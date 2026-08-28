"""Append-only, hash-chained event store.

hash_n = sha256(prev_hash || canonical_json(event_without_hash)).
Tampering with any row breaks every subsequent hash - the audit trail the
buildathon rubric asks for is verifiable, not just present.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from revive.events import AGG_JOURNEY, Event, InvalidEvent, make_event
from revive.store.db import Database

GENESIS_HASH = "0" * 64


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_hash(prev_hash: str, event_fields: dict[str, Any]) -> str:
    basis = prev_hash + canonical(event_fields)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AppendResult:
    seq: int
    event_id: str
    hash: str


class EventStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def last_hash(self) -> str:
        row = self._db.conn.execute(
            "SELECT hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row["hash"] if row else GENESIS_HASH

    def append(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        occurred_at: str,
        recorded_at: str,
        event_id: str,
    ) -> AppendResult:
        fields = make_event(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            event_id=event_id,
        )
        prev = self.last_hash()
        digest = compute_hash(prev, fields)
        cursor = self._db.conn.execute(
            """
            INSERT INTO events
                (event_id, occurred_at, recorded_at, type, aggregate_type,
                 aggregate_id, payload, prev_hash, hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["event_id"],
                fields["occurred_at"],
                fields["recorded_at"],
                fields["type"],
                fields["aggregate_type"],
                fields["aggregate_id"],
                canonical(fields["payload"]),
                prev,
                digest,
            ),
        )
        return AppendResult(seq=cursor.lastrowid, event_id=event_id, hash=digest)

    def get_by_aggregate(
        self, aggregate_type: str, aggregate_id: str
    ) -> list[Event]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM events
            WHERE aggregate_type = ? AND aggregate_id = ?
            ORDER BY seq ASC
            """,
            (aggregate_type, aggregate_id),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_by_type(self, event_type: str, limit: int = 500) -> list[Event]:
        rows = self._db.conn.execute(
            "SELECT * FROM events WHERE type = ? ORDER BY seq DESC LIMIT ?",
            (event_type, limit),
        ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def verify_chain(self) -> tuple[bool, int | None]:
        """Recompute the full chain. Returns (ok, first_bad_seq or None)."""
        prev = GENESIS_HASH
        for row in self._db.conn.execute("SELECT * FROM events ORDER BY seq ASC"):
            fields = {
                "event_id": row["event_id"],
                "occurred_at": row["occurred_at"],
                "recorded_at": row["recorded_at"],
                "type": row["type"],
                "aggregate_type": row["aggregate_type"],
                "aggregate_id": row["aggregate_id"],
                "payload": json.loads(row["payload"]),
            }
            expected = compute_hash(prev, fields)
            if row["prev_hash"] != prev or row["hash"] != expected:
                return False, row["seq"]
            prev = row["hash"]
        return True, None

    def count(self) -> int:
        return int(self._db.conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"])

    @staticmethod
    def _row_to_event(row: Any) -> Event:
        return Event(
            seq=row["seq"],
            event_id=row["event_id"],
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
            type=row["type"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            payload=json.loads(row["payload"]),
            prev_hash=row["prev_hash"],
            hash=row["hash"],
        )


__all__ = ["AGG_JOURNEY", "EventStore", "GENESIS_HASH", "InvalidEvent", "AppendResult"]
