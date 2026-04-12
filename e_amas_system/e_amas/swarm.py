"""Worker swarm execution with asynchronous batch dispatch."""

from __future__ import annotations

import asyncio

from .backends import AsyncLLMBackend
from .models import BatchConfiguration, BatchExecution, Challenge, WorkerTask
from .utils import utc_now_iso


class WorkerSwarm:
    """Dispatch worker variants concurrently to exploit backend batching."""

    def __init__(self, backend: AsyncLLMBackend, *, model: str) -> None:
        self.backend = backend
        self.model = model

    async def run_batch(
        self,
        *,
        challenge: Challenge,
        configuration: BatchConfiguration,
    ) -> BatchExecution:
        """Submit all workers concurrently and return the whole batch."""
        started_at = utc_now_iso()
        tasks = [
            WorkerTask(
                worker_id=f"{configuration.team_name}-worker-{index + 1}",
                team_name=configuration.team_name,
                reasoning_mode=variant.mode,
                system_prompt=variant.system_prompt,
                user_prompt=challenge.prompt,
                metadata={"challenge": challenge},
            )
            for index, variant in enumerate(configuration.prompt_variants)
        ]
        loop = asyncio.get_running_loop()
        start = loop.time()
        responses = await self.backend.generate_batch(
            tasks,
            model=self.model,
            temperature=configuration.temperature,
            max_tokens=configuration.max_tokens,
        )
        duration = loop.time() - start
        return BatchExecution(
            started_at=started_at,
            duration_seconds=duration,
            responses=responses,
        )
