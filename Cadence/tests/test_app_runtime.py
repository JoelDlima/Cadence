"""Served-app autonomy: a posted webhook is fully processed by the app's own
runtime (engine + dispatcher handlers) - no companion script required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.test_api import _config

from revive.api.app import create_app
from revive.store.journey_repo import STATE_INTERVENING, JourneyRepo

pytestmark = [pytest.mark.integration]

_SECRET = "s3cret"


def _sign(raw: bytes) -> str:
    return hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def _failure_body() -> dict:
    return {
        "id": "evt_RT1",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RT1",
                    "order_id": "order_RT1",
                    "amount": 49900,
                    "currency": "INR",
                    "error_code": "insufficient_funds",
                    "error_description": "insufficient balance",
                    "customer_id": "cust_RT1",
                }
            }
        },
    }


def test_webhook_then_runtime_tick_opens_and_advances_journey(tmp_path: Path) -> None:
    db_path = tmp_path / "rt.db"
    app = create_app(cfg=_config(db_path))
    client = TestClient(app)

    raw = json.dumps(_failure_body()).encode()
    response = client.post(
        "/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": _sign(raw)}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    # TestClient without a context manager never starts the lifespan thread;
    # tick the exposed runtime once - exactly what the background loop does.
    runtime = app.state.runtime
    runtime.worker.run_once(runtime.handlers)

    journeys = JourneyRepo(runtime.db)
    journey = journeys.get_by_subscription("order_RT1")
    assert journey is not None
    assert journey.amount_minor == 49900  # rehydrated, not lost
    assert journey.state == STATE_INTERVENING
    assert journey.root_cause == "NO_FUNDS"


def test_runtime_handlers_cover_the_full_task_surface(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "rt2.db"))

    handlers = app.state.runtime.handlers

    assert set(handlers) == {
        "execute_intervention",
        "handle_payment_failed",
        "payment_captured",
        "outcome_check",
        "await_customer_reply",
    }
