#!/usr/bin/env python3
"""Interactive self-evolving coding solver powered by DeepInfra."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from src.solver.agent import SelfEvolvingSolver
from src.solver.deepinfra_client import DeepInfraChatClient
from src.solver.memory_store import SolverMemoryStore
from src.solver.tools import LocalToolExecutor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Self-evolving coding solver")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--model", default="gpt-oss-120b", help="DeepInfra model name")
    parser.add_argument("--max-steps", type=int, default=14, help="Max tool-reasoning steps per user request")
    parser.add_argument("--state-dir", default=".solver_state", help="Persistent memory directory")
    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    api_key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not api_key:
        print("Missing DEEPINFRA_API_KEY in environment.")
        print("Example: export DEEPINFRA_API_KEY='your_key'")
        return 1

    base_url = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")

    workspace = Path(args.workspace).resolve()
    memory = SolverMemoryStore(base_dir=(workspace / args.state_dir))
    tools = LocalToolExecutor(workspace=workspace)
    client = DeepInfraChatClient(
        api_key=api_key,
        model=args.model,
        base_url=base_url,
    )
    solver = SelfEvolvingSolver(
        client=client,
        tools=tools,
        memory=memory,
        max_steps=args.max_steps,
    )

    print("Self-evolving solver ready.")
    print("Type your coding problem. Type 'exit' to quit.")

    while True:
        try:
            task = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not task:
            continue
        if task.lower() in {"exit", "quit"}:
            print("Exiting.")
            break

        def on_update(update: str) -> None:
            print(f"Solver> {update}")

        try:
            result = solver.solve(task, on_update=on_update)
            print("Solver> Final:")
            print(result)
        except Exception as exc:
            print(f"Solver> Error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
