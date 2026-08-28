"""Bank-outage circuit breaker: same-cause failure spike detection (pure).

The caller supplies the recent window of failure causes observed across ALL
journeys; this module only decides whether one cause has spiked past the pause
threshold. Windowing is deliberately left to the caller so the check stays
clock-free and trivially testable.
"""

from __future__ import annotations

__all__ = ["detect_cause_outage"]

DEFAULT_WINDOW_MINUTES = 1440
DEFAULT_THRESHOLD = 5


def detect_cause_outage(
    *,
    recent_failure_causes: list[str],
    cause: str,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    threshold: int = DEFAULT_THRESHOLD,
) -> bool:
    """True when ``cause`` occurrences in the recent window reach ``threshold``.

    ``window_minutes`` documents the caller's windowing contract (default 24h);
    the list passed in is expected to already cover that window.
    """
    return recent_failure_causes.count(cause) >= threshold
