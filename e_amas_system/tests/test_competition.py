"""Tests for competitive training."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from e_amas.adversary import ProgressiveAdversary
from e_amas.backends import MockLLMBackend
from e_amas.competition import CompetitionTrainer
from e_amas.ledger import KnowledgeLedger
from e_amas.manager import BatchManager, ManagerConfig
from e_amas.metrics import BatchMetricsLogger
from e_amas.swarm import WorkerSwarm


def build_manager(base: Path, team_name: str, base_workers: int, adversary: ProgressiveAdversary) -> BatchManager:
    """Create one manager for test competition."""
    return BatchManager(
        config=ManagerConfig(team_name=team_name, base_worker_count=base_workers, max_worker_count=8),
        swarm=WorkerSwarm(backend=MockLLMBackend(), model="mock-model"),
        adversary=adversary,
        ledger=KnowledgeLedger(base / f"{team_name.lower()}_ledger.json"),
        metrics_logger=BatchMetricsLogger(base / f"{team_name.lower()}_metrics.jsonl"),
    )


class CompetitionTrainerTests(unittest.TestCase):
    """Validate competitive training and lesson transfer."""

    def test_competition_runs_and_transfers_lessons(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            adversary = ProgressiveAdversary(seed=5)
            team_a = build_manager(base, "TeamA", 3, adversary)
            team_b = build_manager(base, "TeamB", 4, adversary)
            trainer = CompetitionTrainer(
                team_a=team_a,
                team_b=team_b,
                adversary=adversary,
                summary_path=base / "competition_summary.json",
            )

            summary = asyncio.run(trainer.run(rounds=4))

            self.assertEqual(summary["rounds"], 4)
            self.assertEqual(summary["wins"]["TeamA"] + summary["wins"]["TeamB"], 4)
            self.assertTrue(trainer.summary_path.exists())
            self.assertTrue(team_a.ledger.load()["notes"])
            self.assertTrue(team_b.ledger.load()["notes"])


if __name__ == "__main__":
    unittest.main()
