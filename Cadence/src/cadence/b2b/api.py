"""B2B receivables chaser API endpoints.

Endpoints:
- POST /api/b2b/invoice/create   — seed a new invoice
- GET  /api/b2b/invoices?status=  — list invoices (filter by status)
- GET  /api/b2b/invoices/overdue  — list overdue invoices
- POST /api/b2b/invoice/{id}/chase — manual trigger
- GET  /api/b2b/funnel            — count by status
- POST /api/b2b/tick              — run the chaser across all open rows
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from cadence.b2b.chaser import (
    ACTION_MANAGER,
    ACTION_WRITEOFF,
    STATUS_ISSUED,
    decide,
)
from cadence.b2b.repo import B2BRepo, row_to_chaser_input
from cadence.clock import Clock
from cadence.store.db import Database


class CreateInvoiceRequest(BaseModel):
    invoice_number: str | None = None
    org_id: str
    contact_id: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    amount_minor: int = Field(gt=0)
    currency: str = "INR"
    issued_at: str | None = None
    due_date: str | None = None
    notes: str = ""


class InvoiceOut(BaseModel):
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


class ChaseResultOut(BaseModel):
    ran_at: str
    considered: int
    chased: int
    manager_escalations: int
    writeoffs: int
    no_op: int
    decisions: list[dict[str, Any]]


def _row_to_out(row) -> InvoiceOut:
    return InvoiceOut(
        id=row.id,
        invoice_number=row.invoice_number,
        org_id=row.org_id,
        contact_id=row.contact_id,
        contact_email=row.contact_email,
        contact_phone=row.contact_phone,
        amount_minor=row.amount_minor,
        currency=row.currency,
        issued_at=row.issued_at,
        due_date=row.due_date,
        paid_at=row.paid_at,
        status=row.status,
        chases_sent=row.chases_sent,
        last_chase_at=row.last_chase_at,
        last_chase_action=row.last_chase_action,
        escalated_to_manager=row.escalated_to_manager,
        writeoff_at=row.writeoff_at,
    )


def _short_id(seed: str) -> str:
    return f"inv_{hashlib.sha1(seed.encode()).hexdigest()[:10]}"


def register_routes(app: FastAPI, *, db: Database, clock: Clock) -> None:
    repo = B2BRepo(db)
    events = _ensure_event_store(db)

    @app.post("/api/b2b/invoice/create", response_model=InvoiceOut)
    def post_create_invoice(req: CreateInvoiceRequest) -> InvoiceOut:
        now_iso = clock.now().astimezone(UTC).isoformat()
        issued_iso = req.issued_at or now_iso
        # Default due date = +30 days if not given
        if req.due_date:
            due_iso = req.due_date
        else:
            due_iso = (clock.now().astimezone(UTC) + _30_DAYS).isoformat()
        iid = _short_id(f"{req.org_id}:{issued_iso}:{uuid.uuid4()}")
        repo.insert_invoice(
            invoice_id=iid,
            invoice_number=req.invoice_number,
            org_id=req.org_id,
            contact_id=req.contact_id,
            contact_email=req.contact_email,
            contact_phone=req.contact_phone,
            amount_minor=req.amount_minor,
            currency=req.currency,
            issued_at_iso=issued_iso,
            due_date_iso=due_iso,
            status=STATUS_ISSUED,
            notes=req.notes,
        )
        _emit(events, iid, "b2b.invoice.created", {
            "org_id": req.org_id,
            "amount_minor": req.amount_minor,
            "due_date": due_iso,
        })
        row = repo.get_invoice(iid)
        if row is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="insert failed")
        return _row_to_out(row)

    @app.get("/api/b2b/invoices", response_model=list[InvoiceOut])
    def get_invoices(
        status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
    ) -> list[InvoiceOut]:
        rows = repo.list_invoices(status=status, limit=limit)
        return [_row_to_out(r) for r in rows]

    @app.get("/api/b2b/invoices/overdue", response_model=list[InvoiceOut])
    def get_overdue(limit: int = Query(50, ge=1, le=200)) -> list[InvoiceOut]:
        now_iso = clock.now().astimezone(UTC).isoformat()
        rows = repo.list_overdue(now_iso=now_iso, limit=limit)
        return [_row_to_out(r) for r in rows]

    @app.post("/api/b2b/invoice/{invoice_id}/chase", response_model=InvoiceOut)
    def post_chase(invoice_id: str) -> InvoiceOut:
        row = repo.get_invoice(invoice_id)
        if row is None:
            raise HTTPException(status_code=404, detail="unknown invoice")
        sm = row_to_chaser_input(row)
        now = clock.now().astimezone(UTC)
        d = decide(sm, now=now)
        new_chases = sm.chases_sent + (1 if d.should_chase else 0)
        escalated = 1 if d.action == ACTION_MANAGER else row.escalated_to_manager
        writeoff_iso = now.isoformat() if d.action == ACTION_WRITEOFF else None
        last_chase_iso = now.isoformat() if d.should_chase else row.last_chase_at
        repo.record_chase(
            invoice_id=invoice_id,
            chases_sent=new_chases,
            last_chase_at_iso=last_chase_iso or now.isoformat(),
            last_chase_action=d.action,
            escalated_to_manager=escalated,
            writeoff_at_iso=writeoff_iso,
        )
        _emit(events, invoice_id, "b2b.invoice.chased", {
            "action": d.action,
            "channel": d.channel,
            "recipient": d.recipient,
            "days_past_due": d.days_past_due,
            "reason": d.reason,
            "chases_sent": new_chases,
        })
        updated = repo.get_invoice(invoice_id)
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="read failed")
        return _row_to_out(updated)

    @app.get("/api/b2b/funnel")
    def get_funnel() -> dict[str, Any]:
        return {"counts": repo.count_by_status()}

    @app.post("/api/b2b/tick", response_model=ChaseResultOut)
    def post_tick() -> ChaseResultOut:
        now = clock.now().astimezone(UTC)
        now_iso = now.isoformat()
        rows = repo.list_overdue(now_iso=now_iso, limit=500)
        considered = chased = manager = writeoff = no_op = 0
        decisions: list[dict[str, Any]] = []
        for row in rows:
            considered += 1
            sm = row_to_chaser_input(row)
            d = decide(sm, now=now)
            if not d.should_chase:
                no_op += 1
                continue
            new_chases = sm.chases_sent + 1
            escalated = 1 if d.action == ACTION_MANAGER else row.escalated_to_manager
            writeoff_iso = now_iso if d.action == ACTION_WRITEOFF else None
            repo.record_chase(
                invoice_id=row.id,
                chases_sent=new_chases,
                last_chase_at_iso=now_iso,
                last_chase_action=d.action,
                escalated_to_manager=escalated,
                writeoff_at_iso=writeoff_iso,
            )
            decisions.append({
                "invoice_id": row.id,
                "org_id": row.org_id,
                "action": d.action,
                "channel": d.channel,
                "recipient": d.recipient,
                "days_past_due": d.days_past_due,
                "chases_sent": new_chases,
                "reason": d.reason,
            })
            chased += 1
            if d.action == ACTION_MANAGER:
                manager += 1
            if d.action == ACTION_WRITEOFF:
                writeoff += 1
            _emit(events, row.id, "b2b.invoice.chased", {
                "action": d.action,
                "channel": d.channel,
                "recipient": d.recipient,
                "days_past_due": d.days_past_due,
                "reason": d.reason,
                "chases_sent": new_chases,
            })
        return ChaseResultOut(
            ran_at=now_iso,
            considered=considered,
            chased=chased,
            manager_escalations=manager,
            writeoffs=writeoff,
            no_op=no_op,
            decisions=decisions,
        )


_30_DAYS = None  # type: ignore[assignment]


def _ensure_event_store(db: Database):
    from cadence.store.event_store import EventStore
    return EventStore(db)


def _emit(events, invoice_id: str, event_type: str, payload: dict[str, Any]) -> None:
    try:
        now = datetime.now(tz=UTC)
        events.append(
            aggregate_type="b2b_invoice",
            aggregate_id=invoice_id,
            event_type=event_type,
            payload=payload,
            occurred_at=now.isoformat(),
            recorded_at=now.isoformat(),
            event_id=str(uuid.uuid4()),
        )
    except Exception:
        return


# Set the constant here (after the function definitions so it
# doesn't get imported as a global by mistake).
import datetime as _dt
_30_DAYS = _dt.timedelta(days=30)


__all__ = [
    "ChaseResultOut",
    "CreateInvoiceRequest",
    "InvoiceOut",
    "register_routes",
]
