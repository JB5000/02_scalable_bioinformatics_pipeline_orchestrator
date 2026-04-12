"""Prompt evolution helpers for worker specialization."""

from __future__ import annotations

from .models import Challenge, PromptVariant


PROMPT_TEMPLATES: dict[str, str] = {
    "direct": (
        "You are a high-throughput worker. Solve the task quickly and return only the final answer. "
        "Avoid explanations."
    ),
    "deliberate": (
        "You are a careful reasoning worker. Verify intermediate transformations mentally and then return only the final answer."
    ),
    "verifier": (
        "You are a verification-first worker. Recompute the answer twice using two mental passes, then return only the final answer."
    ),
    "skeptic": (
        "You are an adversarial worker. Assume the first intuition is wrong, stress-test edge cases, then return only the final answer."
    ),
    "minimalist": (
        "You are a compact worker optimized for low token usage. Think briefly, then return only the final answer."
    ),
    "structured": (
        "You are a structured worker. Normalize the input format internally, apply a deterministic procedure, then return only the final answer."
    ),
    "consensus_seed": (
        "You are a consensus-seeding worker. Favor stable, canonical formatting so other workers can agree, then return only the final answer."
    ),
    "debugger": (
        "You are a debugging worker. Look for off-by-one, ordering, or sign mistakes before returning only the final answer."
    ),
}


FAMILY_MODE_PRIORITY: dict[str, list[str]] = {
    "arithmetic": ["verifier", "skeptic", "deliberate", "debugger", "direct", "minimalist"],
    "word_sort": ["structured", "consensus_seed", "verifier", "direct", "minimalist", "skeptic"],
    "count_char": ["structured", "verifier", "debugger", "deliberate", "minimalist", "direct"],
    "compare_sums": ["verifier", "debugger", "skeptic", "structured", "direct", "minimalist"],
}


def build_prompt_variants(
    *,
    challenge: Challenge,
    worker_count: int,
    learned_hints: list[str],
) -> list[PromptVariant]:
    """Create worker system prompts with lightweight prompt evolution."""
    preferred_modes = FAMILY_MODE_PRIORITY.get(challenge.family, list(PROMPT_TEMPLATES))
    hints_block = ""
    if learned_hints:
        hint_lines = "\n".join(f"- {hint}" for hint in learned_hints[:3])
        hints_block = (
            "\nRecent manager notes to incorporate when relevant:\n"
            f"{hint_lines}\n"
            "Use the notes only if they help this task."
        )

    variants: list[PromptVariant] = []
    for index in range(worker_count):
        mode = preferred_modes[index % len(preferred_modes)]
        base_prompt = PROMPT_TEMPLATES[mode]
        evolved_prompt = (
            f"{base_prompt}\n"
            f"Task family: {challenge.family}.\n"
            f"Difficulty: {challenge.difficulty}."
            f"{hints_block}"
        )
        variants.append(PromptVariant(mode=mode, system_prompt=evolved_prompt))
    return variants
