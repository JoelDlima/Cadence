"""Timer scheduling surface over the durable task queue.

Timers are ordinary `task_queue` rows whose `available_at` lies in the future:
the worker simply never claims them until they come due, so no separate timer
process exists. Schedule computation (payday alignment, quiet-hour deferral)
lives in the journey engine and policy guardian; this module only re-exports
the loop entry point so callers can treat "scheduler" and "bus" as one thing.
"""

from cadence.worker.bus import Worker

__all__ = ["Worker"]
