"""Clock abstraction so time-dependent logic (quiet hours, timers, windows) is
deterministically testable. Production uses `SystemClock`; tests use `FakeClock`."""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current aware UTC datetime."""
        ...

    def in_tz(self, tz_name: str) -> datetime:
        """Current aware datetime converted to the named timezone."""
        ...


@dataclass(frozen=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def in_tz(self, tz_name: str) -> datetime:
        return self.now().astimezone(zoneinfo.ZoneInfo(tz_name))


@dataclass
class FakeClock:
    """Manually advanced clock for deterministic tests and simulations."""

    _now: datetime = field(default_factory=lambda: datetime(2026, 8, 22, 10, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self._now

    def in_tz(self, tz_name: str) -> datetime:
        return self._now.astimezone(zoneinfo.ZoneInfo(tz_name))

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FakeClock.set requires an aware datetime")
        self._now = moment


def utc_iso(moment: datetime) -> str:
    """Canonical ISO-8601 string (UTC, seconds precision) used in events and DB."""
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
