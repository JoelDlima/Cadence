"""Evidence-based retry timing for Indian payment rails (pure functions).

Research anchors (2026 dunning/UPI studies; see docs/research-verification-report.md):

- Flat 24h retry ladders are the leading cause of preventable revenue loss;
  optimal retry timing varies by decline reason and day-of-month.
- Indian rails: banks run 85-95% UPI success rates, failures cluster at peak
  hours, NPCI operates daily UPI maintenance windows (~01:00-06:00 IST), and
  bank-server issues are the #1 failure point.
- Pause offers convert 15-25% of cancels and retention sequences hit a 34%
  median save rate - the basis for the engine's save-offer ladder.
- NPCI since 1 Aug 2025 holds UPI AutoPay debits during peak hours and
  releases them later: a "failed" debit inside a hold window may be QUEUED,
  not failed (subshield.com/blog/upi-autopay-peak-window-failures, Jun 2026;
  Livemint Oct 2025 - AutoPay failures up to 90%, market retreating to cards).

Everything here is pure: no I/O, no logging, fully deterministic.
"""

from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, timedelta

from cadence.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    EXPIRED_INSTRUMENT,
    NO_FUNDS,
    TIMEOUT,
)

__all__ = [
    "INDIAN_HOLIDAYS_2026",
    "NPCI_MAINTENANCE_WINDOW",
    "PEAK_HOLD_WINDOWS_IST",
    "hold_release_shift",
    "is_holiday",
    "is_npci_maintenance",
    "is_peak_hold",
    "next_contactable_moment",
    "retry_delay_for_cause",
]

# Daily UPI maintenance (start hour inclusive, end hour exclusive), IST wall clock.
NPCI_MAINTENANCE_WINDOW: tuple[int, int] = (1, 6)

# Approximate NPCI peak-hold windows per Aug-2025 rule (start hour inclusive,
# end hour exclusive, local wall clock); verify against current NPCI circular
# before production use. A debit "failing" inside these windows may merely be
# queued by NPCI and settle on its own once released.
PEAK_HOLD_WINDOWS_IST: tuple[tuple[int, int], ...] = ((10, 13), (17, 22))

# Customer quiet hours (start inclusive, end exclusive), IST wall clock.
_QUIET_HOURS_IST: tuple[int, int] = (21, 9)

_MAX_SEARCH_DAYS = 10

# National holidays for scheduling blackout. NOTE: extend yearly - regenerate
# this set each December from the RBI/NPCI holiday notification.
INDIAN_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
        date(2026, 1, 26),  # Republic Day
        date(2026, 3, 4),  # Holi
        date(2026, 8, 15),  # Independence Day
        date(2026, 10, 2),  # Gandhi Jayanti
        date(2026, 11, 8),  # Diwali
        date(2026, 12, 25),  # Christmas
    }
)

# Evidence-based per-cause retry delays (2026 timing studies: per-reason delays
# beat flat 24h ladders; bank downtime usually clears within hours, while
# cash-flow and instrument problems resolve on day-scale rhythms).
_CAUSE_RETRY_DELAYS: dict[str, timedelta] = {
    NO_FUNDS: timedelta(hours=72),  # caller aligns to payday; +72h is the fallback
    BANK_DOWN: timedelta(hours=6),  # downtime usually clears
    TIMEOUT: timedelta(hours=2),  # collect requests expire fast; retry soon
    CUSTOMER_ABORTED: timedelta(hours=24),
    BAD_VPA: timedelta(hours=24),
    EXPIRED_INSTRUMENT: timedelta(hours=24),
}
_DEFAULT_RETRY_DELAY = timedelta(hours=24)


def is_npci_maintenance(moment_ist: datetime) -> bool:
    """True when the IST wall-clock moment falls inside daily UPI maintenance."""
    start, end = NPCI_MAINTENANCE_WINDOW
    return start <= moment_ist.hour < end


def _ensure_utc(moment_utc: datetime) -> datetime:
    if moment_utc.tzinfo is None:
        raise ValueError("peak-hold helpers require an aware datetime")
    return moment_utc


