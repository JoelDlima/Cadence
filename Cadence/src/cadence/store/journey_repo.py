"""Journey projection repository.

The `journeys` table is a read model rebuilt/advanced transactionally alongside
the events that justify each change. Source of truth = event log; this repo
never writes without a corresponding event written by the caller in the same
unit of work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cadence.store.db import Database

# Journey states (kept here as the canonical string set for the projection).
STATE_OPENED = "OPENED"
STATE_CLASSIFIED = "CLASSIFIED"
STATE_INTERVENING = "INTERVENING"
STATE_WAITING_OUTCOME = "WAITING_OUTCOME"
STATE_RECOVERED = "RECOVERED"
STATE_CLOSED_UNRECOVERED = "CLOSED_UNRECOVERED"
STATE_HUMAN_REVIEW = "HUMAN_REVIEW"

ALL_STATES = frozenset(
    {
        STATE_OPENED,
        STATE_CLASSIFIED,
        STATE_INTERVENING,
        STATE_WAITING_OUTCOME,
        STATE_RECOVERED,
        STATE_CLOSED_UNRECOVERED,
        STATE_HUMAN_REVIEW,
    }
)


@dataclass(frozen=True)
class Journey:
    journey_id: str
    subscription_id: str
    customer_id: str
    state: str
    failure_code: str | None
    root_cause: str | None
    classify_source: str | None
    amount_minor: int | None
    currency: str
    attempts_used: int
    touches_used: int
    window_started_at: str | None
    opened_at: str
    updated_at: str
    closed_at: str | None
    last_retry_at: str | None = None  # PHASE 5: NPCI 18h UPI cooling


class JourneyRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        journey_id: str,
        subscription_id: str,
        customer_id: str,
        amount_minor: int,
        currency: str,
        failure_code: str | None,
        opened_at: str,
    ) -> None:
        self._db.conn.execute(
            """
            INSERT INTO journeys
                (journey_id, subscription_id, customer_id, state, failure_code,
                 amount_minor, currency, window_started_at, opened_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                journey_id,
                subscription_id,
                customer_id,
                STATE_OPENED,
                failure_code,
                amount_minor,
                currency,
                opened_at,
                opened_at,
                opened_at,
            ),
        )

    def get_by_subscription(self, subscription_id: str) -> Journey | None:
        row = self._db.conn.execute(
            "SELECT * FROM journeys WHERE subscription_id=?", (subscription_id,)
        ).fetchone()
        return self._to_journey(row) if row else None

    def get(self, journey_id: str) -> Journey | None:
        row = self._db.conn.execute(
            "SELECT * FROM journeys WHERE journey_id=?", (journey_id,)
        ).fetchone()
        return self._to_journey(row) if row else None

    def list_open(self, limit: int = 200) -> list[Journey]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM journeys
             WHERE state IN (?, ?, ?, ?)
             ORDER BY updated_at DESC LIMIT ?
            """,
            (
                STATE_OPENED,
                STATE_CLASSIFIED,
                STATE_INTERVENING,
                STATE_WAITING_OUTCOME,
                limit,
            ),
        ).fetchall()
        return [self._to_journey(r) for r in rows]

    def list_closed(self, limit: int = 200) -> list[Journey]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM journeys
             WHERE state IN (?, ?)
             ORDER BY updated_at DESC LIMIT ?
            """,
            (STATE_RECOVERED, STATE_CLOSED_UNRECOVERED, limit),
        ).fetchall()
        return [self._to_journey(r) for r in rows]
    def update_fields(self, journey_id: str, fields: dict[str, Any], *,
                     updated_at: str) -> None:
        """Patch allowed projection columns. Rejects unknown keys (fail fast)."""
        allowed = {
            "state",
            "failure_code",
            "root_cause",
            "classify_source",
            "amount_minor",
            "attempts_used",
            "touches_used",
            "window_started_at",
            "closed_at",
            "last_retry_at",  # PHASE 5: NPCI 18h UPI cooling
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown journey columns: {sorted(unknown)}")
        if not fields:
            return
        sets = ", ".join(f"{key}=?" for key in fields)
        params = [fields[key] for key in fields] + [updated_at, journey_id]
        self._db.conn.execute(
            f"UPDATE journeys SET {sets}, updated_at=? WHERE journey_id=?", params
        )

    def count_by_state(self) -> dict[str, int]:
        rows = self._db.conn.execute(
            "SELECT state, COUNT(*) AS c FROM journeys GROUP BY state"
        ).fetchall()
        return {r["state"]: int(r["c"]) for r in rows}

    @staticmethod
    def _to_journey(row: Any) -> Journey:
        return Journey(
            journey_id=row["journey_id"],
            subscription_id=row["subscription_id"],
            customer_id=row["customer_id"],
            state=row["state"],
            failure_code=row["failure_code"],
            root_cause=row["root_cause"],
            classify_source=row["classify_source"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            attempts_used=row["attempts_used"],
            touches_used=row["touches_used"],
            window_started_at=row["window_started_at"],
            opened_at=row["opened_at"],
            updated_at=row["updated_at"],
            closed_at=row["closed_at"],
            last_retry_at=row["last_retry_at"],
        )


def journey_to_dict(j: Journey) -> dict[str, Any]:
    return json.loads(json.dumps(j.__dict__))
