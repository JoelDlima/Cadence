"""Checkout recovery API endpoints.

Endpoints:
- POST /api/checkout/abandon — record an abandoned checkout
- POST /api/checkout/recover/{id} — mark a session recovered
- GET  /api/checkout/sessions?limit=50 — list recent sessions
- GET  /api/checkout/funnel — aggregate counts by status
- POST /api/checkout/tick — run the chaser state machine
                     across all OPEN/ABANDONED/NUDGED rows
                     (manual trigger; in LIVE mode the worker
                      runs the same call on a 30s tick)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from cadence.checkout.recovery import (
    MAX_NUDGES,
    NUDGE_T1_AFTER,
    NUDGE_T2_AFTER,
    STATUS_ABANDONED,
    STATUS_EXPIRED,
    STATUS_NUDGED,
    STATUS_OPEN,
    STATUS_RECOVERED,
    decide,
    utcnow,
)
from cadence.checkout.repo import (
    CheckoutSessionRepo,
    row_to_state_machine,
)
from cadence.store.db import Database
from cadence.clock import Clock


class AbandonRequest(BaseModel):
    customer_id: str
    subscription_id: str | None = None
    amount_minor: int = Field(gt=0)
    currency: str = "INR"
    started_at: str | None = None  # ISO; defaults to clock.now()


class RecoverRequest(BaseModel):
    payment_id: str
    recovered_at: str | None = None  # ISO; defaults to clock.now()


class SessionOut(BaseModel):
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


class TickResultOut(BaseModel):
    ran_at: str
    considered: int
    nudged: int
    abandoned: int
    recovered: int
    expired: int
    no_op: int
    decisions: list[dict[str, Any]]


def _row_to_out(row) -> SessionOut:
    return SessionOut(
        id=row.id,
        customer_id=row.customer_id,
        subscription_id=row.subscription_id,
        amount_minor=row.amount_minor,
        currency=row.currency,
        started_at=row.started_at,
        abandoned_at=row.abandoned_at,
        last_nudge_at=row.last_nudge_at,
        nudges_sent=row.nudges_sent,
        status=row.status,
        payment_link_id=row.payment_link_id,
        payment_link_short_url=row.payment_link_short_url,
        recovered_at=row.recovered_at,
        recovery_payment_id=row.recovery_payment_id,
    )


def _short_id(seed: str) -> str:
    return f"co_{hashlib.sha1(seed.encode()).hexdigest()[:10]}"


def register_routes(
    app: FastAPI,
    *,
    db: Database,
    clock: Clock,
    config: Any | None = None,
) -> None:
    repo = CheckoutSessionRepo(db)
    events = _ensure_event_store(db)

    @app.post("/api/checkout/abandon", response_model=SessionOut)
    def post_abandon(req: AbandonRequest) -> SessionOut:
        started_iso = req.started_at or clock.now().astimezone(UTC).isoformat()
        sid = _short_id(f"{req.customer_id}:{started_iso}:{uuid.uuid4()}")
        repo.insert(
            session_id=sid,
            customer_id=req.customer_id,
            subscription_id=req.subscription_id,
            amount_minor=req.amount_minor,
            currency=req.currency,
            started_at_iso=started_iso,
        )
        _emit_checkout_event(
            events, sid, "checkout.abandoned",
            {
                "customer_id": req.customer_id,
                "subscription_id": req.subscription_id,
                "amount_minor": req.amount_minor,
                "currency": req.currency,
            },
        )
        row = repo.get(sid)
        if row is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="failed to insert session")
        return _row_to_out(row)

    @app.post("/api/checkout/recover/{session_id}", response_model=SessionOut)
    def post_recover(session_id: str, req: RecoverRequest) -> SessionOut:
        row = repo.get(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="unknown session id")
        recovered_iso = req.recovered_at or clock.now().astimezone(UTC).isoformat()
        repo.update_state(
            session_id=session_id,
            new_status=STATUS_RECOVERED,
            nudges_sent=row.nudges_sent,
            last_nudge_at_iso=None,
            recovered_at_iso=recovered_iso,
            recovery_payment_id=req.payment_id,
        )
        _emit_checkout_event(
            events, session_id, "checkout.recovered",
            {"payment_id": req.payment_id, "nudges_sent": row.nudges_sent},
        )
        updated = repo.get(session_id)
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="failed to read session")
        return _row_to_out(updated)

    @app.get("/api/checkout/sessions", response_model=list[SessionOut])
    def get_sessions(limit: int = Query(50, ge=1, le=200)) -> list[SessionOut]:
        rows = repo.list_recent(limit=limit)
        return [_row_to_out(r) for r in rows]

    @app.get("/api/checkout/funnel")
    def get_funnel() -> dict[str, Any]:
        return {"counts": repo.count_by_status()}

    @app.post("/api/checkout/tick", response_model=TickResultOut)
    def post_tick() -> TickResultOut:
        """Run the chaser state machine across all open rows."""
        now = clock.now().astimezone(UTC)
        considered = nudged = abandoned = recovered = expired = no_op = 0
        decisions: list[dict[str, Any]] = []
        for row in repo.list_recent(limit=500):
            if row.status in (STATUS_RECOVERED, STATUS_EXPIRED):
                continue
            considered += 1
            sm = row_to_state_machine(row)
            d = decide(sm, now=now)
            new_nudges = sm.nudges_sent
            last_nudge_iso = row.last_nudge_at
            if d.should_nudge:
                new_nudges = sm.nudges_sent + 1
                last_nudge_iso = now.isoformat()
                if config and hasattr(config, "razorpay") and config.razorpay.is_live:
                    try:
                        from cadence.executors.razorpay_client import build_client
                        rzp_client = build_client(config.razorpay)
                        link = rzp_client.create_payment_link(
                            amount_minor=row.amount_minor,
                            currency=row.currency,
                            customer_id=row.customer_id,
                            description=f"Shopify drop-off recovery for {row.customer_id}",
                            reference_id=f"chk_{row.id}:{new_nudges}",
                        )
                        if link and "id" in link:
                            repo.record_payment_link(
                                session_id=row.id,
                                payment_link_id=link["id"],
                                short_url=link.get("short_url", ""),
                            )
                    except Exception:  # noqa: BLE001
                        pass
            repo.update_state(
                session_id=row.id,
                new_status=d.next_status,
                nudges_sent=new_nudges,
                last_nudge_at_iso=last_nudge_iso,
            )
            decisions.append({
                "session_id": row.id,
                "from_status": row.status,
                "to_status": d.next_status,
                "should_nudge": d.should_nudge,
                "include_discount": d.include_discount,
                "reason": d.reason,
            })
            if d.next_status == STATUS_ABANDONED:
                abandoned += 1
            elif d.next_status == STATUS_NUDGED:
                if d.should_nudge:
                    nudged += 1
                else:
                    no_op += 1
            elif d.next_status == STATUS_RECOVERED:
                recovered += 1
            elif d.next_status == STATUS_EXPIRED:
                expired += 1
            else:
                no_op += 1
            _emit_checkout_event(
                events, row.id, "checkout.chased",
                {
                    "from_status": row.status,
                    "to_status": d.next_status,
                    "should_nudge": d.should_nudge,
                    "include_discount": d.include_discount,
                    "reason": d.reason,
                    "nudges_sent": new_nudges,
                },
            )
        return TickResultOut(
            ran_at=now.isoformat(),
            considered=considered,
            nudged=nudged,
            abandoned=abandoned,
            recovered=recovered,
            expired=expired,
            no_op=no_op,
            decisions=decisions,
        )


def _ensure_event_store(db: Database):
    """Lazily grab the event store; defined as a tiny indirection so
    tests that mock the event store can plug in without depending on
    the full event_store import path."""
    from cadence.store.event_store import EventStore
    return EventStore(db)


def _emit_checkout_event(events, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    try:
        now = datetime.now(tz=UTC)
        events.append(
            aggregate_type="checkout_session",
            aggregate_id=session_id,
            event_type=event_type,
            payload=payload,
            occurred_at=now.isoformat(),
            recorded_at=now.isoformat(),
            event_id=str(uuid.uuid4()),
        )
    except Exception:
        # Audit chain append is best-effort for the demo; never block
        # the API on a hash-chain failure.
        return


__all__ = [
    "AbandonRequest",
    "RecoverRequest",
    "SessionOut",
    "TickResultOut",
    "register_routes",
    "NUDGE_T1_AFTER",
    "NUDGE_T2_AFTER",
    "MAX_NUDGES",
    "STATUS_OPEN",
    "STATUS_ABANDONED",
    "STATUS_NUDGED",
    "STATUS_RECOVERED",
    "STATUS_EXPIRED",
]
