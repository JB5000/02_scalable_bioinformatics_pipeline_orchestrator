#!/usr/bin/env python3
"""
Benchmark realista e justo (ISO-PARAM) entre All-to-All e Transformer.

Inclui:
- Corpus real extraído dos ficheiros do projeto
- Tokenização e dataset de next-token prediction
- Split train/val/test
- Treino mini-batch
- Matching de parâmetros por número de layers
- Métricas: accuracy, loss, perplexity, tempo, latência, throughput, FLOPs, eficiência
- Geração de gráficos comparativos completos
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

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.all_to_all_model import AllToAllModel
from models.simple_transformer import SimpleTransformer


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def collect_text_files(project_root: Path, max_files: int = 300):
    patterns = ["**/*.md", "**/*.py", "**/*.txt"]
    candidates = []

    for pat in patterns:
        candidates.extend(project_root.glob(pat))

    # Excluir diretórios gerados / pesados
    excluded_parts = {"outputs", "__pycache__", ".git", ".venv", "work"}

    filtered = []
    for path in candidates:
        if not path.is_file():
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        filtered.append(path)

    filtered = sorted(set(filtered))
    return filtered[:max_files]


def read_corpus(paths, max_chars: int = 2_000_000):
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
    # Tokens de palavras com suporte a acentos
    # Ex: "ação", "microbiome", "v4", etc.
    return re.findall(r"[a-zà-ÿ0-9_]+", text.lower())


def build_vocab(tokens, max_vocab: int = 8000, min_freq: int = 2):
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
    unk = stoi["<UNK>"]
    return [stoi.get(t, unk) for t in tokens]


def make_sequences(ids, seq_len: int, stride: int, max_samples: int, seed: int):
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
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def valid_heads(embed_dim: int):
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
    perplexity = math.exp(min(avg_loss, 20.0))

    return {
        "loss": avg_loss,
        "accuracy": accuracy,
        "perplexity": perplexity,
    }


def measure_latency(model, sample_batch, repeats=120):
    model.eval()

    with torch.no_grad():
        for _ in range(20):
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

    sample_b1 = next(iter(test_loader))[0][:1].to(device)

    # batch para throughput
    sample_large = next(iter(test_loader))[0]
    sample_large = sample_large[: min(len(sample_large), 64)].to(device)

    infer_ms_b1 = measure_latency(model, sample_b1, repeats=200)
    infer_ms_bN = measure_latency(model, sample_large, repeats=120)

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
        "acc_per_mparam": (test_metrics["accuracy"] / params) * 1_000_000,
        "history": train_history,
    }


def make_line(ax, x, y1, y2, label1, label2, title, ylabel):
    ax.plot(x, y1, marker="o", linewidth=2, label=label1)
    ax.plot(x, y2, marker="s", linewidth=2, label=label2)
    ax.set_title(title)
    ax.set_xlabel("Layers")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)


def generate_plots(results, output_dir: Path):
    layers = [r["layers"] for r in results]

    a2a = [r["all_to_all"] for r in results]
    tf = [r["transformer"] for r in results]

    # Séries
    a2a_params = [m["params"] for m in a2a]
    tf_params = [m["params"] for m in tf]

    a2a_acc = [m["test"]["accuracy"] * 100 for m in a2a]
    tf_acc = [m["test"]["accuracy"] * 100 for m in tf]

    a2a_ppl = [m["test"]["perplexity"] for m in a2a]
    tf_ppl = [m["test"]["perplexity"] for m in tf]

    a2a_train = [m["train_time_s"] for m in a2a]
    tf_train = [m["train_time_s"] for m in tf]

    a2a_inf1 = [m["infer_ms_batch1"] for m in a2a]
    tf_inf1 = [m["infer_ms_batch1"] for m in tf]

    a2a_infN = [m["infer_ms_batchN"] for m in a2a]
    tf_infN = [m["infer_ms_batchN"] for m in tf]

    a2a_thr = [m["throughput_tok_s_batchN"] for m in a2a]
    tf_thr = [m["throughput_tok_s_batchN"] for m in tf]

    a2a_flops = [m["flops_per_forward"] or np.nan for m in a2a]
    tf_flops = [m["flops_per_forward"] or np.nan for m in tf]

    a2a_eff = [m["acc_per_mparam"] for m in a2a]
    tf_eff = [m["acc_per_mparam"] for m in tf]

    # Figura principal 3x3
    fig, axes = plt.subplots(3, 3, figsize=(20, 14))
    fig.suptitle("Benchmark Realista ISO-PARAM: All-to-All vs Transformer", fontsize=16, fontweight="bold")

    make_line(axes[0, 0], layers, a2a_params, tf_params, "All-to-All", "Transformer", "Paridade de Parâmetros", "# params")
    make_line(axes[0, 1], layers, a2a_acc, tf_acc, "All-to-All", "Transformer", "Accuracy de Teste", "Accuracy (%)")
    make_line(axes[0, 2], layers, a2a_ppl, tf_ppl, "All-to-All", "Transformer", "Perplexity de Teste", "Perplexity")

    make_line(axes[1, 0], layers, a2a_train, tf_train, "All-to-All", "Transformer", "Tempo Total de Treino", "segundos")
    make_line(axes[1, 1], layers, a2a_inf1, tf_inf1, "All-to-All", "Transformer", "Latência Inferência (batch=1)", "ms")
    make_line(axes[1, 2], layers, a2a_infN, tf_infN, "All-to-All", "Transformer", "Latência Inferência (batch=N)", "ms")

    make_line(axes[2, 0], layers, a2a_thr, tf_thr, "All-to-All", "Transformer", "Throughput (batch=N)", "tokens/s")
    make_line(axes[2, 1], layers, a2a_flops, tf_flops, "All-to-All", "Transformer", "FLOPs por Forward", "FLOPs")
    make_line(axes[2, 2], layers, a2a_eff, tf_eff, "All-to-All", "Transformer", "Eficiência (acc/M params)", "acc per M param")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    overview_path = output_dir / "benchmark_realistic_overview.png"
    fig.savefig(overview_path, dpi=220)
    plt.close(fig)

    # Pareto: accuracy vs train time
    fig2, ax = plt.subplots(figsize=(10, 7))
    for i, r in enumerate(results):
        ax.scatter(
            r["all_to_all"]["train_time_s"],
            r["all_to_all"]["test"]["accuracy"] * 100,
            s=max(r["all_to_all"]["params"] / 4000, 20),
            marker="o",
            alpha=0.8,
            label="All-to-All" if i == 0 else None,
        )
        ax.text(
            r["all_to_all"]["train_time_s"],
            r["all_to_all"]["test"]["accuracy"] * 100,
            f"L{r['layers']}",
            fontsize=8,
        )

        ax.scatter(
            r["transformer"]["train_time_s"],
            r["transformer"]["test"]["accuracy"] * 100,
            s=max(r["transformer"]["params"] / 4000, 20),
            marker="s",
            alpha=0.8,
            label="Transformer" if i == 0 else None,
        )
        ax.text(
            r["transformer"]["train_time_s"],
            r["transformer"]["test"]["accuracy"] * 100,
            f"L{r['layers']}",
            fontsize=8,
        )

    ax.set_title("Pareto: Accuracy vs Tempo de Treino (tamanho do ponto = #params)")
    ax.set_xlabel("Tempo de treino (s)")
    ax.set_ylabel("Accuracy (%)")
    ax.grid(alpha=0.25)
    ax.legend()

    pareto_path = output_dir / "benchmark_realistic_pareto.png"
    fig2.savefig(pareto_path, dpi=220)
    plt.close(fig2)

    # Ratios
    ratio_train = [r["all_to_all"]["train_time_s"] / max(r["transformer"]["train_time_s"], 1e-9) for r in results]
    ratio_inf = [r["all_to_all"]["infer_ms_batch1"] / max(r["transformer"]["infer_ms_batch1"], 1e-9) for r in results]
    ratio_flops = [
        (r["all_to_all"]["flops_per_forward"] / max(r["transformer"]["flops_per_forward"], 1e-9))
        if (r["all_to_all"]["flops_per_forward"] and r["transformer"]["flops_per_forward"])
        else np.nan
        for r in results
    ]

    fig3, ax3 = plt.subplots(figsize=(10, 6))
    ax3.plot(layers, ratio_train, marker="o", label="A2A/TF treino")
    ax3.plot(layers, ratio_inf, marker="s", label="A2A/TF inferência b1")
    ax3.plot(layers, ratio_flops, marker="^", label="A2A/TF FLOPs")
    ax3.axhline(1.0, color="black", linewidth=1, linestyle="--")
    ax3.set_title("Ratios A2A/Transformer (<1 favorece All-to-All)")
    ax3.set_xlabel("Layers")
    ax3.set_ylabel("Ratio")
    ax3.grid(alpha=0.25)
    ax3.legend()

    ratio_path = output_dir / "benchmark_realistic_ratios.png"
    fig3.savefig(ratio_path, dpi=220)
    plt.close(fig3)

    return {
        "overview": str(overview_path),
        "pareto": str(pareto_path),
        "ratios": str(ratio_path),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", type=str, default="4,6,8,10,12")
    parser.add_argument("--seq-len", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--alltoall-embed", type=int, default=64)
    parser.add_argument("--max-files", type=int, default=300)
    parser.add_argument("--max-chars", type=int, default=2_000_000)
    parser.add_argument("--max-samples", type=int, default=6000)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    set_seed(args.seed)
    torch.set_num_threads(args.threads)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    project_root = Path(__file__).parent.parent
    files = collect_text_files(project_root, max_files=args.max_files)
    corpus = read_corpus(files, max_chars=args.max_chars)

    tokens = tokenize_text(corpus)
    stoi = build_vocab(tokens, max_vocab=8000, min_freq=2)
    ids = encode_tokens(tokens, stoi)

    xs, ys = make_sequences(
        ids,
        seq_len=args.seq_len,
        stride=args.stride,
        max_samples=args.max_samples,
        seed=args.seed,
    )

    xtr, ytr, xva, yva, xte, yte = split_dataset(xs, ys, seed=args.seed, val_ratio=0.1, test_ratio=0.1)

    # Tensores
    xtr_t = torch.tensor(xtr, dtype=torch.long)
    ytr_t = torch.tensor(ytr, dtype=torch.long)
    xva_t = torch.tensor(xva, dtype=torch.long)
    yva_t = torch.tensor(yva, dtype=torch.long)
    xte_t = torch.tensor(xte, dtype=torch.long)
    yte_t = torch.tensor(yte, dtype=torch.long)

    train_loader = DataLoader(TensorDataset(xtr_t, ytr_t), batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(xva_t, yva_t), batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(TensorDataset(xte_t, yte_t), batch_size=args.batch_size, shuffle=False)

    layers = [int(v.strip()) for v in args.layers.split(",") if v.strip()]
    vocab_size = len(stoi)

    print("=" * 120, flush=True)
    print("BENCHMARK REALISTA ISO-PARAM: ALL-TO-ALL vs TRANSFORMER", flush=True)
    print("=" * 120, flush=True)
    print(
        (
            f"device={device} | files={len(files)} | tokens={len(tokens):,} | vocab={vocab_size:,} | "
            f"seq_len={args.seq_len} | samples={len(xs):,} | train/val/test={len(xtr)}/{len(xva)}/{len(xte)}"
        ),
        flush=True,
    )
    print(
        (
            f"layers={layers} | epochs={args.epochs} | batch={args.batch_size} | "
            f"alltoall_embed={args.alltoall_embed} | lr={args.lr}"
        ),
        flush=True,
    )

    all_results = []

    for n_layers in layers:
        print("\n" + "-" * 120, flush=True)
        print(f"Layers={n_layers}", flush=True)
        print("-" * 120, flush=True)

        set_seed(args.seed)
        a2a_model = AllToAllModel(
            vocab_size=vocab_size,
            seq_len=args.seq_len,
            embed_dim=args.alltoall_embed,
            layers=n_layers,
            dropout=args.dropout,
        ).to(device)

        target_params = count_params(a2a_model)

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

        set_seed(args.seed)
        tf_model = SimpleTransformer(
            vocab_size=vocab_size,
            seq_len=args.seq_len,
            embed_dim=tf_cfg["embed_dim"],
            num_layers=n_layers,
            num_heads=tf_cfg["num_heads"],
            dropout=args.dropout,
        ).to(device)

        tf_gap = abs(count_params(tf_model) - target_params) / max(target_params, 1) * 100

        print(
            (
                f"ISO-PARAM: A2A={target_params:,} | TF={count_params(tf_model):,} | gap={tf_gap:.2f}% | "
                f"TF embed={tf_cfg['embed_dim']} heads={tf_cfg['num_heads']}"
            ),
            flush=True,
        )

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

        row = {
            "layers": n_layers,
            "param_gap_pct": tf_gap,
            "all_to_all": a2a_metrics,
            "transformer": tf_metrics,
            "transformer_config": tf_cfg,
        }
        all_results.append(row)

        print(
            (
                f"A2A test_acc={a2a_metrics['test']['accuracy']:.2%} | "
                f"TF test_acc={tf_metrics['test']['accuracy']:.2%}"
            ),
            flush=True,
        )
        print(
            (
                f"A2A train={a2a_metrics['train_time_s']:.2f}s | "
                f"TF train={tf_metrics['train_time_s']:.2f}s"
            ),
            flush=True,
        )
        print(
            (
                f"A2A infer_b1={a2a_metrics['infer_ms_batch1']:.3f}ms | "
                f"TF infer_b1={tf_metrics['infer_ms_batch1']:.3f}ms"
            ),
            flush=True,
        )

    output_dir = project_root / "outputs" / "metrics"
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "benchmark": "realistic_iso_param_alltoall_vs_transformer",
        "device": device,
        "seed": args.seed,
        "seq_len": args.seq_len,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "layers": layers,
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

    json_path = output_dir / "benchmark_realistic_iso_alltoall_vs_transformer.json"
    json_path.write_text(json.dumps(meta, indent=2))

    plot_paths = generate_plots(all_results, output_dir)

    print("\n" + "=" * 120, flush=True)
    print("RESUMO FINAL", flush=True)
    print("=" * 120, flush=True)
    print(f"JSON: {json_path}", flush=True)
    print(f"PLOT overview: {plot_paths['overview']}", flush=True)
    print(f"PLOT pareto:   {plot_paths['pareto']}", flush=True)
    print(f"PLOT ratios:   {plot_paths['ratios']}", flush=True)


if __name__ == "__main__":
    main()
