"""Razorpay webhook ingest gateway (Phase B1).

Flow per delivery: HMAC-SHA256 verify over the RAW body -> parse JSON ->
ignore unknown event types -> claim dedupe key (exactly-once processing) ->
append ``webhook.received`` -> append domain events -> enqueue durable task
for the journey engine. The gateway never opens journeys itself; that is the
engine's job when it claims the task.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from revive.clock import Clock, utc_iso
from revive.events import (
    AGG_JOURNEY,
    AGG_WEBHOOK,
    E_PAYMENT_FAILED,
    E_PAYMENT_RECOVERED,
    E_WEBHOOK_RECEIVED,
)
from revive.ingest.signature import verify_signature
from revive.logging_setup import get_logger
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.queue_repo import QueueRepo

ACCEPTED_EVENTS: frozenset[str] = frozenset(
    {
        "subscription.pending",
        "subscription.halted",
        "payment.failed",
        "payment.captured",
    }
)
FAILURE_EVENTS: frozenset[str] = frozenset(
    {"subscription.pending", "subscription.halted", "payment.failed"}
)

EVENT_ID_HEADER = "X-Razorpay-Event-Id"
SIGNATURE_HEADER = "X-Razorpay-Signature"
TASK_HANDLE_PAYMENT_FAILED = "handle_payment_failed"
TASK_PAYMENT_CAPTURED = "payment_captured"

log = get_logger("revive.ingest.gateway")


def _parse_json_object(raw: bytes) -> dict[str, Any] | None:
    """Parse raw bytes into a JSON object; None when malformed or not an object."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _dedupe_key_for(
    *, body: dict[str, Any], raw: bytes, event_id_header: str | None = None
) -> str:
    """Dedupe priority: Razorpay's `X-Razorpay-Event-Id` header (their documented
    duplicate marker) -> body delivery id -> sha256 of the raw body."""
    if event_id_header:
        return f"evt:{event_id_header}"
    provider_id = body.get("id")
    if provider_id:
        return str(provider_id)
    return hashlib.sha256(raw).hexdigest()


