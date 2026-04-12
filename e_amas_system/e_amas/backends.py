"""Async model backends for mock mode and vLLM/OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import Challenge, WorkerResponse, WorkerTask
from .utils import estimate_token_count, stable_fraction


class AsyncLLMBackend(Protocol):
    """Protocol for async LLM backends."""

    async def generate_batch(
        self,
        tasks: list[WorkerTask],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> list[WorkerResponse]:
        """Generate one batch of worker responses."""


@dataclass(slots=True)
class MockLLMBackend:
    """Deterministic backend for local testing without network access."""

    base_latency_seconds: float = 0.03

    async def generate_batch(
        self,
        tasks: list[WorkerTask],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> list[WorkerResponse]:
        del model, temperature, max_tokens
        return await asyncio.gather(*(self._solve(task) for task in tasks))

    async def _solve(self, task: WorkerTask) -> WorkerResponse:
        challenge_data = task.metadata.get("challenge")
        if not isinstance(challenge_data, Challenge):
            raise TypeError("MockLLMBackend requires the Challenge object in task metadata.")

        jitter = stable_fraction(task.worker_id, task.reasoning_mode, challenge_data.challenge_id) * 0.03
        latency = self.base_latency_seconds + (challenge_data.difficulty * 0.015) + jitter
        await asyncio.sleep(latency)

        accuracy = self._accuracy(task, challenge_data)
        roll = stable_fraction(challenge_data.challenge_id, task.team_name, task.reasoning_mode, "roll")
        if roll <= accuracy:
            content = challenge_data.ground_truth
        else:
            content = self._wrong_answer(challenge_data, roll)

        prompt_tokens = estimate_token_count(task.system_prompt, task.user_prompt)
        completion_tokens = estimate_token_count(content)
        return WorkerResponse(
            worker_id=task.worker_id,
            team_name=task.team_name,
            reasoning_mode=task.reasoning_mode,
            system_prompt=task.system_prompt,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_seconds=latency,
        )

    def _accuracy(self, task: WorkerTask, challenge: Challenge) -> float:
        mode_bonus = {
            "verifier": 0.14,
            "skeptic": 0.1,
            "debugger": 0.09,
            "deliberate": 0.08,
            "structured": 0.08,
            "consensus_seed": 0.05,
            "direct": 0.02,
            "minimalist": -0.02,
        }.get(task.reasoning_mode, 0.0)
        difficulty_penalty = 0.08 * max(challenge.difficulty - 1, 0)
        team_bonus = 0.04 if task.team_name.lower().endswith("b") else 0.0
        lesson_bonus = 0.03 if "Recent manager notes" in task.system_prompt else 0.0
        accuracy = 0.72 + mode_bonus + team_bonus + lesson_bonus - difficulty_penalty
        return min(0.98, max(0.08, accuracy))

    def _wrong_answer(self, challenge: Challenge, roll: float) -> str:
        if challenge.family == "arithmetic":
            return str(int(challenge.ground_truth) + (1 if roll < 0.5 else -1))
        if challenge.family == "word_sort":
            words = list(challenge.metadata.get("words", []))
            if not words:
                return challenge.ground_truth
            rotated = words[1:] + words[:1]
            return ", ".join(word.lower() for word in rotated)
        if challenge.family == "count_char":
            return str(max(0, int(challenge.ground_truth) + (2 if roll < 0.5 else -2)))
        if challenge.family == "compare_sums":
            return "team right" if challenge.ground_truth == "team left" else "team left"
        return ""


@dataclass(slots=True)
class OpenAICompatibleAsyncBackend:
    """Async backend for vLLM or any OpenAI-compatible chat endpoint."""

    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 120
    extra_payload: dict[str, Any] = field(default_factory=dict)

    async def generate_batch(
        self,
        tasks: list[WorkerTask],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> list[WorkerResponse]:
        coroutines = [
            self._generate_one(
                task,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            for task in tasks
        ]
        return await asyncio.gather(*coroutines)

    async def _generate_one(
        self,
        task: WorkerTask,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> WorkerResponse:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": task.system_prompt},
                {"role": "user", "content": task.user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self.extra_payload,
        }
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            body = await asyncio.to_thread(self._post_json, payload)
            latency = loop.time() - started
            usage = body.get("usage", {}) if isinstance(body, dict) else {}
            choices = body.get("choices", []) if isinstance(body, dict) else []
            if not choices:
                raise RuntimeError("Response missing choices")
            message = choices[0].get("message", {})
            content = self._extract_content(message.get("content", ""))
            prompt_tokens = int(usage.get("prompt_tokens", estimate_token_count(task.system_prompt, task.user_prompt)))
            completion_tokens = int(usage.get("completion_tokens", estimate_token_count(content)))
            return WorkerResponse(
                worker_id=task.worker_id,
                team_name=task.team_name,
                reasoning_mode=task.reasoning_mode,
                system_prompt=task.system_prompt,
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_seconds=latency,
            )
        except Exception as exc:
            latency = loop.time() - started
            return WorkerResponse(
                worker_id=task.worker_id,
                team_name=task.team_name,
                reasoning_mode=task.reasoning_mode,
                system_prompt=task.system_prompt,
                content="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_seconds=latency,
                error=str(exc),
            )

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {details[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError("Chat completion response is not a JSON object")
        return data

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _extract_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(str(item.get("text", "")))
            return "".join(chunks).strip()
        return str(content).strip()
