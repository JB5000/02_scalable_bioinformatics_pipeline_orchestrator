#!/usr/bin/env python3
"""Basic repository health check utility."""

from __future__ import annotations

from pathlib import Path
import json


def evaluate_repo(root: Path) -> dict:
    expected = ["README.md", "src", "tests", "configs", "docs"]
    present = {}
    for item in expected:
        target = root / item
        present[item] = target.exists()

    missing = [item for item, ok in present.items() if not ok]
    score = int(((len(expected) - len(missing)) / len(expected)) * 100)

    return {
        "repository": root.name,
        "score": score,
        "present": present,
        "missing": missing,
        "status": "healthy" if score >= 80 else "needs_attention",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = evaluate_repo(root)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
