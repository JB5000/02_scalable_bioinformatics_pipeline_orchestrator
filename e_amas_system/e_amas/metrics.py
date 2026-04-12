"""Batch metric logging and efficiency helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import EpisodeResult
from .utils import utc_now_iso


def compute_efficiency(quality: float, total_tokens: int, duration_seconds: float) -> float:
    """Compute efficiency score E = quality / (tokens * time)."""
    denominator = max(float(total_tokens), 1.0) * max(duration_seconds, 1e-6)
    return quality / denominator


@dataclass(slots=True)
class BatchMetricsLogger:
    """Append-only JSONL metrics logger for batch runs."""

    path: Path

    def ensure(self) -> None:
        """Create the JSONL file if required."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def log_episode(self, result: EpisodeResult) -> None:
        """Persist a compact metrics row."""
        self.ensure()
        payload = {
            "timestamp": utc_now_iso(),
            "team_name": result.team_name,
            "challenge_id": result.challenge_id,
            "family": result.family,
            "difficulty": result.difficulty,
            "quality": result.quality,
            "duration_seconds": result.duration_seconds,
            "total_tokens": result.total_tokens,
            "efficiency": result.efficiency,
            "worker_count": result.batch_configuration.worker_count,
            "selected_mode": result.selected_mode,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_recent(self, limit: int = 30) -> list[dict[str, Any]]:
        """Load recent metric rows."""
        self.ensure()
        rows = self.path.read_text(encoding="utf-8").splitlines()
        parsed: list[dict[str, Any]] = []
        for row in rows[-limit:]:
            row = row.strip()
            if not row:
                continue
            try:
                item = json.loads(row)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                parsed.append(item)
        return parsed
