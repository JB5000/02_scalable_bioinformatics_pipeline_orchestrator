"""Utility helpers for normalization, hashing, and timestamps."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return a stable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def normalize_answer(text: str) -> str:
    """Normalize textual answers to improve exact-match scoring."""
    cleaned = text.strip().lower()
    cleaned = cleaned.replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,:;!?'\"")
    return cleaned


def stable_fraction(*parts: str) -> float:
    """Map arbitrary strings to a stable float in [0, 1)."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    value = int(digest[:16], 16)
    return value / float(16**16)


def estimate_token_count(*texts: str) -> int:
    """Approximate token counts without external tokenizers."""
    joined = " ".join(texts)
    rough = max(1, len(joined) // 4)
    return rough
