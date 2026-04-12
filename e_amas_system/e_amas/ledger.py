"""JSON ledger for notes and episode history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import utc_now_iso


@dataclass(slots=True)
class KnowledgeLedger:
    """Persistent JSON knowledge base for post-mortems and episodes."""

    path: Path

    def _fresh_payload(self) -> dict[str, Any]:
        """Return a fresh empty ledger payload."""
        return {
            "version": 1,
            "notes": [],
            "episodes": [],
        }

    def ensure(self) -> None:
        """Create the ledger file when it is missing."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._fresh_payload())

    def load(self) -> dict[str, Any]:
        """Load current ledger state."""
        self.ensure()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fresh = self._fresh_payload()
            self._write(fresh)
            return fresh

    def append_note(
        self,
        text: str,
        *,
        team_name: str,
        challenge_id: str | None = None,
        family: str | None = None,
        difficulty: int | None = None,
        signals: dict[str, Any] | None = None,
    ) -> None:
        """Persist one short post-mortem note."""
        payload = self.load()
        payload["notes"].append(
            {
                "timestamp": utc_now_iso(),
                "team_name": team_name,
                "challenge_id": challenge_id,
                "family": family,
                "difficulty": difficulty,
                "text": text,
                "signals": signals or {},
            }
        )
        self._write(payload)

    def append_episode(self, episode: dict[str, Any]) -> None:
        """Persist one episode record."""
        payload = self.load()
        payload["episodes"].append(
            {
                "timestamp": utc_now_iso(),
                **episode,
            }
        )
        self._write(payload)

    def recent_notes(self, limit: int = 8, family: str | None = None) -> list[dict[str, Any]]:
        """Return recent notes, optionally filtered by family."""
        notes = self.load().get("notes", [])
        filtered = [
            note
            for note in notes
            if family is None or note.get("family") in {None, family}
        ]
        return filtered[-limit:]

    def recent_episodes(
        self,
        limit: int = 20,
        *,
        family: str | None = None,
        team_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent episodes with optional filters."""
        episodes = self.load().get("episodes", [])
        filtered = [
            episode
            for episode in episodes
            if (family is None or episode.get("family") == family)
            and (team_name is None or episode.get("team_name") == team_name)
        ]
        return filtered[-limit:]

    def learned_hints(self, *, family: str, limit: int = 4) -> list[str]:
        """Extract recent note strings to feed prompt evolution."""
        hints = []
        for note in reversed(self.recent_notes(limit=limit * 2, family=family)):
            text = str(note.get("text", "")).strip()
            if not text:
                continue
            hints.append(text)
            if len(hints) >= limit:
                break
        return list(reversed(hints))

    def preferred_worker_count(self, *, family: str) -> int | None:
        """Infer a historically efficient worker count for one challenge family."""
        episodes = self.recent_episodes(limit=40, family=family)
        if not episodes:
            return None
        scored = [
            episode
            for episode in episodes
            if float(episode.get("quality", 0.0)) > 0.5
            and int(episode.get("worker_count", 0)) > 0
        ]
        if not scored:
            return None
        best = max(
            scored,
            key=lambda episode: (
                float(episode.get("efficiency", 0.0)),
                float(episode.get("quality", 0.0)),
            ),
        )
        return int(best.get("worker_count", 0)) or None

    def _write(self, payload: dict[str, Any]) -> None:
        """Write the ledger atomically."""
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.path)
