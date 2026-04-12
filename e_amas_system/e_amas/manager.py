"""Manager/orchestrator for batch planning, critique, and learning."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .adversary import ProgressiveAdversary
from .ledger import KnowledgeLedger
from .metrics import BatchMetricsLogger, compute_efficiency
from .models import BatchConfiguration, CandidateEvaluation, Challenge, EpisodeResult
from .prompts import build_prompt_variants
from .swarm import WorkerSwarm
from .utils import normalize_answer


@dataclass(slots=True)
class ManagerConfig:
    """Manager policy knobs."""

    team_name: str
    model: str = "mock-model"
    base_worker_count: int = 4
    min_worker_count: int = 2
    max_worker_count: int = 10
    temperature: float = 0.35
    max_tokens: int = 128
    note_limit: int = 4
    slow_batch_seconds: float = 0.35


class BatchManager:
    """Plan, execute, critique, and learn from batch episodes."""

    def __init__(
        self,
        *,
        config: ManagerConfig,
        swarm: WorkerSwarm,
        adversary: ProgressiveAdversary,
        ledger: KnowledgeLedger,
        metrics_logger: BatchMetricsLogger,
    ) -> None:
        self.config = config
        self.swarm = swarm
        self.adversary = adversary
        self.ledger = ledger
        self.metrics_logger = metrics_logger

    async def run_episode(self, challenge: Challenge) -> EpisodeResult:
        """Execute one full manager-worker episode."""
        batch_config = self.plan_batch(challenge)
        execution = await self.swarm.run_batch(
            challenge=challenge,
            configuration=batch_config,
        )
        evaluations = self._evaluate_candidates(challenge, execution.responses)
        selected = self._select_consensus(evaluations, execution.responses)
        total_tokens = sum(response.total_tokens for response in execution.responses)
        efficiency = compute_efficiency(selected["score"], total_tokens, execution.duration_seconds)
        result = EpisodeResult(
            team_name=self.config.team_name,
            challenge_id=challenge.challenge_id,
            family=challenge.family,
            difficulty=challenge.difficulty,
            selected_answer=selected["response"].content,
            selected_worker_id=selected["response"].worker_id,
            selected_mode=selected["response"].reasoning_mode,
            quality=selected["score"],
            duration_seconds=execution.duration_seconds,
            total_tokens=total_tokens,
            efficiency=efficiency,
            batch_configuration=batch_config,
            evaluations=evaluations,
            responses=execution.responses,
        )
        self._persist_episode(result)
        self._write_post_mortem(challenge, result)
        self.metrics_logger.log_episode(result)
        return result

    def plan_batch(self, challenge: Challenge) -> BatchConfiguration:
        """Consult the ledger and produce a new batch configuration."""
        learned_hints = self.ledger.learned_hints(
            family=challenge.family,
            limit=self.config.note_limit,
        )
        recent_family_episodes = self.ledger.recent_episodes(
            limit=20,
            family=challenge.family,
            team_name=self.config.team_name,
        )
        preferred_worker_count = self.ledger.preferred_worker_count(family=challenge.family)
        worker_count = self.config.base_worker_count + max(challenge.difficulty - 1, 0)
        if preferred_worker_count is not None:
            worker_count = preferred_worker_count
        if recent_family_episodes:
            average_quality = sum(float(item.get("quality", 0.0)) for item in recent_family_episodes) / len(recent_family_episodes)
            if average_quality < 0.75:
                worker_count += 1
            if any(float(item.get("duration_seconds", 0.0)) > self.config.slow_batch_seconds for item in recent_family_episodes[-3:]):
                worker_count -= 1

        worker_count = max(self.config.min_worker_count, min(self.config.max_worker_count, worker_count))
        prompt_variants = build_prompt_variants(
            challenge=challenge,
            worker_count=worker_count,
            learned_hints=learned_hints,
        )
        rationale = (
            f"team={self.config.team_name}; family={challenge.family}; "
            f"difficulty={challenge.difficulty}; learned_hints={len(learned_hints)}; "
            f"preferred_worker_count={preferred_worker_count}"
        )
        return BatchConfiguration(
            team_name=self.config.team_name,
            worker_count=worker_count,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            prompt_variants=prompt_variants,
            rationale=rationale,
        )

    def _evaluate_candidates(self, challenge: Challenge, responses: list[Any]) -> list[CandidateEvaluation]:
        evaluations: list[CandidateEvaluation] = []
        for response in responses:
            score = 0.0 if response.error else self.adversary.evaluate(challenge, response.content)
            evaluations.append(
                CandidateEvaluation(
                    worker_id=response.worker_id,
                    reasoning_mode=response.reasoning_mode,
                    answer=response.content,
                    normalized_answer=normalize_answer(response.content),
                    score=score,
                    error=response.error,
                )
            )
        return evaluations

    def _select_consensus(
        self,
        evaluations: list[CandidateEvaluation],
        responses: list[Any],
    ) -> dict[str, Any]:
        by_worker = {response.worker_id: response for response in responses}
        counts = Counter(
            evaluation.normalized_answer
            for evaluation in evaluations
            if evaluation.normalized_answer
        )
        enriched: list[dict[str, Any]] = []
        for evaluation in evaluations:
            response = by_worker[evaluation.worker_id]
            enriched.append(
                {
                    "evaluation": evaluation,
                    "response": response,
                    "score": evaluation.score,
                    "consensus_count": counts.get(evaluation.normalized_answer, 0),
                }
            )
        return max(
            enriched,
            key=lambda item: (
                item["score"],
                item["consensus_count"],
                -item["response"].latency_seconds,
                -item["response"].total_tokens,
            ),
        )

    def _persist_episode(self, result: EpisodeResult) -> None:
        self.ledger.append_episode(
            {
                "team_name": result.team_name,
                "challenge_id": result.challenge_id,
                "family": result.family,
                "difficulty": result.difficulty,
                "quality": result.quality,
                "duration_seconds": result.duration_seconds,
                "total_tokens": result.total_tokens,
                "efficiency": result.efficiency,
                "selected_mode": result.selected_mode,
                "worker_count": result.batch_configuration.worker_count,
                "selected_answer": result.selected_answer,
                "rationale": result.batch_configuration.rationale,
            }
        )

    def _write_post_mortem(self, challenge: Challenge, result: EpisodeResult) -> None:
        if result.quality >= 1.0:
            self.ledger.append_note(
                (
                    f"Mode {result.selected_mode} solved {challenge.family} at difficulty "
                    f"{challenge.difficulty} with batch {result.batch_configuration.worker_count}."
                ),
                team_name=self.config.team_name,
                challenge_id=challenge.challenge_id,
                family=challenge.family,
                difficulty=challenge.difficulty,
                signals={
                    "worker_count": result.batch_configuration.worker_count,
                    "selected_mode": result.selected_mode,
                    "efficiency": result.efficiency,
                },
            )
        else:
            self.ledger.append_note(
                (
                    f"Batch {result.batch_configuration.worker_count} underperformed on {challenge.family} "
                    f"difficulty {challenge.difficulty}; increase verifier coverage or worker count."
                ),
                team_name=self.config.team_name,
                challenge_id=challenge.challenge_id,
                family=challenge.family,
                difficulty=challenge.difficulty,
                signals={
                    "worker_count": result.batch_configuration.worker_count,
                    "quality": result.quality,
                },
            )

        if result.duration_seconds > self.config.slow_batch_seconds:
            recommended = max(self.config.min_worker_count, result.batch_configuration.worker_count - 1)
            self.ledger.append_note(
                (
                    f"Batch {result.batch_configuration.worker_count} was slow for {challenge.family}; "
                    f"prefer {recommended} workers when difficulty is similar."
                ),
                team_name=self.config.team_name,
                challenge_id=challenge.challenge_id,
                family=challenge.family,
                difficulty=challenge.difficulty,
                signals={
                    "recommended_worker_count": recommended,
                    "duration_seconds": result.duration_seconds,
                },
            )
