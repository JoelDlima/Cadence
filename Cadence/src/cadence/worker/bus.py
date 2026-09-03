"""Durable-task bus: claims due queue rows and dispatches them to registered handlers.

One tick = one atomic claim batch. Handlers run inline; failures re-queue with
exponential backoff (capped at 1h) and dead-letter after max_attempts. Tasks
whose type has no registered handler back off a fixed 5 minutes so late
registration is possible without losing work.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from cadence.clock import Clock, utc_iso
from cadence.store.queue_repo import QueueRepo, Task

_NO_HANDLER_ERROR = "no_handler_registered"
_NO_HANDLER_BACKOFF_SECONDS = 300
_BASE_BACKOFF_SECONDS = 60
_MAX_BACKOFF_SECONDS = 3600


class Worker:
    def __init__(self, queue: QueueRepo, clock: Clock) -> None:
        self._queue = queue
        self._clock = clock

    def run_once(
        self, handlers: dict[str, Callable[[dict], None]], *, max_tasks: int = 25
    ) -> int:
        """Claim up to `max_tasks` due tasks, run each handler once, return claim count."""
        now = self._clock.now()
        claimed = self._queue.claim_due(now_iso=utc_iso(now), limit=max_tasks)
        for task in claimed:
            self._process(handlers, task, now)
        return len(claimed)

    def _process(
        self,
        handlers: dict[str, Callable[[dict], None]],
        task: Task,
        now: datetime,
    ) -> None:
        handler = handlers.get(task.task_type)
        if handler is None:
            self._retry_later(
                task.task_id,
                backoff_seconds=_NO_HANDLER_BACKOFF_SECONDS,
                now=now,
                error=_NO_HANDLER_ERROR,
            )
            return
        try:
            handler(task.payload)
        except Exception as exc:  # worker must survive any handler fault
            backoff_seconds = min(_BASE_BACKOFF_SECONDS * 2**task.attempts, _MAX_BACKOFF_SECONDS)
            self._retry_later(
                task.task_id, backoff_seconds=backoff_seconds, now=now, error=str(exc)
            )
            return
        self._queue.mark_done(task.task_id)

    def _retry_later(
        self, task_id: int, *, backoff_seconds: int, now: datetime, error: str
    ) -> None:
        self._queue.mark_failed_retry(
            task_id,
            backoff_seconds=backoff_seconds,
            next_available_at=utc_iso(now + timedelta(seconds=backoff_seconds)),
            error=error,
        )