def is_peak_hold(moment_utc: datetime, tz: str = "Asia/Kolkata") -> bool:
    """True when the local hour of ``moment_utc`` falls in an NPCI peak-hold window.

    Windows are start-inclusive / end-exclusive, matching the maintenance-window
    convention above. See PEAK_HOLD_WINDOWS_IST for the research caveat.
    """
    local_hour = _ensure_utc(moment_utc).astimezone(zoneinfo.ZoneInfo(tz)).hour
    return any(start <= local_hour < end for start, end in PEAK_HOLD_WINDOWS_IST)


def hold_release_shift(
    moment_utc: datetime, tz: str = "Asia/Kolkata", buffer_minutes: int = 90
) -> datetime | None:
    """UTC moment when a debit held at ``moment_utc`` would be released, else None.

    NPCI queues AutoPay debits attempted inside a peak-hold window and releases
    them after the window ends; the buffer covers release lag. Returns the end
    of the containing window plus ``buffer_minutes`` converted back to UTC, or
    None when the moment sits outside every hold window (nothing held).
    """
    zone = zoneinfo.ZoneInfo(tz)
    local = _ensure_utc(moment_utc).astimezone(zone)
    for start, end in PEAK_HOLD_WINDOWS_IST:
        if start <= local.hour < end:
            release_local = local.replace(hour=end, minute=0, second=0, microsecond=0)
            return (release_local + timedelta(minutes=buffer_minutes)).astimezone(UTC)
    return None


def is_holiday(day: date) -> bool:
    """True when the date is an Indian national-holiday scheduling blackout."""
    return day in INDIAN_HOLIDAYS_2026


def _ensure_aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("next_contactable_moment requires an aware datetime")
    return moment


def _in_quiet_hours(hour: int) -> bool:
    start, end = _QUIET_HOURS_IST
    return hour >= start or hour < end


def _next_morning(local: datetime) -> datetime:
    _, end = _QUIET_HOURS_IST
    return (local + timedelta(days=1)).replace(hour=end, minute=0, second=0, microsecond=0)


def _quiet_exit(local: datetime) -> datetime:
    """First non-quiet moment: 09:00 same day for pre-dawn, next day otherwise."""
    if local.hour >= _QUIET_HOURS_IST[0]:
        return _next_morning(local)
    _, end = _QUIET_HOURS_IST
    return local.replace(hour=end, minute=0, second=0, microsecond=0)


def next_contactable_moment(after_utc: datetime, tz: str = "Asia/Kolkata") -> datetime:
    """Earliest UTC moment >= ``after_utc`` that is customer-contactable.

    A moment is contactable when it (a) sits outside the NPCI maintenance
    window, (b) is not an Indian national holiday, and (c) sits outside quiet
    hours 21:00-09:00 in ``tz``. Moments already contactable are returned
    unchanged. Day-by-day search capped at 10 iterations.
    """
    zone = zoneinfo.ZoneInfo(tz)
    local = _ensure_aware(after_utc).astimezone(zone)
    for _ in range(_MAX_SEARCH_DAYS):
        if is_holiday(local.date()):
            local = _next_morning(local)
            continue
        if is_npci_maintenance(local):
            local = local.replace(
                hour=NPCI_MAINTENANCE_WINDOW[1], minute=0, second=0, microsecond=0
            )
            continue
        if _in_quiet_hours(local.hour):
            local = _quiet_exit(local)
            continue
        return local.astimezone(UTC)
    raise ValueError(f"no contactable moment within {_MAX_SEARCH_DAYS} days of {after_utc}")


def retry_delay_for_cause(root_cause: str, attempt_no: int, rng_seed: int) -> timedelta:
    """Delay before the next retry for a root cause (evidence-based table).

    Cites the 2026 timing studies: flat 24h retries are the leading cause of
    preventable revenue loss, and optimal timing varies by decline reason -
    e.g. bank downtime usually clears within hours (short delay), while
    cash-flow shortfalls resolve on payday rhythms (long fallback; the caller
    aligns NO_FUNDS retries to payday and only uses +72h as a floor).
    ``attempt_no`` and ``rng_seed`` are reserved for per-attempt jitter so
    mass retries stop clustering at peak hours; current policy applies none,
    keeping the returned values exactly the researched table delays.
    """
    del attempt_no, rng_seed  # reserved: see docstring
    return _CAUSE_RETRY_DELAYS.get(root_cause, _DEFAULT_RETRY_DELAY)
