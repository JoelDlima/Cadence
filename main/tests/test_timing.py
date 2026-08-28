"""Pure timing-policy tests: NPCI maintenance, holidays, contactability, retry table."""

from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, timedelta

import pytest

from revive.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    EXPIRED_INSTRUMENT,
    NO_FUNDS,
    TIMEOUT,
)
from revive.policy.timing import (
    INDIAN_HOLIDAYS_2026,
    NPCI_MAINTENANCE_WINDOW,
    PEAK_HOLD_WINDOWS_IST,
    hold_release_shift,
    is_holiday,
    is_npci_maintenance,
    is_peak_hold,
    next_contactable_moment,
    retry_delay_for_cause,
)

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _ist(hour: int, minute: int = 0, *, day: date = date(2026, 8, 22)) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_IST)


# --- maintenance window ---------------------------------------------------------


def test_maintenance_window_bounds() -> None:
    assert NPCI_MAINTENANCE_WINDOW == (1, 6)


@pytest.mark.parametrize(
    "moment",
    [_ist(1), _ist(2, 30), _ist(5, 59)],
)
def test_inside_npci_maintenance(moment: datetime) -> None:
    assert is_npci_maintenance(moment) is True


@pytest.mark.parametrize(
    "moment",
    [_ist(0, 59), _ist(6), _ist(12), _ist(23)],
)
def test_outside_npci_maintenance(moment: datetime) -> None:
    assert is_npci_maintenance(moment) is False


# --- holidays --------------------------------------------------------------


@pytest.mark.parametrize(
    "day",
    sorted(INDIAN_HOLIDAYS_2026),
)
def test_every_listed_holiday_is_detected(day: date) -> None:
    assert is_holiday(day) is True


@pytest.mark.parametrize(
    ("month", "day"),
    [(1, 25), (3, 5), (8, 14), (10, 3), (11, 9), (12, 24), (8, 22)],
)
def test_adjacent_and_ordinary_days_are_not_holidays(month: int, day: int) -> None:
    assert is_holiday(date(2026, month, day)) is False


# --- next_contactable_moment -----------------------------------------------


def test_already_contactable_moment_is_returned_unchanged() -> None:
    moment = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)  # 15:30 IST Saturday

    assert next_contactable_moment(moment) == moment


def test_maintenance_hour_defers_to_quiet_hours_end() -> None:
    # 02:00 IST Sunday -> inside maintenance and quiet hours -> 09:00 IST.
    moment = datetime(2026, 8, 22, 20, 30, tzinfo=UTC)

    assert next_contactable_moment(moment) == datetime(2026, 8, 23, 3, 30, tzinfo=UTC)


def test_evening_quiet_hours_defer_to_next_morning() -> None:
    # 22:00 IST Friday -> quiet hours -> 09:00 IST Saturday.
    moment = datetime(2026, 8, 21, 16, 30, tzinfo=UTC)

    assert next_contactable_moment(moment) == datetime(2026, 8, 22, 3, 30, tzinfo=UTC)


def test_exact_quiet_hours_start_boundary_defers() -> None:
    # 21:00 IST exactly is the inclusive start of quiet hours.
    moment = datetime(2026, 8, 21, 15, 30, tzinfo=UTC)

    assert next_contactable_moment(moment) == datetime(2026, 8, 22, 3, 30, tzinfo=UTC)


def test_independence_day_skips_to_next_morning() -> None:
    # 10:00 IST on Aug 15 (holiday) -> 09:00 IST Aug 16.
    moment = datetime(2026, 8, 15, 4, 30, tzinfo=UTC)

    assert next_contactable_moment(moment) == datetime(2026, 8, 16, 3, 30, tzinfo=UTC)


def test_diwali_pre_dawn_combines_all_three_blackouts() -> None:
    # 03:00 IST Nov 8: maintenance + quiet hours + Diwali holiday.
    moment = datetime(2026, 11, 7, 21, 30, tzinfo=UTC)

    assert next_contactable_moment(moment) == datetime(2026, 11, 9, 3, 30, tzinfo=UTC)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        next_contactable_moment(datetime(2026, 8, 22, 10, 0))


# --- retry delay table ------------------------------------------------------


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (NO_FUNDS, timedelta(hours=72)),
        (BANK_DOWN, timedelta(hours=6)),
        (TIMEOUT, timedelta(hours=2)),
        (CUSTOMER_ABORTED, timedelta(hours=24)),
        (BAD_VPA, timedelta(hours=24)),
        (EXPIRED_INSTRUMENT, timedelta(hours=24)),
    ],
)
def test_retry_delay_table_values(cause: str, expected: timedelta) -> None:
    assert retry_delay_for_cause(cause, attempt_no=1, rng_seed=42) == expected


def test_unknown_cause_gets_default_delay() -> None:
    assert retry_delay_for_cause("MYSTERY", attempt_no=2, rng_seed=7) == timedelta(hours=24)


def test_delay_is_deterministic_across_seeds_and_attempts() -> None:
    first = retry_delay_for_cause(BANK_DOWN, attempt_no=1, rng_seed=1)
    second = retry_delay_for_cause(BANK_DOWN, attempt_no=3, rng_seed=999)

    assert first == second


# --- NPCI peak-hold windows (phantom-failure guard) --------------------------


def test_default_peak_hold_windows() -> None:
    assert PEAK_HOLD_WINDOWS_IST == ((10, 13), (17, 22))


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (9, 59, False),  # just before the morning window
        (10, 0, True),  # inclusive start
        (12, 59, True),
        (13, 0, False),  # exclusive end
        (16, 59, False),  # between the two windows
        (17, 0, True),  # inclusive start of the evening window
        (21, 59, True),
        (22, 0, False),  # exclusive end
    ],
)
def test_peak_hold_window_edges(hour: int, minute: int, expected: bool) -> None:
    moment = _ist(hour, minute).astimezone(UTC)

    assert is_peak_hold(moment) is expected


def test_hold_release_shift_returns_none_off_window() -> None:
    off_window = [_ist(9, 59), _ist(13, 30), _ist(16, 59), _ist(22, 0)]

    for moment in off_window:
        assert hold_release_shift(moment.astimezone(UTC)) is None


def test_hold_release_shift_returns_window_end_plus_buffer_in_window() -> None:
    # 11:00 IST -> window ends 13:00 IST, +90m buffer = 14:30 IST = 09:00 UTC.
    assert hold_release_shift(_ist(11).astimezone(UTC)) == datetime(
        2026, 8, 22, 9, 0, tzinfo=UTC
    )
    # 18:00 IST -> evening window ends 22:00 IST, +90m = 23:30 IST = 18:00 UTC.
    assert hold_release_shift(_ist(18).astimezone(UTC)) == datetime(
        2026, 8, 22, 18, 0, tzinfo=UTC
    )
    # Custom buffer is honored.
    assert hold_release_shift(_ist(10).astimezone(UTC), buffer_minutes=30) == datetime(
        2026, 8, 22, 8, 0, tzinfo=UTC
    )


def test_is_peak_hold_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        is_peak_hold(datetime(2026, 8, 22, 11, 0))


def test_hold_release_shift_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        hold_release_shift(datetime(2026, 8, 22, 11, 0))
