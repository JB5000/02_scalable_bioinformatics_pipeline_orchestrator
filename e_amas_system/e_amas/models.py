"""Shared data models for the E-AMAS runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Challenge:
    """Adversarial challenge with a known ground truth."""

    challenge_id: str
    round_index: int
    family: str
    difficulty: int
    prompt: str
    ground_truth: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PromptVariant:
    """One worker prompt specialization."""

    mode: str
    system_prompt: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class BatchConfiguration:
    """Manager-selected configuration for a batch."""

    team_name: str
    worker_count: int
    temperature: float
    max_tokens: int
    prompt_variants: list[PromptVariant]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_name": self.team_name,
            "worker_count": self.worker_count,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "prompt_variants": [variant.to_dict() for variant in self.prompt_variants],
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class WorkerTask:
    """A single worker prompt invocation."""

    worker_id: str
    team_name: str
    reasoning_mode: str
    system_prompt: str
    user_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkerResponse:
    """Observed output and cost from one worker."""

    worker_id: str
    team_name: str
    reasoning_mode: str
    system_prompt: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "team_name": self.team_name,
            "reasoning_mode": self.reasoning_mode,
            "system_prompt": self.system_prompt,
            "content": self.content,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_seconds": self.latency_seconds,
            "error": self.error,
        }


@dataclass(slots=True)
class CandidateEvaluation:
    """Manager's critique for one worker output."""

    worker_id: str
    reasoning_mode: str
    answer: str
    normalized_answer: str
    score: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BatchExecution:
    """Raw execution result from the swarm."""

    started_at: str
    duration_seconds: float
    responses: list[WorkerResponse]


@dataclass(slots=True)
class EpisodeResult:
    """Manager-selected outcome for a full challenge."""

    team_name: str
    challenge_id: str
    family: str
    difficulty: int
    selected_answer: str
    selected_worker_id: str
    selected_mode: str
    quality: float
    duration_seconds: float
    total_tokens: int
    efficiency: float
    batch_configuration: BatchConfiguration
    evaluations: list[CandidateEvaluation]
    responses: list[WorkerResponse]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_name": self.team_name,
            "challenge_id": self.challenge_id,
            "family": self.family,
            "difficulty": self.difficulty,
            "selected_answer": self.selected_answer,
            "selected_worker_id": self.selected_worker_id,
            "selected_mode": self.selected_mode,
            "quality": self.quality,
            "duration_seconds": self.duration_seconds,
            "total_tokens": self.total_tokens,
            "efficiency": self.efficiency,
            "batch_configuration": self.batch_configuration.to_dict(),
            "evaluations": [evaluation.to_dict() for evaluation in self.evaluations],
            "responses": [response.to_dict() for response in self.responses],
        }
