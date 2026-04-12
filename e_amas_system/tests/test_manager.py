"""Tests for the manager learning loop."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from e_amas.adversary import ProgressiveAdversary
from e_amas.backends import MockLLMBackend
from e_amas.ledger import KnowledgeLedger
from e_amas.manager import BatchManager, ManagerConfig
from e_amas.metrics import BatchMetricsLogger
from e_amas.swarm import WorkerSwarm


class BatchManagerTests(unittest.TestCase):
    """Validate episode persistence and prompt evolution."""

    def test_manager_persists_episode_and_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            adversary = ProgressiveAdversary(seed=7)
            backend = MockLLMBackend()
            manager = BatchManager(
                config=ManagerConfig(team_name="TeamA", base_worker_count=3, max_worker_count=6),
                swarm=WorkerSwarm(backend=backend, model="mock-model"),
                adversary=adversary,
                ledger=KnowledgeLedger(base / "team_a_ledger.json"),
                metrics_logger=BatchMetricsLogger(base / "team_a_metrics.jsonl"),
            )
            challenge = adversary.next_challenge()

            result = asyncio.run(manager.run_episode(challenge))

            self.assertEqual(result.challenge_id, challenge.challenge_id)
            self.assertGreaterEqual(result.quality, 0.0)
            self.assertLessEqual(result.quality, 1.0)
            self.assertGreater(result.total_tokens, 0)
            self.assertTrue(manager.ledger.load()["episodes"])
            self.assertTrue(manager.ledger.load()["notes"])
            self.assertTrue(manager.metrics_logger.read_recent())

    def test_prompt_evolution_reads_existing_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            adversary = ProgressiveAdversary(seed=9)
            ledger = KnowledgeLedger(base / "team_b_ledger.json")
            ledger.append_note(
                "Verifier prompts were best on arithmetic at difficulty 2.",
                team_name="TeamB",
                family="arithmetic",
                difficulty=2,
            )
            manager = BatchManager(
                config=ManagerConfig(team_name="TeamB", base_worker_count=2, max_worker_count=5),
                swarm=WorkerSwarm(backend=MockLLMBackend(), model="mock-model"),
                adversary=adversary,
                ledger=ledger,
                metrics_logger=BatchMetricsLogger(base / "team_b_metrics.jsonl"),
            )
            challenge = adversary.next_challenge()

            batch = manager.plan_batch(challenge)

            self.assertTrue(batch.prompt_variants)
            self.assertTrue(
                any("Recent manager notes" in variant.system_prompt for variant in batch.prompt_variants)
            )


if __name__ == "__main__":
    unittest.main()