def _claim_first_delivery(db: Database, *, dedupe_key: str, seen_at: str) -> bool:
    """Insert the dedupe row; False means this delivery was already processed."""
    try:
        db.conn.execute(
            "INSERT INTO webhook_dedupe (dedupe_key, first_seen_at) VALUES (?, ?)",
            (dedupe_key, seen_at),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def _extract_entities(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pull ``(subscription.entity, payment.entity)``; any missing level yields {}."""
    payload = body.get("payload")
    payload_map = payload if isinstance(payload, dict) else {}
    subscription = payload_map.get("subscription")
    payment = payload_map.get("payment")
    sub_entity = subscription.get("entity") if isinstance(subscription, dict) else {}
    pay_entity = payment.get("entity") if isinstance(payment, dict) else {}
    sub_out = sub_entity if isinstance(sub_entity, dict) else {}
    pay_out = pay_entity if isinstance(pay_entity, dict) else {}
    return sub_out, pay_out


def _append_webhook_received(
    store: EventStore,
    *,
    dedupe_key: str,
    event_name: str,
    now_iso: str,
) -> None:
    store.append(
        event_type=E_WEBHOOK_RECEIVED,
        aggregate_type=AGG_WEBHOOK,
        aggregate_id=dedupe_key,
        payload={"event": event_name},
        occurred_at=now_iso,
        recorded_at=now_iso,
        event_id=f"wh_{uuid.uuid4().hex}",
    )


def _append_payment_failed(
    *,
    store: EventStore,
    sub: dict[str, Any],
    pay: dict[str, Any],
    subscription_id: str,
    now_iso: str,
) -> None:
    store.append(
        event_type=E_PAYMENT_FAILED,
        aggregate_type=AGG_JOURNEY,
        aggregate_id=subscription_id,
        payload={
            "failure_code": pay.get("error_code"),
            "error_description": pay.get("error_description"),
            "amount_minor": pay.get("amount"),
            "currency": pay.get("currency", "INR"),
            "customer_id": sub.get("customer_id") or pay.get("customer_id") or "unknown",
            "payment_id": pay.get("id"),
        },
        occurred_at=now_iso,
        recorded_at=now_iso,
        event_id=f"pf_{uuid.uuid4().hex}",
    )


def _enqueue_failure_task(
    *,
    queue: QueueRepo,
    pay: dict[str, Any],
    subscription_id: str,
    dedupe_key: str,
    now_iso: str,
) -> None:
    """Enqueue engine work keyed on payment id so Razorpay replays cannot double-run."""
    payment_id = pay.get("id")
    queue.enqueue(
        task_type=TASK_HANDLE_PAYMENT_FAILED,
        payload={"subscription_id": subscription_id, "payment_id": payment_id},
        idempotency_key=f"{TASK_HANDLE_PAYMENT_FAILED}:{payment_id or dedupe_key}",
        available_at=now_iso,
        created_at=now_iso,
    )


def _append_payment_recovered(
    *,
    store: EventStore,
    pay: dict[str, Any],
    subscription_id: str,
    now_iso: str,
) -> None:
    store.append(
        event_type=E_PAYMENT_RECOVERED,
        aggregate_type=AGG_JOURNEY,
        aggregate_id=subscription_id,
        payload={"payment_id": pay.get("id"), "amount_minor": pay.get("amount")},
        occurred_at=now_iso,
        recorded_at=now_iso,
        event_id=f"pr_{uuid.uuid4().hex}",
    )


def _enqueue_capture_task(
    *,
    queue: QueueRepo,
    pay: dict[str, Any],
    subscription_id: str,
    dedupe_key: str,
    now_iso: str,
) -> None:
    """Queue the journeys-projection update for a captured payment."""
    payment_id = pay.get("id")
    queue.enqueue(
        task_type=TASK_PAYMENT_CAPTURED,
        payload={"subscription_id": subscription_id, "payment_id": payment_id},
        idempotency_key=f"{TASK_PAYMENT_CAPTURED}:{payment_id or dedupe_key}",
        available_at=now_iso,
        created_at=now_iso,
    )


def process_delivery(
    *,
    db: Database,
    webhook_secret: str,
    clock: Clock,
    raw: bytes,
    signature: str | None,
    event_id: str | None = None,
) -> tuple[int, dict[str, str]]:
    """One webhook delivery, verified and applied. Shared by the HTTP route and
    the Supabase-inbox drain so both paths run identical logic.

    Returns ``(http_status, json_body)``.
    """
    if not verify_signature(raw_body=raw, signature_header=signature, secret=webhook_secret):
        log.warning("rejected webhook: bad signature (%d bytes)", len(raw))
        return 401, {"detail": "bad signature"}
    body = _parse_json_object(raw)
    if body is None:
        log.warning("rejected webhook: malformed json (%d bytes)", len(raw))
        return 400, {"detail": "malformed json"}
    event_name = body.get("event")
    if not isinstance(event_name, str) or event_name not in ACCEPTED_EVENTS:
        return 200, {"status": "ignored"}
    store = EventStore(db)
    queue = QueueRepo(db)
    now_iso = utc_iso(clock.now())
    dedupe_key = _dedupe_key_for(body=body, raw=raw, event_id_header=event_id)
    if not _claim_first_delivery(db, dedupe_key=dedupe_key, seen_at=now_iso):
        log.info("duplicate webhook delivery suppressed: %s", dedupe_key)
        return 200, {"status": "duplicate"}
    _append_webhook_received(
        store, dedupe_key=dedupe_key, event_name=event_name, now_iso=now_iso
    )
    sub, pay = _extract_entities(body)
    subscription_id = str(sub.get("id") or pay.get("order_id") or dedupe_key)
    if event_name in FAILURE_EVENTS:
        _append_payment_failed(
            store=store, sub=sub, pay=pay, subscription_id=subscription_id, now_iso=now_iso
        )
        _enqueue_failure_task(
            queue=queue,
            pay=pay,
            subscription_id=subscription_id,
            dedupe_key=dedupe_key,
            now_iso=now_iso,
        )
    elif event_name == "payment.captured":
        _append_payment_recovered(
            store=store, pay=pay, subscription_id=subscription_id, now_iso=now_iso
        )
        _enqueue_capture_task(
            queue=queue,
            pay=pay,
            subscription_id=subscription_id,
            dedupe_key=dedupe_key,
            now_iso=now_iso,
        )
    elif event_name == "payment_link.paid":
        # PHASE 8: customer paid the Razorpay Payment Link. Same
        # close path as payment.captured -- write the recovered
        # event and enqueue the update task. The 20s first
        # outcome check (PHASE 8) then sees the closed journey
        # on the very next worker tick.
        _append_payment_recovered(
            store=store, pay=pay, subscription_id=subscription_id, now_iso=now_iso
        )
        _enqueue_capture_task(
            queue=queue,
            pay=pay,
            subscription_id=subscription_id,
            dedupe_key=dedupe_key,
            now_iso=now_iso,
        )
    return 200, {"status": "accepted"}


def create_webhook_router(*, db: Database, webhook_secret: str, clock: Clock) -> APIRouter:
    """Build a router bound to concrete db/secret/clock dependencies (testable)."""
    router = APIRouter()

    @router.post("/webhooks/razorpay")
    async def receive_razorpay_webhook(request: Request) -> Response:
        raw = await request.body()
        status, body = process_delivery(
            db=db,
            webhook_secret=webhook_secret,
            clock=clock,
            raw=raw,
            signature=request.headers.get(SIGNATURE_HEADER),
            event_id=request.headers.get(EVENT_ID_HEADER),
        )
        return JSONResponse(status_code=status, content=body)

    return router
