#!/usr/bin/env python3
"""
Benchmark justo (ISO-PARAM) entre All-to-All e Transformer para múltiplos números de layers.

Objetivo:
- Comparar só All-to-All vs Transformer (sem V4)
- Para cada nº de layers, aproximar o nº de parâmetros entre os dois modelos
- Medir accuracy, tempo de treino, latência de inferência, FLOPs e eficiência
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.all_to_all_model import AllToAllModel
from models.simple_transformer import SimpleTransformer


def build_dataset(device: str):
    text = """
o cão é muito bonito
o gato é muito bonito
o cão corre muito rápido
o gato corre muito rápido
o cão come comida
o gato come peixe
o cão é um animal
o gato é um animal
o cão gosta de brincar
o gato gosta de dormir
"""

    words = text.split()
    vocab = sorted(set(words))

    stoi = {w: i + 1 for i, w in enumerate(vocab)}
    stoi["<PAD>"] = 0

    vocab_size = len(stoi)
    seq_len = 4

    tokens = [stoi[w] for w in words]

    data, targets = [], []
    for i in range(len(tokens) - seq_len):
        data.append(tokens[i : i + seq_len])
        targets.append(tokens[i + 1 : i + seq_len + 1])

    data = torch.tensor(data, device=device)
    targets = torch.tensor(targets, device=device)

    return data, targets, vocab_size, seq_len


def count_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def pick_num_heads(embed_dim: int) -> int:
    for h in (8, 4, 2, 1):
        if embed_dim % h == 0:
            return h
    return 1


def find_transformer_config_for_target_params(
    target_params: int,
    vocab_size: int,
    seq_len: int,
    num_layers: int,
    dropout: float,
    embed_min: int = 16,
    embed_max: int = 384,
    embed_step: int = 4,
):
    best = None

    for embed_dim in range(embed_min, embed_max + 1, embed_step):
        num_heads = pick_num_heads(embed_dim)

        model = SimpleTransformer(
            vocab_size=vocab_size,
            seq_len=seq_len,
            embed_dim=embed_dim,
            num_layers=num_layers,
            num_heads=num_heads,
            dropout=dropout,
        )

        params = count_params(model)
        rel_error = abs(params - target_params) / max(target_params, 1)

        item = {
            "embed_dim": embed_dim,
            "num_heads": num_heads,
            "params": params,
            "rel_error": rel_error,
        }

        if best is None or item["rel_error"] < best["rel_error"]:
            best = item

    return best


def measure_inference_ms(model, sample_x, repeats=200):
    model.eval()

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    with torch.no_grad():
        for _ in range(20):
            _ = model(sample_x)

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    t0 = time.time()
    with torch.no_grad():
        for _ in range(repeats):
            _ = model(sample_x)

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    elapsed = time.time() - t0
    return (elapsed / repeats) * 1000.0


def train_and_eval(model, data, targets, seq_len, epochs=40, lr=1e-3):
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    model.train()
    t0 = time.time()

    for _ in range(epochs):
        optimizer.zero_grad()
        outputs = model(data)

        use_positions = min(seq_len, len(outputs))
        loss = 0.0
        for pos in range(use_positions):
            loss = loss + criterion(outputs[pos], targets[:, pos])
        loss = loss / use_positions

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

    train_time = time.time() - t0

    model.eval()
    with torch.no_grad():
        outputs = model(data)
        use_positions = min(seq_len, len(outputs))

        correct = 0
        total = 0
        for pos in range(use_positions):
            pred = outputs[pos].argmax(dim=-1)
            tgt = targets[:, pos]
            correct += int((pred == tgt).sum().item())
            total += int(tgt.numel())

    accuracy = correct / max(total, 1)
    infer_ms = measure_inference_ms(model, data[:1], repeats=200)

    flops = None
    if hasattr(model, "estimate_flops_per_forward"):
        flops = model.estimate_flops_per_forward()

    params = count_params(model)

    return {
        "params": params,
        "flops": flops,
        "train_time_s": train_time,
        "infer_ms": infer_ms,
        "accuracy": accuracy,
        "acc_per_mparam": (accuracy / params) * 1_000_000,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", type=str, default="4,6,8,10,12")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--alltoall-embed", type=int, default=128)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    torch.set_num_threads(args.threads)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    data, targets, vocab_size, seq_len = build_dataset(device)

    layer_list = [int(x.strip()) for x in args.layers.split(",") if x.strip()]

    print("=" * 110, flush=True)
    print("BENCHMARK JUSTO (ISO-PARAM): ALL-TO-ALL vs TRANSFORMER", flush=True)
    print("=" * 110, flush=True)
    print(
        (
            f"device={device} | dataset={len(data)} | vocab={vocab_size} | seq_len={seq_len} | "
            f"layers={layer_list} | epochs={args.epochs}"
        ),
        flush=True,
    )

    all_results = []

    for n_layers in layer_list:
        print("\n" + "-" * 110, flush=True)
        print(f"Layers = {n_layers}", flush=True)
        print("-" * 110, flush=True)

        alltoall = AllToAllModel(
            vocab_size=vocab_size,
            seq_len=seq_len,
            embed_dim=args.alltoall_embed,
            layers=n_layers,
            dropout=args.dropout,
        ).to(device)

        alltoall_params = count_params(alltoall)

        tf_cfg = find_transformer_config_for_target_params(
            target_params=alltoall_params,
            vocab_size=vocab_size,
            seq_len=seq_len,
            num_layers=n_layers,
            dropout=args.dropout,
        )

        transformer = SimpleTransformer(
            vocab_size=vocab_size,
            seq_len=seq_len,
            embed_dim=tf_cfg["embed_dim"],
            num_layers=n_layers,
            num_heads=tf_cfg["num_heads"],
            dropout=args.dropout,
        ).to(device)

        tf_param_gap_pct = abs(count_params(transformer) - alltoall_params) / max(alltoall_params, 1) * 100.0

        print(
            (
                f"Paridade params: A2A={alltoall_params:,} | TF={count_params(transformer):,} "
                f"| gap={tf_param_gap_pct:.2f}% | TF embed={tf_cfg['embed_dim']} heads={tf_cfg['num_heads']}"
            ),
            flush=True,
        )

        a2a_metrics = train_and_eval(
            alltoall,
            data,
            targets,
            seq_len,
            epochs=args.epochs,
            lr=1e-3,
        )

        tf_metrics = train_and_eval(
            transformer,
            data,
            targets,
            seq_len,
            epochs=args.epochs,
            lr=1e-3,
        )

        row = {
            "layers": n_layers,
            "param_gap_pct": tf_param_gap_pct,
            "all_to_all": a2a_metrics,
            "transformer": tf_metrics,
            "transformer_config": tf_cfg,
        }
        all_results.append(row)

        acc_diff_pp = (a2a_metrics["accuracy"] - tf_metrics["accuracy"]) * 100.0
        time_ratio = a2a_metrics["train_time_s"] / max(tf_metrics["train_time_s"], 1e-9)

        print(
            (
                f"A2A acc={a2a_metrics['accuracy']:.2%} | TF acc={tf_metrics['accuracy']:.2%} | "
                f"acc_diff={acc_diff_pp:+.2f}pp"
            ),
            flush=True,
        )
        print(
            (
                f"A2A train={a2a_metrics['train_time_s']:.2f}s | TF train={tf_metrics['train_time_s']:.2f}s | "
                f"A2A/TF={time_ratio:.2f}x"
            ),
            flush=True,
        )
        print(
            (
                f"A2A infer={a2a_metrics['infer_ms']:.3f}ms | TF infer={tf_metrics['infer_ms']:.3f}ms"
            ),
            flush=True,
        )

    print("\n" + "=" * 110, flush=True)
    print("RESUMO FINAL (ISO-PARAM por nº de layers)", flush=True)
    print("=" * 110, flush=True)
    print(
        f"{'Layers':>6} | {'Gap%':>6} | {'A2A acc':>8} | {'TF acc':>8} | {'A2A tr(s)':>9} | {'TF tr(s)':>8} | {'A2A inf(ms)':>11} | {'TF inf(ms)':>10}",
        flush=True,
    )
    print("-" * 110, flush=True)

    for r in all_results:
        print(
            (
                f"{r['layers']:>6} | {r['param_gap_pct']:>6.2f} | "
                f"{r['all_to_all']['accuracy']*100:>7.2f}% | {r['transformer']['accuracy']*100:>7.2f}% | "
                f"{r['all_to_all']['train_time_s']:>9.2f} | {r['transformer']['train_time_s']:>8.2f} | "
                f"{r['all_to_all']['infer_ms']:>11.3f} | {r['transformer']['infer_ms']:>10.3f}"
            ),
            flush=True,
        )

    out_dir = Path(__file__).parent.parent / "outputs" / "metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "benchmark_fair_alltoall_vs_transformer_layers.json"
    out_file.write_text(json.dumps(all_results, indent=2))

    print("\nResultado guardado em:", out_file, flush=True)


if __name__ == "__main__":
    main()
