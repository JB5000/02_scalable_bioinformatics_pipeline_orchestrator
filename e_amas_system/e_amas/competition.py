"""Competitive training loop for two E-AMAS teams."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adversary import ProgressiveAdversary
from .manager import BatchManager
from .utils import utc_now_iso


@dataclass(slots=True)
class CompetitionTrainer:
    """Run team-vs-team competitive training and transfer learnings."""

    team_a: BatchManager
    team_b: BatchManager
    adversary: ProgressiveAdversary
    summary_path: Path

    async def run(self, rounds: int) -> dict[str, Any]:
        """Run multiple competitive rounds and persist a summary JSON file."""
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        wins = {self.team_a.config.team_name: 0, self.team_b.config.team_name: 0}
        for _ in range(rounds):
            challenge = self.adversary.next_challenge()
            result_a, result_b = await self._play_both(challenge)
            winner, loser = self._pick_winner(result_a, result_b)
            wins[winner.team_name] += 1
            self._share_lesson(winner, loser, challenge.challenge_id)
            records.append(
                {
                    "timestamp": utc_now_iso(),
                    "challenge_id": challenge.challenge_id,
                    "family": challenge.family,
                    "difficulty": challenge.difficulty,
                    "winner": winner.team_name,
                    "loser": loser.team_name,
                    "winner_quality": winner.quality,
                    "loser_quality": loser.quality,
                    "winner_efficiency": winner.efficiency,
                    "loser_efficiency": loser.efficiency,
                }
            )

        summary = {
            "generated_at": utc_now_iso(),
            "rounds": rounds,
            "wins": wins,
            "records": records,
        }
        self.summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    async def _play_both(self, challenge: Any) -> tuple[Any, Any]:
        import asyncio

        return await asyncio.gather(
            self.team_a.run_episode(challenge),
            self.team_b.run_episode(challenge),
        )

    def _pick_winner(self, result_a: Any, result_b: Any) -> tuple[Any, Any]:
        if result_a.quality != result_b.quality:
            return (result_a, result_b) if result_a.quality > result_b.quality else (result_b, result_a)
        if result_a.efficiency != result_b.efficiency:
            return (result_a, result_b) if result_a.efficiency > result_b.efficiency else (result_b, result_a)
        if result_a.duration_seconds != result_b.duration_seconds:
            return (result_a, result_b) if result_a.duration_seconds < result_b.duration_seconds else (result_b, result_a)
        return (result_a, result_b) if result_a.total_tokens <= result_b.total_tokens else (result_b, result_a)

    def _share_lesson(self, winner: Any, loser: Any, challenge_id: str) -> None:
        lesson = (
            f"Competition winner {winner.team_name} used batch {winner.batch_configuration.worker_count} "
            f"and mode {winner.selected_mode} with efficiency {winner.efficiency:.6f}."
        )
        loser_manager = self.team_a if loser.team_name == self.team_a.config.team_name else self.team_b
        winner_manager = self.team_a if winner.team_name == self.team_a.config.team_name else self.team_b

        winner_manager.ledger.append_note(
            lesson,
            team_name=winner.team_name,
            challenge_id=challenge_id,
            family=winner.family,
            difficulty=winner.difficulty,
            signals={
                "competition": "winner",
                "worker_count": winner.batch_configuration.worker_count,
                "selected_mode": winner.selected_mode,
            },
        )
        loser_manager.ledger.append_note(
            f"Adopt lesson from {winner.team_name}: {lesson}",
            team_name=loser.team_name,
            challenge_id=challenge_id,
            family=loser.family,
            difficulty=loser.difficulty,
            signals={
                "competition": "loser_adapting",
                "recommended_worker_count": winner.batch_configuration.worker_count,
                "recommended_mode": winner.selected_mode,
            },
        )
