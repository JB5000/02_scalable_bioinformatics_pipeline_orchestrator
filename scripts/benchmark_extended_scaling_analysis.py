#!/usr/bin/env python3
"""
Benchmark estendido com scaling: All-to-All vs Transformer
- Layers: 4, 6, 8, 10, 12, 14, 16, 18, 20
- Dataset: 100K+ tokens, 8000+ amostras
- ISO-PARAM matching para comparação justa
- Análise de tendências de escalação
"""

import argparse
import json
import math
import random
import re
import time
from collections import Counter
from pathlib import Path
import sys
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.all_to_all_model import AllToAllModel
from models.simple_transformer import SimpleTransformer


def log_msg(msg: str, level: str = "INFO"):
    """Log com timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{timestamp}] [{level:7s}]"
    print(f"{prefix} {msg}", flush=True)


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def collect_text_files(project_root: Path, max_files: int = 500):
    """Coleta ficheiros de texto do projecto"""
    patterns = ["**/*.md", "**/*.py", "**/*.txt", "**/*.sh", "**/*.csv"]
    candidates = []

    for pat in patterns:
        candidates.extend(project_root.glob(pat))

    # Excluir diretórios pesados
    excluded_parts = {"outputs", "__pycache__", ".git", ".venv", "work", ".pytest_cache", "node_modules"}

    filtered = []
    for path in candidates:
        if not path.is_file():
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        try:
            if path.stat().st_size > 50_000_000:  # Skip huge files
                continue
        except Exception:
            continue
        filtered.append(path)

    filtered = sorted(set(filtered))
    return filtered[:max_files]


def read_corpus(paths, max_chars: int = 5_000_000):
    """Lê corpus de ficheiros"""
    chunks = []
    total = 0

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if not text.strip():
            continue

        remaining = max_chars - total
        if remaining <= 0:
            break

        if len(text) > remaining:
            text = text[:remaining]

        chunks.append(text)
        total += len(text)

    return "\n".join(chunks)


def tokenize_text(text: str):
    """Tokeniza texto em palavras"""
    return re.findall(r"[a-zà-ÿ0-9_]+", text.lower())


def build_vocab(tokens, max_vocab: int = 10000, min_freq: int = 1):
    """Constrói vocabulário"""
    counter = Counter(tokens)

    vocab_items = [
        token
        for token, freq in counter.most_common(max_vocab)
        if freq >= min_freq
    ]

    stoi = {"<PAD>": 0, "<UNK>": 1}
    for token in vocab_items:
        if token not in stoi:
            stoi[token] = len(stoi)

    return stoi


def encode_tokens(tokens, stoi):
    """Codifica tokens"""
    unk = stoi["<UNK>"]
    return [stoi.get(t, unk) for t in tokens]


def make_sequences(ids, seq_len: int, stride: int, max_samples: int, seed: int):
    """Cria sequências para next-token prediction"""
    xs = []
    ys = []

    for i in range(0, len(ids) - seq_len - 1, stride):
        x = ids[i : i + seq_len]
        y = ids[i + 1 : i + seq_len + 1]
        xs.append(x)
        ys.append(y)

    if len(xs) == 0:
        raise ValueError("Dados insuficientes para construir sequências.")

    if len(xs) > max_samples:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(xs), size=max_samples, replace=False)
        idx = np.sort(idx)
        xs = [xs[i] for i in idx]
        ys = [ys[i] for i in idx]

    return np.array(xs, dtype=np.int64), np.array(ys, dtype=np.int64)


def split_dataset(xs, ys, seed: int, val_ratio=0.1, test_ratio=0.1):
    """Divide dataset em train/val/test"""
    n = len(xs)
    idx = np.arange(n)

    rng = np.random.default_rng(seed)
    rng.shuffle(idx)

    test_n = int(n * test_ratio)
    val_n = int(n * val_ratio)
    train_n = n - val_n - test_n

    train_idx = idx[:train_n]
    val_idx = idx[train_n : train_n + val_n]
    test_idx = idx[train_n + val_n :]

    return (
        xs[train_idx], ys[train_idx],
        xs[val_idx], ys[val_idx],
        xs[test_idx], ys[test_idx],
    )


def count_params(model):
    """Conta parâmetros treináveis"""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def valid_heads(embed_dim: int):
    """Retorna números de heads válidos para embed_dim"""
    options = [16, 12, 10, 8, 6, 5, 4, 3, 2, 1]
    return [h for h in options if embed_dim % h == 0]


def find_transformer_match(
    target_params: int,
    vocab_size: int,
    seq_len: int,
    num_layers: int,
    dropout: float,
    embed_min: int = 24,
    embed_max: int = 320,
    embed_step: int = 2,
):
    """Encontra configuração Transformer com parâmetros ≈ target_params"""
    best = None

    for embed_dim in range(embed_min, embed_max + 1, embed_step):
        for heads in valid_heads(embed_dim):
            model = SimpleTransformer(
                vocab_size=vocab_size,
                seq_len=seq_len,
                embed_dim=embed_dim,
                num_layers=num_layers,
                num_heads=heads,
                dropout=dropout,
            )
            params = count_params(model)
            rel_error = abs(params - target_params) / max(target_params, 1)

            cand = {
                "embed_dim": embed_dim,
                "num_heads": heads,
                "params": params,
                "rel_error": rel_error,
            }

            if best is None or cand["rel_error"] < best["rel_error"]:
                best = cand

    return best


def evaluate_model(model, loader, seq_len, device):
    """Avalia modelo no dataset"""
    criterion = nn.CrossEntropyLoss(reduction="sum")
    model.eval()

    total_loss = 0.0
    total_tokens = 0
    total_correct = 0

    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            yb = yb.to(device)

            outputs = model(xb)
            use_positions = min(seq_len, len(outputs))

            for pos in range(use_positions):
                logits = outputs[pos]
                tgt = yb[:, pos]

                total_loss += float(criterion(logits, tgt).item())
                pred = logits.argmax(dim=-1)
                total_correct += int((pred == tgt).sum().item())
                total_tokens += int(tgt.numel())

    avg_loss = total_loss / max(total_tokens, 1)
    accuracy = total_correct / max(total_tokens, 1)
    perplexity = math.exp(min(avg_loss, 25.0))

    return {
        "loss": avg_loss,
        "accuracy": accuracy,
        "perplexity": perplexity,
    }


def measure_latency(model, sample_batch, repeats=100):
    """Mede latência de inferência"""
    model.eval()

    with torch.no_grad():
        for _ in range(10):
            _ = model(sample_batch)

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    t0 = time.time()
    with torch.no_grad():
        for _ in range(repeats):
            _ = model(sample_batch)

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    elapsed = time.time() - t0
    return (elapsed / repeats) * 1000.0


def train_model(
    model,
    train_loader,
    val_loader,
    test_loader,
    seq_len,
    epochs,
    lr,
    device,
):
    """Treina modelo com early stopping"""
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    train_history = []
    best_val_loss = float("inf")
    best_state = None

    t0 = time.time()

    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        seen_batches = 0

        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)

            optimizer.zero_grad()
            outputs = model(xb)
            use_positions = min(seq_len, len(outputs))

            loss = 0.0
            for pos in range(use_positions):
                loss = loss + criterion(outputs[pos], yb[:, pos])
            loss = loss / use_positions

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            running_loss += float(loss.item())
            seen_batches += 1

        train_loss = running_loss / max(seen_batches, 1)
        val_metrics = evaluate_model(model, val_loader, seq_len, device)
        
        elapsed_epoch = time.time() - t0
        log_msg(f"    Epoch {epoch + 1}/{epochs} | Loss: {train_loss:.4f} | Val Loss: {val_metrics['loss']:.4f} | Val Acc: {val_metrics['accuracy']*100:.1f}% | Tempo: {elapsed_epoch/60:.1f} min", "EPOCH")

        train_history.append(
            {
                "epoch": epoch + 1,
                "train_loss": train_loss,
                "val_loss": val_metrics["loss"],
                "val_acc": val_metrics["accuracy"],
                "val_ppl": val_metrics["perplexity"],
            }
        )

        if val_metrics["loss"] < best_val_loss:
            best_val_loss = val_metrics["loss"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    train_time = time.time() - t0

    if best_state is not None:
        model.load_state_dict(best_state)

    val_metrics = evaluate_model(model, val_loader, seq_len, device)
    test_metrics = evaluate_model(model, test_loader, seq_len, device)

    # Mede latência
    sample_b1 = next(iter(test_loader))[0][:1].to(device)
    sample_large = next(iter(test_loader))[0]
    sample_large = sample_large[: min(len(sample_large), 64)].to(device)

    infer_ms_b1 = measure_latency(model, sample_b1, repeats=150)
    infer_ms_bN = measure_latency(model, sample_large, repeats=80)

    tokens_b1 = sample_b1.shape[0] * sample_b1.shape[1]
    tokens_bN = sample_large.shape[0] * sample_large.shape[1]

    throughput_b1 = tokens_b1 / max(infer_ms_b1 / 1000.0, 1e-9)
    throughput_bN = tokens_bN / max(infer_ms_bN / 1000.0, 1e-9)

    flops = None
    if hasattr(model, "estimate_flops_per_forward"):
        try:
            flops = float(model.estimate_flops_per_forward())
        except Exception:
            flops = None

    params = count_params(model)

    return {
        "params": params,
        "param_memory_mb": params * 4 / (1024**2),
        "flops_per_forward": flops,
        "train_time_s": train_time,
        "epoch_time_s": train_time / max(epochs, 1),
        "val": val_metrics,
        "test": test_metrics,
        "infer_ms_batch1": infer_ms_b1,
        "infer_ms_batchN": infer_ms_bN,
        "throughput_tok_s_batch1": throughput_b1,
        "throughput_tok_s_batchN": throughput_bN,
        "acc_per_mparam": (test_metrics["accuracy"] / params) * 1_000_000 if params > 0 else 0,
        "history": train_history,
    }


def generate_trend_visualizations(results, output_dir: Path):
    """Gera visualizações de tendências de scaling"""
    layers = np.array([r["layers"] for r in results])

    a2a = [r["all_to_all"] for r in results]
    tf = [r["transformer"] for r in results]

    # Dados
    a2a_params = np.array([m["params"] for m in a2a])
    tf_params = np.array([m["params"] for m in tf])

    a2a_acc = np.array([m["test"]["accuracy"] * 100 for m in a2a])
    tf_acc = np.array([m["test"]["accuracy"] * 100 for m in tf])

    a2a_ppl = np.array([m["test"]["perplexity"] for m in a2a])
    tf_ppl = np.array([m["test"]["perplexity"] for m in tf])

    a2a_train = np.array([m["train_time_s"] for m in a2a])
    tf_train = np.array([m["train_time_s"] for m in tf])

    a2a_inf1 = np.array([m["infer_ms_batch1"] for m in a2a])
    tf_inf1 = np.array([m["infer_ms_batch1"] for m in tf])

    a2a_infN = np.array([m["infer_ms_batchN"] for m in a2a])
    tf_infN = np.array([m["infer_ms_batchN"] for m in tf])

    a2a_thr = np.array([m["throughput_tok_s_batchN"] for m in a2a])
    tf_thr = np.array([m["throughput_tok_s_batchN"] for m in tf])

    a2a_flops = np.array([m["flops_per_forward"] or np.nan for m in a2a])
    tf_flops = np.array([m["flops_per_forward"] or np.nan for m in tf])

    # ========== Figura 1: Grid 3x3 completo ==========
    fig, axes = plt.subplots(3, 3, figsize=(22, 15))
    fig.suptitle("Benchmark Estendido: Todas as Tendências de Scaling", fontsize=18, fontweight="bold")

    # linha 0: Parâmetros, Accuracy, Perplexity
    axes[0, 0].plot(layers, a2a_params, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[0, 0].plot(layers, tf_params, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[0, 0].set_title("Parâmetros vs Layers", fontsize=12, fontweight="bold")
    axes[0, 0].set_xlabel("Layers")
    axes[0, 0].set_ylabel("# Parâmetros")
    axes[0, 0].grid(alpha=0.3)
    axes[0, 0].legend(fontsize=10)

    axes[0, 1].plot(layers, a2a_acc, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[0, 1].plot(layers, tf_acc, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[0, 1].set_title("Accuracy de Teste vs Layers", fontsize=12, fontweight="bold")
    axes[0, 1].set_xlabel("Layers")
    axes[0, 1].set_ylabel("Accuracy (%)")
    axes[0, 1].grid(alpha=0.3)
    axes[0, 1].legend(fontsize=10)

    axes[0, 2].plot(layers, a2a_ppl, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[0, 2].plot(layers, tf_ppl, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[0, 2].set_title("Perplexity vs Layers", fontsize=12, fontweight="bold")
    axes[0, 2].set_xlabel("Layers")
    axes[0, 2].set_ylabel("Perplexity")
    axes[0, 2].grid(alpha=0.3)
    axes[0, 2].legend(fontsize=10)

    # linha 1: Tempo, Latência B1, Latência BN
    axes[1, 0].plot(layers, a2a_train, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[1, 0].plot(layers, tf_train, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[1, 0].set_title("Tempo Total de Treino", fontsize=12, fontweight="bold")
    axes[1, 0].set_xlabel("Layers")
    axes[1, 0].set_ylabel("Segundos")
    axes[1, 0].grid(alpha=0.3)
    axes[1, 0].legend(fontsize=10)

    axes[1, 1].plot(layers, a2a_inf1, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[1, 1].plot(layers, tf_inf1, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[1, 1].set_title("Latência Inferência (batch=1)", fontsize=12, fontweight="bold")
    axes[1, 1].set_xlabel("Layers")
    axes[1, 1].set_ylabel("ms")
    axes[1, 1].grid(alpha=0.3)
    axes[1, 1].legend(fontsize=10)

    axes[1, 2].plot(layers, a2a_infN, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[1, 2].plot(layers, tf_infN, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[1, 2].set_title("Latência Inferência (batch=N)", fontsize=12, fontweight="bold")
    axes[1, 2].set_xlabel("Layers")
    axes[1, 2].set_ylabel("ms")
    axes[1, 2].grid(alpha=0.3)
    axes[1, 2].legend(fontsize=10)

    # linha 2: Throughput, FLOPs, Expoente de Escalação
    axes[2, 0].plot(layers, a2a_thr, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[2, 0].plot(layers, tf_thr, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[2, 0].set_title("Throughput (batch=N)", fontsize=12, fontweight="bold")
    axes[2, 0].set_xlabel("Layers")
    axes[2, 0].set_ylabel("tokens/s")
    axes[2, 0].grid(alpha=0.3)
    axes[2, 0].legend(fontsize=10)

    axes[2, 1].plot(layers, a2a_flops, marker="o", linewidth=2.5, markersize=8, label="All-to-All", color="tab:blue")
    axes[2, 1].plot(layers, tf_flops, marker="s", linewidth=2.5, markersize=8, label="Transformer", color="tab:orange")
    axes[2, 1].set_title("FLOPs por Forward", fontsize=12, fontweight="bold")
    axes[2, 1].set_xlabel("Layers")
    axes[2, 1].set_ylabel("FLOPs")
    axes[2, 1].grid(alpha=0.3)
    axes[2, 1].legend(fontsize=10)

    # Speedup ratios
    speedup_train = a2a_train / np.maximum(tf_train, 1e-9)
    speedup_inf1 = a2a_inf1 / np.maximum(tf_inf1, 1e-9)
    speedup_infN = a2a_infN / np.maximum(tf_infN, 1e-9)

    axes[2, 2].plot(layers, speedup_train, marker="o", linewidth=2.5, markersize=8, label="Train speedup", color="tab:green")
    axes[2, 2].plot(layers, speedup_inf1, marker="^", linewidth=2.5, markersize=8, label="Inf B=1 speedup", color="tab:red")
    axes[2, 2].plot(layers, speedup_infN, marker="s", linewidth=2.5, markersize=8, label="Inf B=N speedup", color="tab:purple")
    axes[2, 2].axhline(y=1.0, color="black", linestyle="--", linewidth=1, alpha=0.5, label="Paridade")
    axes[2, 2].set_title("Speedup All-to-All (< 1 = mais rápido)", fontsize=12, fontweight="bold")
    axes[2, 2].set_xlabel("Layers")
    axes[2, 2].set_ylabel("Speedup Ratio")
    axes[2, 2].grid(alpha=0.3)
    axes[2, 2].legend(fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    trend_path = output_dir / "benchmark_extended_trends.png"
    fig.savefig(trend_path, dpi=220)
    plt.close(fig)

    print(f"  ✓ Trend visualization: {trend_path}")

    # ========== Figura 2: Scalação de Parâmetros com Regressão ==========
    fig2, ax = plt.subplots(figsize=(12, 7))

    ax.plot(layers, a2a_params, marker="o", linewidth=2.5, markersize=10, label="All-to-All", color="tab:blue")
    ax.plot(layers, tf_params, marker="s", linewidth=2.5, markersize=10, label="Transformer", color="tab:orange")

    # Fit polinômio
    z_a2a = np.polyfit(layers, a2a_params, 2)
    p_a2a = np.poly1d(z_a2a)
    z_tf = np.polyfit(layers, tf_params, 2)
    p_tf = np.poly1d(z_tf)

    x_fine = np.linspace(layers.min(), layers.max(), 100)
    ax.plot(x_fine, p_a2a(x_fine), linestyle="--", linewidth=1.5, alpha=0.7, color="tab:blue")
    ax.plot(x_fine, p_tf(x_fine), linestyle="--", linewidth=1.5, alpha=0.7, color="tab:orange")

    ax.set_title("Escalação de Parâmetros com Fit Polinomial", fontsize=14, fontweight="bold")
    ax.set_xlabel("Número de Layers", fontsize=12)
    ax.set_ylabel("Contagem de Parâmetros", fontsize=12)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=11)

    scaling_path = output_dir / "benchmark_extended_param_scaling.png"
    fig2.savefig(scaling_path, dpi=220)
    plt.close(fig2)

    print(f"  ✓ Parameter scaling: {scaling_path}")

    # ========== Figura 3: Pareto - Tempo vs Accuracy ==========
    fig3, ax = plt.subplots(figsize=(12, 8))

    for i, layer_count in enumerate(layers):
        # All-to-All
        ax.scatter(
            a2a_train[i],
            a2a_acc[i],
            s=300,
            marker="o",
            alpha=0.7,
            color="tab:blue",
            edgecolor="darkblue",
            linewidth=2
        )
        ax.text(a2a_train[i], a2a_acc[i] - 0.3, f"L{int(layer_count)}", fontsize=10, ha="center", fontweight="bold")

        # Transformer
        ax.scatter(
            tf_train[i],
            tf_acc[i],
            s=300,
            marker="s",
            alpha=0.7,
            color="tab:orange",
            edgecolor="darkorange",
            linewidth=2
        )
        ax.text(tf_train[i], tf_acc[i] + 0.3, f"L{int(layer_count)}", fontsize=10, ha="center", fontweight="bold")

    # Curva de tendência
    ax.plot(a2a_train, a2a_acc, linestyle="--", linewidth=1.5, alpha=0.5, color="tab:blue")
    ax.plot(tf_train, tf_acc, linestyle="--", linewidth=1.5, alpha=0.5, color="tab:orange")

    ax.set_title("Pareto: Tempo de Treino vs Accuracy (Escalação de Layers)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Tempo Total de Treino (s)", fontsize=12)
    ax.set_ylabel("Accuracy de Teste (%)", fontsize=12)
    ax.grid(alpha=0.3)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="tab:blue", edgecolor="darkblue", label="All-to-All"),
        Patch(facecolor="tab:orange", edgecolor="darkorange", label="Transformer"),
    ]
    ax.legend(handles=legend_elements, fontsize=11)

    pareto_path = output_dir / "benchmark_extended_pareto.png"
    fig3.savefig(pareto_path, dpi=220)
    plt.close(fig3)

    print(f"  ✓ Pareto chart: {pareto_path}")

    # ========== Figura 4: Ratios de Speedup ==========
    fig4, ax = plt.subplots(figsize=(12, 7))

    width = 0.35
    x = np.arange(len(layers))

    bars1 = ax.bar(x - width/2, speedup_train, width, label="Training Time", color="tab:blue", alpha=0.8)
    bars2 = ax.bar(x, speedup_inf1, width, label="Inference (B=1)", color="tab:orange", alpha=0.8)
    bars3 = ax.bar(x + width/2, speedup_infN, width, label="Inference (B=N)", color="tab:green", alpha=0.8)

    ax.axhline(y=1.0, color="red", linestyle="--", linewidth=2, label="Paridade (All-to-All = Transformer)")
    ax.set_title("Speedup All-to-All vs Transformer (< 1 = All-to-All mais rápido)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Número de Layers", fontsize=12)
    ax.set_ylabel("Speedup Ratio", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels([f"L{int(l)}" for l in layers])
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=11)

    # Adiciona valores nas barras
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.2f}x',
                   ha='center', va='bottom', fontsize=8)

    speedup_path = output_dir / "benchmark_extended_speedup_ratios.png"
    fig4.savefig(speedup_path, dpi=220)
    plt.close(fig4)

    print(f"  ✓ Speedup ratios: {speedup_path}")

    return {
        "trends": trend_path,
        "param_scaling": scaling_path,
        "pareto": pareto_path,
        "speedup": speedup_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", type=str, default="4,6,8,10,12,14,16,18,20")
    parser.add_argument("--seq-len", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--alltoall-embed", type=int, default=64)
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-chars", type=int, default=5_000_000)
    parser.add_argument("--max-samples", type=int, default=10000)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    set_seed(args.seed)
    torch.set_num_threads(args.threads)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    project_root = Path(__file__).parent.parent
    files = collect_text_files(project_root, max_files=args.max_files)

    log_msg("▬" * 70, "START")
    log_msg("BENCHMARK ESTENDIDO DE SCALING: ALL-TO-ALL VS TRANSFORMER", "START")
    log_msg("▬" * 70, "START")
    log_msg(f"Device: {device} | Arquivos encontrados: {len(files)}", "SETUP")
    log_msg(f"Lendo corpus (máx {args.max_chars/1e6:.1f}M caracteres)...", "SETUP")

    text = read_corpus(files, max_chars=args.max_chars)
    log_msg(f"Corpus lido: {len(text):,} caracteres", "SETUP")
    
    log_msg(f"Tokenizando texto...", "SETUP")
    tokens = tokenize_text(text)
    log_msg(f"Tokens extraídos: {len(tokens):,}", "SETUP")
    
    log_msg(f"Construindo vocabulário (máx 10K)...", "SETUP")
    stoi = build_vocab(tokens, max_vocab=10000, min_freq=1)

    ids = encode_tokens(tokens, stoi)
    log_msg(f"Tokens codificados: {len(ids):,}", "SETUP")

    log_msg(f"Criando sequências (seq_len={args.seq_len}, stride={args.stride})...", "SETUP")
    xs, ys = make_sequences(
        ids,
        seq_len=args.seq_len,
        stride=args.stride,
        max_samples=args.max_samples,
        seed=args.seed,
    )
    log_msg(f"Sequências criadas: {len(xs):,}", "SETUP")

    log_msg(f"Dividindo em train/val/test...", "SETUP")
    xtr, ytr, xva, yva, xte, yte = split_dataset(xs, ys, seed=args.seed, val_ratio=0.1, test_ratio=0.1)
    log_msg(f"Dataset: train={len(xtr):,}, val={len(xva):,}, test={len(xte):,}", "SETUP")

    xtr_t = torch.tensor(xtr, dtype=torch.long)
    ytr_t = torch.tensor(ytr, dtype=torch.long)
    xva_t = torch.tensor(xva, dtype=torch.long)
    yva_t = torch.tensor(yva, dtype=torch.long)
    xte_t = torch.tensor(xte, dtype=torch.long)
    yte_t = torch.tensor(yte, dtype=torch.long)

    train_loader = DataLoader(TensorDataset(xtr_t, ytr_t), batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(xva_t, yva_t), batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(TensorDataset(xte_t, yte_t), batch_size=args.batch_size, shuffle=False)

    layers_list = [int(v.strip()) for v in args.layers.split(",") if v.strip()]
    vocab_size = len(stoi)

    print(
        (
            f"Corpus: {len(tokens):,} tokens | vocab={vocab_size:,} | "
            f"Samples: {len(xs):,} (train/val/test = {len(xtr):,}/{len(xva):,}/{len(xte):,})"
        ),
        flush=True,
    )
    print(
        (
            f"Layers: {layers_list} | Epochs: {args.epochs} | Batch: {args.batch_size} | "
            f"Seq len: {args.seq_len} | A2A embed: {args.alltoall_embed}"
        ),
        flush=True,
    )
    print("=" * 140, flush=True)

    all_results = []
    global_start = time.time()
    total_layers = len(layers_list)
    
    log_msg(f"INICIANDO BENCHMARK COM {total_layers} CONFIGURAÇÕES DE LAYERS", "INIT")
    log_msg(f"Tempo estimado: ~{(total_layers * 3) / 60:.1f} minutos (assumindo ~3 min/layer)", "INIT")

    for idx, n_layers in enumerate(layers_list, 1):
        layer_start = time.time()
        elapsed_global = time.time() - global_start
        
        log_msg(f"[{idx}/{total_layers}] Iniciando teste com {n_layers} layers (tempo global: {elapsed_global/60:.1f} min)", "LAYER")

        set_seed(args.seed)
        a2a_model = AllToAllModel(
            vocab_size=vocab_size,
            seq_len=args.seq_len,
            embed_dim=args.alltoall_embed,
            layers=n_layers,
            dropout=args.dropout,
        ).to(device)

        target_params = count_params(a2a_model)
        log_msg(f"  All-to-All criado: {target_params:,} params", "MODEL")

        tf_cfg = find_transformer_match(
            target_params=target_params,
            vocab_size=vocab_size,
            seq_len=args.seq_len,
            num_layers=n_layers,
            dropout=args.dropout,
            embed_min=24,
            embed_max=320,
            embed_step=2,
        )
        log_msg(f"  Procurando Transformer com ISO-PARAM (target: {target_params:,})...", "MODEL")

        set_seed(args.seed)
        tf_model = SimpleTransformer(
            vocab_size=vocab_size,
            seq_len=args.seq_len,
            embed_dim=tf_cfg["embed_dim"],
            num_layers=n_layers,
            num_heads=tf_cfg["num_heads"],
            dropout=args.dropout,
        ).to(device)

        tf_params = count_params(tf_model)
        tf_gap = abs(tf_params - target_params) / max(target_params, 1) * 100

        log_msg(f"  Transformer criado: {tf_params:,} params (gap: {tf_gap:.1f}%, config: embed_dim={tf_cfg['embed_dim']} heads={tf_cfg['num_heads']})", "MODEL")

        log_msg(f"  Iniciando treino de All-to-All...", "TRAIN")
        a2a_metrics = train_model(
            a2a_model,
            train_loader,
            val_loader,
            test_loader,
            seq_len=args.seq_len,
            epochs=args.epochs,
            lr=args.lr,
            device=device,
        )

        log_msg(f"  Iniciando treino de Transformer...", "TRAIN")
        tf_metrics = train_model(
            tf_model,
            train_loader,
            val_loader,
            test_loader,
            seq_len=args.seq_len,
            epochs=args.epochs,
            lr=args.lr,
            device=device,
        )

        speedup_train = a2a_metrics["train_time_s"] / max(tf_metrics["train_time_s"], 1e-9)
        speedup_inf_b1 = a2a_metrics["infer_ms_batch1"] / max(tf_metrics["infer_ms_batch1"], 1e-9)
        speedup_inf_bN = a2a_metrics["infer_ms_batchN"] / max(tf_metrics["infer_ms_batchN"], 1e-9)

        layer_elapsed = time.time() - layer_start
        elapsed_global = time.time() - global_start
        
        log_msg(f"  ✓ Speedups - Train: {speedup_train:.2f}x | Inf B=1: {speedup_inf_b1:.2f}x | Inf B=N: {speedup_inf_bN:.2f}x", "RESULT")
        log_msg(f"  Tempo para L{n_layers}: {layer_elapsed/60:.1f} min | Total decorrido: {elapsed_global/60:.1f} min", "TIMING")

        # Estima tempo para próximas camadas
        if idx < total_layers:
            avg_time_per_layer = elapsed_global / idx
            remaining_layers = total_layers - idx
            estimated_remaining = (avg_time_per_layer * remaining_layers) / 60
            log_msg(f"  Estimado para {remaining_layers} layers restantes: ~{estimated_remaining:.1f} min", "TIMING")

        all_results.append({
            "layers": n_layers,
            "all_to_all": a2a_metrics,
            "transformer": tf_metrics,
        })

    # Salva resultados
    output_dir = Path(project_root) / "Benchmark_Extended_Scaling"
    output_dir.mkdir(exist_ok=True)
    
    log_msg(f"Guardando resultados em {output_dir}...", "SAVE")

    meta = {
        "benchmark": "extended_scaling_iso_param",
        "device": device,
        "seed": args.seed,
        "seq_len": args.seq_len,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "layers": layers_list,
        "dataset": {
            "files": len(files),
            "tokens": len(tokens),
            "vocab_size": vocab_size,
            "samples": len(xs),
            "train": len(xtr),
            "val": len(xva),
            "test": len(xte),
        },
        "results": all_results,
    }

    json_path = output_dir / "benchmark_extended_scaling.json"
    json_path.write_text(json.dumps(meta, indent=2))
    log_msg(f"JSON guardado: {json_path}", "SAVE")

    # Gera gráficos
    log_msg("Gerando visualizações de tendências...", "VIZ")
    plot_paths = generate_trend_visualizations(all_results, output_dir)

    total_time = time.time() - global_start
    log_msg("=" * 120, "DONE")
    log_msg(f"BENCHMARK COMPLETADO COM SUCESSO!", "DONE")
    log_msg(f"Tempo total: {total_time/60:.1f} minutos ({total_time/3600:.2f} horas)", "DONE")
    log_msg(f"Resultados guardados em: {output_dir}", "DONE")
    log_msg("Visualizações geradas:", "DONE")
    for key, path in plot_paths.items():
        log_msg(f"  ✓ {key}: {path.name}", "DONE")
    log_msg("=" * 120, "DONE")


if __name__ == "__main__":
    main()
