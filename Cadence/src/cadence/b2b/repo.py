"""B2B invoice and org repo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cadence.b2b.chaser import Invoice, STATUS_ISSUED
from cadence.store.db import Database

__all__ = [
    "B2BInvoiceRow",
    "B2BOrgRow",
    "B2BRepo",
    "row_to_chaser_input",
]


@dataclass(frozen=True)
class B2BInvoiceRow:
    id: str
    invoice_number: str | None
    org_id: str
    contact_id: str | None
    contact_email: str | None
    contact_phone: str | None
    amount_minor: int
    currency: str
    issued_at: str
    due_date: str
    paid_at: str | None
    status: str
    chases_sent: int
    last_chase_at: str | None
    last_chase_action: str | None
    escalated_to_manager: int
    writeoff_at: str | None
    notes: str


@dataclass(frozen=True)
class B2BOrgRow:
    id: str
    name: str
    contact_email: str | None
    contact_phone: str | None
    notes: str


class B2BRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- orgs ---

    def insert_org(self, *, org_id: str, name: str, contact_email: str | None,
                   contact_phone: str | None, notes: str = "") -> None:
        self._db.conn.execute(
            """
            INSERT INTO b2b_orgs (id, name, contact_email, contact_phone, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (org_id, name, contact_email, contact_phone, notes),
        )

    def get_org(self, org_id: str) -> B2BOrgRow | None:
        row = self._db.conn.execute(
            "SELECT * FROM b2b_orgs WHERE id = ?", (org_id,)
        ).fetchone()
        if row is None:
            return None
        return B2BOrgRow(
            id=str(row["id"]),
            name=str(row["name"]),
            contact_email=row["contact_email"],
            contact_phone=row["contact_phone"],
            notes=str(row["notes"]),
        )

    def list_orgs(self) -> list[B2BOrgRow]:
        rows = self._db.conn.execute(
            "SELECT * FROM b2b_orgs ORDER BY name"
        ).fetchall()
        return [B2BOrgRow(
            id=str(r["id"]), name=str(r["name"]),
            contact_email=r["contact_email"], contact_phone=r["contact_phone"],
            notes=str(r["notes"]),
        ) for r in rows]

    # --- invoices ---

    def insert_invoice(
        self,
        *,
        invoice_id: str,
        invoice_number: str | None,
        org_id: str,
        contact_id: str | None,
        contact_email: str | None,
        contact_phone: str | None,
        amount_minor: int,
        currency: str,
        issued_at_iso: str,
        due_date_iso: str,
        status: str = STATUS_ISSUED,
        notes: str = "",
    ) -> None:
        self._db.conn.execute(
            """
            INSERT INTO b2b_invoices
                (id, invoice_number, org_id, contact_id, contact_email,
                 contact_phone, amount_minor, currency, issued_at, due_date,
                 status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (invoice_id, invoice_number, org_id, contact_id, contact_email,
             contact_phone, amount_minor, currency, issued_at_iso, due_date_iso,
             status, notes),
        )

    def get_invoice(self, invoice_id: str) -> B2BInvoiceRow | None:
        row = self._db.conn.execute(
            "SELECT * FROM b2b_invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_invoice(row)

    def list_invoices(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[B2BInvoiceRow]:
        if status:
            rows = self._db.conn.execute(
                "SELECT * FROM b2b_invoices WHERE status = ? "
                "ORDER BY due_date ASC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._db.conn.execute(
                "SELECT * FROM b2b_invoices ORDER BY due_date ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_invoice(r) for r in rows]

    def list_overdue(self, *, now_iso: str, limit: int = 50) -> list[B2BInvoiceRow]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM b2b_invoices
            WHERE status = 'issued' AND due_date < ?
            ORDER BY due_date ASC LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [_row_to_invoice(r) for r in rows]

    def record_chase(
        self,
        *,
        invoice_id: str,
        chases_sent: int,
        last_chase_at_iso: str,
        last_chase_action: str,
        escalated_to_manager: int,
        writeoff_at_iso: str | None,
    ) -> None:
        self._db.conn.execute(
            """
            UPDATE b2b_invoices
            SET chases_sent = ?,
                last_chase_at = ?,
                last_chase_action = ?,
                escalated_to_manager = ?,
                writeoff_at = COALESCE(?, writeoff_at)
            WHERE id = ?
            """,
            (chases_sent, last_chase_at_iso, last_chase_action,
             escalated_to_manager, writeoff_at_iso, invoice_id),
        )

    def mark_paid(self, *, invoice_id: str, paid_at_iso: str) -> None:
        self._db.conn.execute(
            """
            UPDATE b2b_invoices
            SET status = 'paid', paid_at = ?
            WHERE id = ?
            """,
            (paid_at_iso, invoice_id),
        )

    def count_by_status(self) -> dict[str, int]:
        rows = self._db.conn.execute(
            "SELECT status, COUNT(*) AS c FROM b2b_invoices GROUP BY status"
        ).fetchall()
        return {str(r["status"]): int(r["c"]) for r in rows}


def _row_to_invoice(row) -> B2BInvoiceRow:
    return B2BInvoiceRow(
        id=str(row["id"]),
        invoice_number=row["invoice_number"],
        org_id=str(row["org_id"]),
        contact_id=row["contact_id"],
        contact_email=row["contact_email"],
        contact_phone=row["contact_phone"],
        amount_minor=int(row["amount_minor"]),
        currency=str(row["currency"]),
        issued_at=str(row["issued_at"]),
        due_date=str(row["due_date"]),
        paid_at=row["paid_at"],
        status=str(row["status"]),
        chases_sent=int(row["chases_sent"]),
        last_chase_at=row["last_chase_at"],
        last_chase_action=row["last_chase_action"],
        escalated_to_manager=int(row["escalated_to_manager"]),
        writeoff_at=row["writeoff_at"],
        notes=str(row["notes"]),
    )


def row_to_chaser_input(row: B2BInvoiceRow) -> Invoice:
    """Project a row into the chaser input shape."""
    return Invoice(
        id=row.id,
        org_id=row.org_id,
        amount_minor=row.amount_minor,
        due_date=_parse_iso(row.due_date),
        status=row.status,
        chases_sent=row.chases_sent,
        last_chase_at=_parse_iso(row.last_chase_at) if row.last_chase_at else None,
    )


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
