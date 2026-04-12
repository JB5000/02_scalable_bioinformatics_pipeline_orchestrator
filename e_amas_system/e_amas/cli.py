"""Command-line interface for E-AMAS experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from .adversary import ProgressiveAdversary
from .backends import MockLLMBackend, OpenAICompatibleAsyncBackend
from .competition import CompetitionTrainer
from .ledger import KnowledgeLedger
from .manager import BatchManager, ManagerConfig
from .metrics import BatchMetricsLogger
from .swarm import WorkerSwarm


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description="E-AMAS manager-workers orchestrator")
    parser.add_argument("--project-root", default=".", help="Path to e_amas_system project root")
    parser.add_argument("--backend", choices=["mock", "openai"], default="mock", help="Execution backend")
    parser.add_argument("--model", default="mock-model", help="Model name to request from the backend")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1", help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default="", help="Optional API key for the backend")
    parser.add_argument("--seed", type=int, default=7, help="Adversary seed")

    subparsers = parser.add_subparsers(dest="command", required=True)

    episode = subparsers.add_parser("run-episode", help="Run one adversarial episode")
    episode.add_argument("--team-name", default="TeamA", help="Manager/team name")
    episode.add_argument("--workers", type=int, default=4, help="Base worker count")
    episode.add_argument("--max-workers", type=int, default=10, help="Maximum workers")

    competition = subparsers.add_parser("train-competition", help="Run team-vs-team training")
    competition.add_argument("--rounds", type=int, default=6, help="Number of competition rounds")
    competition.add_argument("--team-a-workers", type=int, default=4, help="Base workers for team A")
    competition.add_argument("--team-b-workers", type=int, default=5, help="Base workers for team B")
    competition.add_argument("--team-a-name", default="TeamA", help="Name for team A")
    competition.add_argument("--team-b-name", default="TeamB", help="Name for team B")

    return parser


def main() -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    logger = configure_logging(project_root)
    logger.info("Starting E-AMAS command=%s backend=%s", args.command, args.backend)

    if args.command == "run-episode":
        payload = asyncio.run(run_episode(args, project_root, logger))
    else:
        payload = asyncio.run(run_competition(args, project_root, logger))

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


async def run_episode(args: argparse.Namespace, project_root: Path, logger: logging.Logger) -> dict:
    """Run a single manager-worker episode."""
    backend = build_backend(args)
    adversary = ProgressiveAdversary(seed=args.seed)
    challenge = adversary.next_challenge()
    manager = build_manager(
        project_root=project_root,
        backend=backend,
        team_name=args.team_name,
        model=args.model,
        base_workers=args.workers,
        max_workers=args.max_workers,
        adversary=adversary,
    )
    result = await manager.run_episode(challenge)
    logger.info(
        "Episode complete team=%s challenge=%s quality=%.3f efficiency=%.6f",
        result.team_name,
        result.challenge_id,
        result.quality,
        result.efficiency,
    )
    return {
        "challenge": challenge.to_dict(),
        "result": result.to_dict(),
    }


async def run_competition(args: argparse.Namespace, project_root: Path, logger: logging.Logger) -> dict:
    """Run competitive training between team A and team B."""
    backend = build_backend(args)
    adversary = ProgressiveAdversary(seed=args.seed)
    manager_a = build_manager(
        project_root=project_root,
        backend=backend,
        team_name=args.team_a_name,
        model=args.model,
        base_workers=args.team_a_workers,
        max_workers=max(args.team_a_workers + 4, 6),
        adversary=adversary,
    )
    manager_b = build_manager(
        project_root=project_root,
        backend=backend,
        team_name=args.team_b_name,
        model=args.model,
        base_workers=args.team_b_workers,
        max_workers=max(args.team_b_workers + 4, 6),
        adversary=adversary,
    )
    trainer = CompetitionTrainer(
        team_a=manager_a,
        team_b=manager_b,
        adversary=adversary,
        summary_path=project_root / "runtime" / "competition_summary.json",
    )
    summary = await trainer.run(args.rounds)
    logger.info("Competition complete rounds=%s wins=%s", args.rounds, summary.get("wins"))
    return summary


def build_manager(
    *,
    project_root: Path,
    backend: object,
    team_name: str,
    model: str,
    base_workers: int,
    max_workers: int,
    adversary: ProgressiveAdversary,
) -> BatchManager:
    """Construct a manager with isolated ledger and shared backend."""
    runtime_dir = project_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config = ManagerConfig(
        team_name=team_name,
        model=model,
        base_worker_count=base_workers,
        max_worker_count=max_workers,
    )
    swarm = WorkerSwarm(backend=backend, model=model)
    return BatchManager(
        config=config,
        swarm=swarm,
        adversary=adversary,
        ledger=KnowledgeLedger(runtime_dir / f"{team_name.lower()}_ledger.json"),
        metrics_logger=BatchMetricsLogger(runtime_dir / f"{team_name.lower()}_metrics.jsonl"),
    )


def build_backend(args: argparse.Namespace) -> object:
    """Create the selected backend implementation."""
    if args.backend == "mock":
        return MockLLMBackend()
    api_key = args.api_key.strip() or os.getenv("OPENAI_API_KEY", "").strip() or None
    return OpenAICompatibleAsyncBackend(
        base_url=args.base_url,
        api_key=api_key,
    )


def configure_logging(project_root: Path) -> logging.Logger:
    """Configure a file logger in the project root."""
    project_root.mkdir(parents=True, exist_ok=True)
    log_path = project_root / "e_amas.log"
    logger = logging.getLogger("e_amas")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
