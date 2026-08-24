from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress

from pipelines.runner import run_pipeline_task
from pipelines.storage import claim_next_pending_task, recover_interrupted_tasks

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


WORKER_ENABLED = _env_bool("PIPELINE_WORKER_ENABLED", True)
WORKER_CONCURRENCY = _env_int("PIPELINE_WORKER_CONCURRENCY", 1)
POLL_INTERVAL_SECONDS = _env_int("PIPELINE_QUEUE_POLL_SECONDS", 2)


class PipelineQueueWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []

    async def start(self) -> None:
        if not WORKER_ENABLED or self._workers:
            return
        recovered = recover_interrupted_tasks()
        if recovered:
            logger.warning("Recovered %d interrupted pipeline task(s)", recovered)
        self._stop.clear()
        self._workers = [
            asyncio.create_task(self._run(index), name=f"pipeline-worker-{index}")
            for index in range(WORKER_CONCURRENCY)
        ]
        self._wake.set()
        logger.info("Pipeline queue started with %d worker(s)", WORKER_CONCURRENCY)

    async def stop(self) -> None:
        if not self._workers:
            return
        self._stop.set()
        self._wake.set()
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()
        logger.info("Pipeline queue stopped")

    def notify(self) -> None:
        self._wake.set()

    @property
    def is_running(self) -> bool:
        return bool(self._workers) and any(not worker.done() for worker in self._workers)

    async def _run(self, index: int) -> None:
        while not self._stop.is_set():
            metadata = await asyncio.to_thread(claim_next_pending_task)
            if metadata:
                task_id = str(metadata.get("task_id") or "")
                pipeline = str(metadata.get("pipeline") or "")
                params = metadata.get("input") if isinstance(metadata.get("input"), dict) else {}
                if not task_id or not pipeline:
                    logger.error("Worker %d claimed malformed task metadata: %s", index, metadata)
                    continue
                try:
                    await run_pipeline_task(task_id, pipeline, params)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Worker %d survived an unexpected task failure", index)
                continue

            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass


pipeline_queue = PipelineQueueWorker()
