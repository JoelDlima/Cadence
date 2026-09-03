"""Customer communication preferences (backlog item 9).

A customer may reply "whatsapp only mornings": the ordered allowed-channel list
and preferred IST contact window are stored here and honored downstream by the
Guardian (channel veto + window-based deferral) and by channel selection.
"""

from __future__ import annotations

from dataclasses import dataclass

from cadence.store.db import Database

__all__ = ["Preferences", "PreferencesRepo"]


@dataclass(frozen=True)
class Preferences:
    customer_id: str
    allowed_channels: tuple[str, ...]
    preferred_window_start: int
    preferred_window_end: int


class PreferencesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, customer_id: str) -> Preferences | None:
        row = self._db.conn.execute(
            "SELECT * FROM customer_preferences WHERE customer_id=?", (customer_id,)
        ).fetchone()
        if row is None:
            return None
        return Preferences(
            customer_id=str(row["customer_id"]),
            allowed_channels=_parse_channels(str(row["allowed_channels"])),
            preferred_window_start=int(row["preferred_window_start"]),
            preferred_window_end=int(row["preferred_window_end"]),
        )

    def upsert(
        self,
        *,
        customer_id: str,
        allowed_channels: list[str],
        window_start: int,
        window_end: int,
        now_iso: str,
    ) -> None:
        self._db.conn.execute(
            """
            INSERT INTO customer_preferences
                (customer_id, allowed_channels, preferred_window_start,
                 preferred_window_end, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                allowed_channels = excluded.allowed_channels,
                preferred_window_start = excluded.preferred_window_start,
                preferred_window_end = excluded.preferred_window_end,
                updated_at = excluded.updated_at
            """,
            (customer_id, ",".join(allowed_channels), window_start, window_end, now_iso),
        )


def _parse_channels(raw: str) -> tuple[str, ...]:
    return tuple(channel.strip() for channel in raw.split(",") if channel.strip())
