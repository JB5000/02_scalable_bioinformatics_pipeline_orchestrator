"""Core self-evolving solver loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.solver.deepinfra_client import DeepInfraChatClient
from src.solver.memory_store import SolverMemoryStore
from src.solver.tools import LocalToolExecutor


SYSTEM_PROMPT = """You are a coding problem solver with tool access.

Return ONLY valid JSON with this schema:
{
  "action": "message" | "read_file" | "write_file" | "run_shell" | "run_python" | "finish",
  "message": "string for user updates",
  "params": { ... action parameters ... }
}

Rules:
- Work in small steps and verify changes with code execution where useful.
- Prefer read_file before editing unknown files.
- Keep shell commands non-destructive.
- Use concise communication.
- When the task is solved, return action=finish with final explanation in message.
"""

REFLECTION_PROMPT = """You are improving a coding agent policy.
Given a completed episode, output 3-6 short markdown bullets under this title exactly:
## New Heuristics
Do not output anything else.
"""


@dataclass
class SelfEvolvingSolver:
    """Agent that can solve coding tasks and improve strategy notes."""

    client: DeepInfraChatClient
    tools: LocalToolExecutor
    memory: SolverMemoryStore
    max_steps: int = 14

    def _extract_json(self, text: str) -> Dict[str, object]:
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                if candidate.startswith("{") and candidate.endswith("}"):
                    return json.loads(candidate)
        if text.startswith("{") and text.endswith("}"):
            return json.loads(text)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("No JSON object found in model response")

    def solve(
        self,
        user_task: str,
        on_update: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Solve one user task with tool-augmented iterative reasoning."""
        self.memory.ensure()
        policy = self.memory.load_policy()
        recent = self.memory.load_recent_episodes(limit=5)
        recent_text = json.dumps(recent, ensure_ascii=True)

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Current strategy policy:\n" + policy,
            },
            {
                "role": "system",
                "content": "Recent episodes:\n" + recent_text,
            },
            {"role": "user", "content": user_task},
        ]

        final_answer = ""
        trace: List[Dict[str, object]] = []

        for step in range(1, self.max_steps + 1):
            raw = self.client.chat(messages=messages)

            try:
                decision = self._extract_json(raw)
            except Exception as exc:  # pragma: no cover - defensive branch
                feedback = f"Invalid JSON response: {exc}. Return JSON only."
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": feedback})
                continue

            action = str(decision.get("action", "")).strip()
            message = str(decision.get("message", "")).strip()
            params = decision.get("params", {})
            if not isinstance(params, dict):
                params = {}

            if on_update and message:
                on_update(f"[step {step}] {message}")

            if action == "finish":
                final_answer = message or "Task finished."
                trace.append({"action": action, "message": final_answer})
                break

            if action == "message":
                trace.append({"action": action, "message": message})
                messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=True)})
                messages.append(
                    {
                        "role": "user",
                        "content": "Acknowledged. Continue with a concrete next action.",
                    }
                )
                continue

            result = self.tools.execute(action=action, params=params)
            trace.append({"action": action, "params": params, "result": result})

            tool_feedback = {
                "tool_action": action,
                "tool_result": result,
            }
            messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=True)})
            messages.append(
                {
                    "role": "user",
                    "content": "TOOL_RESULT:\n" + json.dumps(tool_feedback, ensure_ascii=True),
                }
            )

        if not final_answer:
            final_answer = "Max steps reached before explicit finish."

        self._reflect_and_evolve(user_task=user_task, final_answer=final_answer, trace=trace)
        return final_answer

    def _reflect_and_evolve(
        self,
        user_task: str,
        final_answer: str,
        trace: List[Dict[str, object]],
    ) -> None:
        """Persist episode and append compact policy notes from model reflection."""
        compact_trace = json.dumps(trace[-8:], ensure_ascii=True)
        self.memory.append_episode(
            {
                "task": user_task[:1200],
                "final_answer": final_answer[:2000],
                "trace": compact_trace[:7000],
            }
        )

        reflection_messages = [
            {"role": "system", "content": REFLECTION_PROMPT},
            {
                "role": "user",
                "content": (
                    "Task:\n"
                    + user_task[:1500]
                    + "\n\nFinal answer:\n"
                    + final_answer[:1500]
                    + "\n\nTrace (recent):\n"
                    + compact_trace[:5000]
                ),
            },
        ]

        try:
            notes = self.client.chat(messages=reflection_messages, temperature=0.1, max_tokens=300)
        except Exception:
            return

        if "## New Heuristics" not in notes:
            return
        self.memory.append_policy_notes(notes)
