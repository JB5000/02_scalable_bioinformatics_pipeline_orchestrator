"""Progressive adversary that emits challenges with known ground truth."""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field

from .models import Challenge
from .utils import normalize_answer


WORD_BANK = [
    "kiwi",
    "argon",
    "delta",
    "ember",
    "fjord",
    "glyph",
    "hazel",
    "ivory",
    "jungle",
    "lilac",
    "meteor",
    "nylon",
]


@dataclass(slots=True)
class ProgressiveAdversary:
    """Generate progressively harder deterministic reasoning tasks."""

    seed: int = 7
    start_difficulty: int = 1
    max_difficulty: int = 6
    round_index: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def next_challenge(self) -> Challenge:
        """Create the next challenge and advance difficulty gradually."""
        families = ["arithmetic", "word_sort", "count_char", "compare_sums"]
        family = families[self.round_index % len(families)]
        difficulty = min(self.max_difficulty, self.start_difficulty + (self.round_index // 2))
        current_round = self.round_index
        self.round_index += 1

        if family == "arithmetic":
            return self._arithmetic(current_round, difficulty)
        if family == "word_sort":
            return self._word_sort(current_round, difficulty)
        if family == "count_char":
            return self._count_char(current_round, difficulty)
        return self._compare_sums(current_round, difficulty)

    def evaluate(self, challenge: Challenge, answer: str) -> float:
        """Score one answer against the challenge ground truth."""
        expected = normalize_answer(challenge.ground_truth)
        candidate = normalize_answer(answer)
        if not candidate:
            return 0.0
        if candidate == expected:
            return 1.0

        if challenge.family in {"arithmetic", "count_char"}:
            if expected.lstrip("-").isdigit() and candidate.lstrip("-").isdigit():
                delta = abs(int(expected) - int(candidate))
                return max(0.0, 1.0 - (delta / max(challenge.difficulty * 4, 1)))
            return 0.0

        if challenge.family == "word_sort":
            expected_items = [item.strip() for item in expected.split(",") if item.strip()]
            candidate_items = [item.strip() for item in candidate.split(",") if item.strip()]
            if not expected_items or not candidate_items:
                return 0.0
            matches = sum(
                1
                for left, right in zip(expected_items, candidate_items)
                if left == right
            )
            return matches / len(expected_items)

        if challenge.family == "compare_sums":
            return 0.6 if candidate == expected.replace("team ", "") else 0.0
        return 0.0

    def _arithmetic(self, round_index: int, difficulty: int) -> Challenge:
        count = difficulty + 2
        numbers = [self._rng.randint(2, 9) for _ in range(count)]
        operations = [self._rng.choice(["+", "-", "*"]) for _ in range(count - 1)]

        expression = str(numbers[0])
        total = numbers[0]
        for operator, value in zip(operations, numbers[1:]):
            expression += f" {operator} {value}"
            if operator == "+":
                total += value
            elif operator == "-":
                total -= value
            else:
                total *= value

        prompt = (
            "Compute the following expression strictly left-to-right and return only the final integer:\n"
            f"{expression}"
        )
        return Challenge(
            challenge_id=f"round-{round_index}-arithmetic-d{difficulty}",
            round_index=round_index,
            family="arithmetic",
            difficulty=difficulty,
            prompt=prompt,
            ground_truth=str(total),
            metadata={"expression": expression},
        )

    def _word_sort(self, round_index: int, difficulty: int) -> Challenge:
        words = self._rng.sample(WORD_BANK, k=min(len(WORD_BANK), difficulty + 3))
        prompt = (
            "Sort the following words alphabetically and return them as a comma-separated list with no extra text:\n"
            + ", ".join(words)
        )
        ground_truth = ", ".join(sorted(word.lower() for word in words))
        return Challenge(
            challenge_id=f"round-{round_index}-word-sort-d{difficulty}",
            round_index=round_index,
            family="word_sort",
            difficulty=difficulty,
            prompt=prompt,
            ground_truth=ground_truth,
            metadata={"words": words},
        )

    def _count_char(self, round_index: int, difficulty: int) -> Challenge:
        target = self._rng.choice(string.ascii_lowercase[:8])
        length = 12 + (difficulty * 4)
        chars = [self._rng.choice(string.ascii_lowercase[:8]) for _ in range(length)]
        text = "".join(chars)
        ground_truth = str(text.count(target))
        prompt = (
            "Count how many times the character appears in the string. Return only the integer.\n"
            f"character: {target}\n"
            f"string: {text}"
        )
        return Challenge(
            challenge_id=f"round-{round_index}-count-char-d{difficulty}",
            round_index=round_index,
            family="count_char",
            difficulty=difficulty,
            prompt=prompt,
            ground_truth=ground_truth,
            metadata={"target": target, "text": text},
        )

    def _compare_sums(self, round_index: int, difficulty: int) -> Challenge:
        left = [self._rng.randint(1, 9) for _ in range(difficulty + 2)]
        right = [self._rng.randint(1, 9) for _ in range(difficulty + 2)]
        left_sum = sum(left)
        right_sum = sum(right)
        if left_sum > right_sum:
            winner = "team left"
        elif right_sum > left_sum:
            winner = "team right"
        else:
            winner = "tie"
        prompt = (
            "Compare the sums of two teams and return only one of: team left, team right, tie.\n"
            f"team left: {left}\n"
            f"team right: {right}"
        )
        return Challenge(
            challenge_id=f"round-{round_index}-compare-sums-d{difficulty}",
            round_index=round_index,
            family="compare_sums",
            difficulty=difficulty,
            prompt=prompt,
            ground_truth=winner,
            metadata={"left": left, "right": right},
        )
