"""Recovery score: a 0-100 worth-recovering weight for a journey (pure).

Higher = more worth pursuing aggressively: bigger amounts, transient causes,
fewer wasted attempts/touches. Hard declines are dead ends and score zero.
Drives risk-based triage (intervention intensity, channel order) instead of a
flat policy.
"""

from __future__ import annotations

from cadence.classify.taxonomy import CUSTOMER_ABORTED, HARD_DECLINE, NO_FUNDS, TIMEOUT

__all__ = ["recovery_score"]

_BASE_SCORE = 50
_BIG_AMOUNT_MINOR = 500_000
_MID_AMOUNT_MINOR = 100_000
_BIG_AMOUNT_BONUS = 20
_MID_AMOUNT_BONUS = 10
_CAUSE_BONUS: dict[str, int] = {NO_FUNDS: 15, TIMEOUT: 10, CUSTOMER_ABORTED: 5}
_ATTEMPT_PENALTY = 8
_TOUCH_PENALTY = 5


def _amount_bonus(amount_minor: int) -> int:
    if amount_minor >= _BIG_AMOUNT_MINOR:
        return _BIG_AMOUNT_BONUS
    if amount_minor >= _MID_AMOUNT_MINOR:
        return _MID_AMOUNT_BONUS
    return 0


def recovery_score(
    *, amount_minor: int, attempts_used: int, touches_used: int, root_cause: str | None
) -> int:
    """Deterministic 0-100 score; clamped, no I/O, no clock."""
    if root_cause == HARD_DECLINE:
        return 0
    raw = (
        _BASE_SCORE
        + _amount_bonus(amount_minor)
        + _CAUSE_BONUS.get(root_cause or "", 0)
        - attempts_used * _ATTEMPT_PENALTY
        - touches_used * _TOUCH_PENALTY
    )
    return max(0, min(100, raw))
