"""Tests for adversary generation and scoring."""

from __future__ import annotations

import unittest

from e_amas.adversary import ProgressiveAdversary


class ProgressiveAdversaryTests(unittest.TestCase):
    """Exercise adversary challenge generation and evaluation."""

    def test_progressive_adversary_increases_difficulty(self) -> None:
        adversary = ProgressiveAdversary(seed=11, start_difficulty=1, max_difficulty=4)
        challenges = [adversary.next_challenge() for _ in range(6)]

        difficulties = [challenge.difficulty for challenge in challenges]
        self.assertEqual(difficulties, [1, 1, 2, 2, 3, 3])
        self.assertTrue(challenges[0].ground_truth)
        self.assertTrue(challenges[-1].challenge_id.startswith("round-5-"))

    def test_adversary_scores_exact_answer_highest(self) -> None:
        adversary = ProgressiveAdversary(seed=3)
        challenge = adversary.next_challenge()

        exact = adversary.evaluate(challenge, challenge.ground_truth)
        wrong = adversary.evaluate(challenge, "definitely-wrong")

        self.assertEqual(exact, 1.0)
        self.assertLessEqual(wrong, exact)


if __name__ == "__main__":
    unittest.main()
