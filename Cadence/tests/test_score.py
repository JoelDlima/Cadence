"""Recovery score: amount bands, cause bonuses, penalties, clamps (pure)."""

from __future__ import annotations

import pytest

from revive.classify.taxonomy import (
    BANK_DOWN,
    CUSTOMER_ABORTED,
    HARD_DECLINE,
    NO_FUNDS,
    TIMEOUT,
    UNKNOWN,
)
from revive.policy.score import recovery_score

pytestmark = [pytest.mark.unit]


def _score(amount_minor: int = 49_900, **overrides: int | str | None) -> int:
    kwargs: dict[str, int | str | None] = {
        "amount_minor": amount_minor,
        "attempts_used": 0,
        "touches_used": 0,
        "root_cause": NO_FUNDS,
    }
    kwargs.update(overrides)
    return recovery_score(**kwargs)  # type: ignore[arg-type]


def test_baseline_score_with_no_signals_is_fifty() -> None:
    assert _score(root_cause=None, attempts_used=0, touches_used=0) == 50


@pytest.mark.parametrize(
    ("amount_minor", "expected"),
    [
        (99_999, 50),
        (100_000, 60),
        (499_999, 60),
        (500_000, 70),
        (5_000_000, 70),
    ],
)
def test_amount_bands_add_ten_then_twenty(amount_minor: int, expected: int) -> None:
    assert _score(amount_minor=amount_minor, root_cause=None) == expected


@pytest.mark.parametrize(
    ("root_cause", "expected"),
    [
        (NO_FUNDS, 65),
        (TIMEOUT, 60),
        (CUSTOMER_ABORTED, 55),
        (BANK_DOWN, 50),
        (UNKNOWN, 50),
        (None, 50),
    ],
)
def test_transient_causes_add_bonus_while_neutral_ones_do_not(
    root_cause: str | None, expected: int
) -> None:
    assert _score(root_cause=root_cause) == expected


def test_attempts_and_touches_penalize_the_score() -> None:
    # Act
    scored = _score(root_cause=None, attempts_used=3, touches_used=2)

    # Assert: 50 - 3*8 - 2*5 = 16
    assert scored == 16


def test_score_clamps_at_zero_floor() -> None:
    # Arrange: 50 - 7*8 - 5*5 = -29 raw
    scored = _score(root_cause=None, attempts_used=7, touches_used=5)

    # Act / Assert
    assert scored == 0


def test_best_case_stays_within_the_hundred_cap() -> None:
    # Arrange: biggest reachable combo is 50 + 20 + 15 = 85
    scored = _score(amount_minor=600_000, root_cause=NO_FUNDS)

    # Act / Assert
    assert scored == 85
    assert scored <= 100


def test_hard_decline_scores_zero_regardless_of_signals() -> None:
    assert (
        _score(amount_minor=5_000_000, attempts_used=0, touches_used=0, root_cause=HARD_DECLINE)
        == 0
    )
