"""Deterministic Promise-to-Pay extraction from free-text customer replies.

Pure functions only: no I/O, no clock reads — `today` is injected so the same
reply parses identically in tests, replays, and production. Hinglish and
English patterns are matched case-insensitively, refusal first (safety over
optimism), then explicit dates, then durations, then vague promises.
"""

from __future__ import annotations

import calendar
import re
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

KIND_DATE = "date"
KIND_DURATION = "duration"
KIND_VAGUE = "vague"
KIND_REFUSAL = "refusal"
KIND_UNPARSEABLE = "unparseable"

_CONFIDENCE: dict[str, float] = {
    KIND_DATE: 0.9,
    KIND_DURATION: 0.8,
    KIND_VAGUE: 0.5,
    KIND_REFUSAL: 1.0,
    KIND_UNPARSEABLE: 0.0,
}

_VAGUE_DAYS = 3

_REFUSAL_RE = re.compile(
    r"\b(nahi|nahin|cancel|stop|mat|band|don'?t|cannot|can'?t)\b", re.IGNORECASE
)
_DAY_OF_MONTH_RE = re.compile(r"\b(\d{1,2})\s*(?:tarikh|tareekh|taarikh)\b", re.IGNORECASE)
_DAYS_RE = re.compile(r"\b(\d+)\s*din\b", re.IGNORECASE)
_WEEKS_RE = re.compile(r"\b(\d+)\s*(?:hafte|hafte|week)s?\b", re.IGNORECASE)
_NEXT_MONTH_RE = re.compile(r"\b(?:next month|agle mahine)\b", re.IGNORECASE)
_KAL_RE = re.compile(r"\bkal\b", re.IGNORECASE)
_PARSO_RE = re.compile(r"\b(?:parso|parson)\b", re.IGNORECASE)
_NEXT_WEEK_RE = re.compile(r"\b(?:next week|agle hafte)\b", re.IGNORECASE)
_VAGUE_RE = re.compile(
    r"\b(pakka|karunga|karungi|karenge|kardunga|try|promise|jaldi|soon|baad\s*me+|"
    r"(?:karta|karti)\s+h[a-z]*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PromiseToPay:
    """Parsed commitment extracted from one customer reply."""

    commit_date_iso: str | None
    confidence: float
    kind: str


def parse_reply(text: str, *, today: datetime, tz: str = "Asia/Kolkata") -> PromiseToPay:
    """Parse a customer reply into a PromiseToPay (never raises)."""
    stripped = text.strip()
    if not stripped:
        return _unparseable()
    local = today if today.tzinfo is not None else today.replace(tzinfo=zoneinfo.ZoneInfo(tz))
    base = local.date()
    if _REFUSAL_RE.search(stripped):
        return PromiseToPay(None, _CONFIDENCE[KIND_REFUSAL], KIND_REFUSAL)
    day_match = _DAY_OF_MONTH_RE.search(stripped)
    if day_match is not None:
        commit = _day_of_month(base, int(day_match.group(1)))
        return PromiseToPay(commit.isoformat(), _CONFIDENCE[KIND_DATE], KIND_DATE)
    next_month = _NEXT_MONTH_RE.search(stripped)
    if next_month is not None:
        return PromiseToPay(
            _same_day_next_month(base).isoformat(), _CONFIDENCE[KIND_DURATION], KIND_DURATION
        )
    days = _days_or_weeks(stripped)
    if days is not None:
        return PromiseToPay(
            (base + timedelta(days=days)).isoformat(), _CONFIDENCE[KIND_DURATION], KIND_DURATION
        )
    offset_days = _relative_day_offset(stripped)
    if offset_days is not None:
        return PromiseToPay(
            (base + timedelta(days=offset_days)).isoformat(), _CONFIDENCE[KIND_DATE], KIND_DATE
        )
    if _VAGUE_RE.search(stripped):
        return PromiseToPay(None, _CONFIDENCE[KIND_VAGUE], KIND_VAGUE)
    return _unparseable()


def ptp_to_timer_days(ptp: PromiseToPay, *, today: date | None = None) -> int | None:
    """Timer length in days for a parsed promise; None when no follow-up is due.

    ``today`` anchors date-kind math; it defaults to the real UTC today so the
    single-argument form stays usable, but callers with a clock should pass it.
    """
    if ptp.kind == KIND_VAGUE:
        return _VAGUE_DAYS
    if ptp.kind in (KIND_REFUSAL, KIND_UNPARSEABLE) or ptp.commit_date_iso is None:
        return None
    reference = today if today is not None else datetime.now(UTC).date()
    commit = date.fromisoformat(ptp.commit_date_iso)
    return max((commit - reference).days, 0)


def _unparseable() -> PromiseToPay:
    return PromiseToPay(None, _CONFIDENCE[KIND_UNPARSEABLE], KIND_UNPARSEABLE)


def _days_or_weeks(text: str) -> int | None:
    weeks = _WEEKS_RE.search(text)
    if weeks is not None:
        return int(weeks.group(1)) * 7
    days = _DAYS_RE.search(text)
    if days is not None:
        return int(days.group(1))
    return None


def _relative_day_offset(text: str) -> int | None:
    if _KAL_RE.search(text):
        return 1
    if _PARSO_RE.search(text):
        return 2
    if _NEXT_WEEK_RE.search(text):
        return 7
    return None


def _bump_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _day_of_month(base: date, day: int) -> date:
    """The named day; past days roll to next month, overflow clamps to month end."""
    year, month = base.year, base.month
    if day < base.day:
        year, month = _bump_month(year, month)
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(day, 1), last))


def _same_day_next_month(base: date) -> date:
    year, month = _bump_month(base.year, base.month)
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(base.day, last))


__all__ = [
    "PromiseToPay",
    "KIND_DATE",
    "KIND_DURATION",
    "KIND_REFUSAL",
    "KIND_UNPARSEABLE",
    "KIND_VAGUE",
    "parse_reply",
    "ptp_to_timer_days",
]
