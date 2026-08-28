"""Checkout session repo.

A thin wrapper over the `checkout_sessions` table. The recovery
state machine lives in `revive.checkout.recovery`; this module
just reads / writes rows so the state machine stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from revive.checkout.recovery import (
    STATUS_ABANDONED,
    STATUS_EXPIRED,
    STATUS_NUDGED,
    STATUS_OPEN,
    STATUS_RECOVERED,
    CheckoutSession,
)
from revive.store.db import Database

__all__ = [
    "CheckoutSessionRow",
    "CheckoutSessionRepo",
    "STATUS_ABANDONED",
    "STATUS_EXPIRED",
    "STATUS_NUDGED",
    "STATUS_OPEN",
    "STATUS_RECOVERED",
]


@dataclass(frozen=True)
class CheckoutSessionRow:
    """The full row (audit chain may need fields the state machine does not)."""
    id: str
    customer_id: str
    subscription_id: str | None
    amount_minor: int
    currency: str
    started_at: str
    abandoned_at: str | None
    last_nudge_at: str | None
    nudges_sent: int
    status: str
    payment_link_id: str | None
    payment_link_short_url: str | None
    recovered_at: str | None
    recovery_payment_id: str | None
    notes: str


class CheckoutSessionRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(
        self,
        *,
        session_id: str,
        customer_id: str,
        subscription_id: str | None,
        amount_minor: int,
        currency: str,
        started_at_iso: str,
        notes: str = "",
    ) -> None:
        self._db.conn.execute(
            """
            INSERT INTO checkout_sessions
                (id, customer_id, subscription_id, amount_minor, currency,
                 started_at, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (session_id, customer_id, subscription_id, amount_minor,
             currency, started_at_iso, notes),
        )

    def get(self, session_id: str) -> CheckoutSessionRow | None:
        row = self._db.conn.execute(
            "SELECT * FROM checkout_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_obj(row)

    def list_recent(self, limit: int = 50) -> list[CheckoutSessionRow]:
        rows = self._db.conn.execute(
            "SELECT * FROM checkout_sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_obj(r) for r in rows]

    def update_state(
        self,
        *,
        session_id: str,
        new_status: str,
        nudges_sent: int,
        last_nudge_at_iso: str | None,
        abandoned_at_iso: str | None = None,
        recovered_at_iso: str | None = None,
        recovery_payment_id: str | None = None,
    ) -> None:
        """Apply the chaser decision to a row."""
        self._db.conn.execute(
            """
            UPDATE checkout_sessions
            SET status = ?,
                nudges_sent = ?,
                last_nudge_at = COALESCE(?, last_nudge_at),
                abandoned_at = COALESCE(?, abandoned_at),
                recovered_at = COALESCE(?, recovered_at),
                recovery_payment_id = COALESCE(?, recovery_payment_id)
            WHERE id = ?
            """,
            (new_status, nudges_sent, last_nudge_at_iso, abandoned_at_iso,
             recovered_at_iso, recovery_payment_id, session_id),
        )

    def record_payment_link(
        self, *, session_id: str, payment_link_id: str, short_url: str
    ) -> None:
        self._db.conn.execute(
            """
            UPDATE checkout_sessions
            SET payment_link_id = ?, payment_link_short_url = ?
            WHERE id = ?
            """,
            (payment_link_id, short_url, session_id),
        )

    def count_by_status(self) -> dict[str, int]:
        rows = self._db.conn.execute(
            "SELECT status, COUNT(*) AS c FROM checkout_sessions GROUP BY status"
        ).fetchall()
        return {str(r["status"]): int(r["c"]) for r in rows}


def _row_to_obj(row) -> CheckoutSessionRow:
    return CheckoutSessionRow(
        id=str(row["id"]),
        customer_id=str(row["customer_id"]),
        subscription_id=row["subscription_id"],
        amount_minor=int(row["amount_minor"]),
        currency=str(row["currency"]),
        started_at=str(row["started_at"]),
        abandoned_at=row["abandoned_at"],
        last_nudge_at=row["last_nudge_at"],
        nudges_sent=int(row["nudges_sent"]),
        status=str(row["status"]),
        payment_link_id=row["payment_link_id"],
        payment_link_short_url=row["payment_link_short_url"],
        recovered_at=row["recovered_at"],
        recovery_payment_id=row["recovery_payment_id"],
        notes=str(row["notes"]),
    )


def row_to_state_machine(row: CheckoutSessionRow) -> CheckoutSession:
    """Project a row into the state machine input shape."""
    return CheckoutSession(
        id=row.id,
        customer_id=row.customer_id,
        amount_minor=row.amount_minor,
        status=row.status,
        started_at=_parse_iso(row.started_at),
        abandoned_at=_parse_iso(row.abandoned_at) if row.abandoned_at else None,
        last_nudge_at=_parse_iso(row.last_nudge_at) if row.last_nudge_at else None,
        nudges_sent=row.nudges_sent,
    )


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string back to a datetime (UTC)."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
