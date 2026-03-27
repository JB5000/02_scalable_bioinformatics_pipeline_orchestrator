"""Persistence layer for self-evolving behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


DEFAULT_POLICY = """# Solver Policy\n\n- Prefer small, verifiable steps.\n- Run code/tests after changing files when possible.\n- Explain actions clearly to the user before executing major changes.\n- Avoid destructive shell commands.\n"""


@dataclass
class SolverMemoryStore:
    """Store lessons and strategy updates across runs."""

    base_dir: Path

    @property
    def policy_path(self) -> Path:
        return self.base_dir / "policy.md"

    @property
    def episodes_path(self) -> Path:
        return self.base_dir / "episodes.jsonl"

    def ensure(self) -> None:
        """Create required files if they do not exist yet."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.policy_path.exists():
            self.policy_path.write_text(DEFAULT_POLICY, encoding="utf-8")
        if not self.episodes_path.exists():
            self.episodes_path.write_text("", encoding="utf-8")

    def load_policy(self) -> str:
        """Load current policy text."""
        self.ensure()
        return self.policy_path.read_text(encoding="utf-8")

    def append_episode(self, episode: Dict[str, str]) -> None:
        """Append episode to jsonl log."""
        self.ensure()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **episode,
        }
        with self.episodes_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def load_recent_episodes(self, limit: int = 6) -> List[Dict[str, str]]:
        """Return a few recent episodes to guide new tasks."""
        self.ensure()
        rows = self.episodes_path.read_text(encoding="utf-8").splitlines()
        data: List[Dict[str, str]] = []
        for row in rows[-limit:]:
            row = row.strip()
            if not row:
                continue
            try:
                parsed = json.loads(row)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                data.append(parsed)
        return data

    def append_policy_notes(self, notes: str) -> None:
        """Append concise strategy notes produced after a run."""
        self.ensure()
        if not notes.strip():
            return
        current = self.policy_path.read_text(encoding="utf-8")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        updated = (
            current.rstrip()
            + "\n\n"
            + f"## Learned {stamp}\n"
            + notes.strip()
            + "\n"
        )
        self.policy_path.write_text(updated, encoding="utf-8")
