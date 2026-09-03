"""Slice tests for the Razorpay webhook ingest gateway (plan item B1)."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from cadence.clock import FakeClock
from cadence.events import (
    AGG_JOURNEY,
    AGG_WEBHOOK,
    E_PAYMENT_FAILED,
    E_PAYMENT_RECOVERED,
    E_WEBHOOK_RECEIVED,
)
from cadence.ingest.gateway import SIGNATURE_HEADER, create_webhook_router
from cadence.store.db import Database
from cadence.store.event_store import EventStore

WEBHOOK_SECRET = "s3cret"

pytestmark = [pytest.mark.integration]


def _build_client(db: Database, clock: FakeClock) -> TestClient:
    app = FastAPI()
    app.include_router(create_webhook_router(db=db, webhook_secret=WEBHOOK_SECRET, clock=clock))
    return TestClient(app)


def _sign(raw: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _post_signed(client: TestClient, body: dict[str, Any]) -> Response:
    raw = json.dumps(body).encode("utf-8")
    return _post_raw_signed(client, raw)


def _post_raw_signed(client: TestClient, raw: bytes) -> Response:
    headers = {SIGNATURE_HEADER: _sign(raw)}
    return client.post("/webhooks/razorpay", content=raw, headers=headers)


def _pending_body(payment_id: str = "pay_TEST123") -> dict[str, Any]:
    return {
        "id": "evt_PENDING_1",
        "event": "subscription.pending",
        "payload": {
            "subscription": {"entity": {"id": "sub_TEST1", "customer_id": "cust_1"}},
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": "order_TEST9",
                    "amount": 49900,
                    "currency": "INR",
                    "error_code": "insufficient_funds",
                    "error_description": "Insufficient funds in bank account",
                }
            },
        },
    }


def _captured_body() -> dict[str, Any]:
    return {
        "id": "evt_CAP_1",
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": "pay_OK1", "order_id": "order_OK1", "amount": 49900}}
        },
    }


def _queued_rows(db: Database) -> list[sqlite3.Row]:
    return db.conn.execute("SELECT * FROM task_queue ORDER BY task_id").fetchall()


def test_bad_signature_is_401_and_writes_nothing(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    client = _build_client(tmp_db, fake_clock)

    bad_headers = {SIGNATURE_HEADER: "00" * 32}
    garbage = client.post("/webhooks/razorpay", content=b"{}", headers=bad_headers)
    missing = client.post("/webhooks/razorpay", content=b"{}")

    assert garbage.status_code == 401
    assert garbage.json() == {"detail": "bad signature"}
    assert missing.status_code == 401
    assert EventStore(tmp_db).count() == 0
    assert len(_queued_rows(tmp_db)) == 0


def test_subscription_pending_records_failure_enqueues_task_keeps_journeys_empty(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    client = _build_client(tmp_db, fake_clock)
    store = EventStore(tmp_db)

    response = _post_signed(client, _pending_body())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    received = store.get_by_type(E_WEBHOOK_RECEIVED)
    failed = store.get_by_type(E_PAYMENT_FAILED)
    # webhook.received + payment.failed must both be in the log (nothing else writes).
    assert store.count() >= 2
    assert len(received) == 1
    assert received[0].aggregate_type == AGG_WEBHOOK
    assert received[0].aggregate_id == "evt_PENDING_1"
    assert received[0].payload == {"event": "subscription.pending"}
    assert len(failed) == 1
    assert failed[0].aggregate_type == AGG_JOURNEY
    assert failed[0].aggregate_id == "sub_TEST1"
    assert failed[0].payload["failure_code"] == "insufficient_funds"
    assert failed[0].payload["amount_minor"] == 49900
    assert failed[0].payload["customer_id"] == "cust_1"

    tasks = _queued_rows(tmp_db)
    assert len(tasks) == 1
    assert tasks[0]["task_type"] == "handle_payment_failed"
    assert tasks[0]["idempotency_key"] == "handle_payment_failed:pay_TEST123"
    assert json.loads(tasks[0]["payload"]) == {
        "subscription_id": "sub_TEST1",
        "payment_id": "pay_TEST123",
    }

    journeys = tmp_db.conn.execute("SELECT COUNT(*) AS c FROM journeys").fetchone()
    assert journeys["c"] == 0


def test_replayed_delivery_is_duplicate_with_no_new_writes(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    client = _build_client(tmp_db, fake_clock)
    store = EventStore(tmp_db)
    body = _pending_body()

    first = _post_signed(client, body)
    assert first.json() == {"status": "accepted"}
    events_before = store.count()
    tasks_before = len(_queued_rows(tmp_db))
    dedupe_before = tmp_db.conn.execute("SELECT COUNT(*) AS c FROM webhook_dedupe").fetchone()["c"]

    replay = _post_signed(client, body)

    assert replay.status_code == 200
    assert replay.json() == {"status": "duplicate"}
    assert store.count() == events_before
    assert len(_queued_rows(tmp_db)) == tasks_before
    dedupe_after = tmp_db.conn.execute("SELECT COUNT(*) AS c FROM webhook_dedupe").fetchone()["c"]
    assert dedupe_after == dedupe_before == 1


def test_payment_captured_appends_recovered_and_enqueues_projection_task(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    client = _build_client(tmp_db, fake_clock)
    store = EventStore(tmp_db)

    response = _post_signed(client, _captured_body())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    recovered = store.get_by_type(E_PAYMENT_RECOVERED)
    assert len(recovered) == 1
    assert recovered[0].aggregate_type == AGG_JOURNEY
    assert recovered[0].aggregate_id == "order_OK1"
    assert recovered[0].payload == {"payment_id": "pay_OK1", "amount_minor": 49900}
    assert store.get_by_type(E_PAYMENT_FAILED) == []
    rows = _queued_rows(tmp_db)
    assert len(rows) == 1
    assert rows[0]["task_type"] == "payment_captured"
    assert json.loads(rows[0]["payload"]) == {
        "subscription_id": "order_OK1",
        "payment_id": "pay_OK1",
    }


def test_unknown_event_is_ignored_with_zero_side_effects(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    client = _build_client(tmp_db, fake_clock)
    store = EventStore(tmp_db)
    body = {"id": "evt_PAUSED_1", "event": "subscription.paused", "payload": {}}

    response = _post_signed(client, body)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert store.count() == 0
    assert len(_queued_rows(tmp_db)) == 0
    dedupe = tmp_db.conn.execute("SELECT COUNT(*) AS c FROM webhook_dedupe").fetchone()
    assert dedupe["c"] == 0


def test_malformed_json_with_valid_signature_is_400(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    client = _build_client(tmp_db, fake_clock)

    response = _post_raw_signed(client, b'{"event": "payment.captured", "payload": {oops')

    assert response.status_code == 400
    assert response.json() == {"detail": "malformed json"}
    assert EventStore(tmp_db).count() == 0
