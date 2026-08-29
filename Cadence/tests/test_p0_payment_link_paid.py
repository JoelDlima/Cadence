"""W2: payment_link.paid webhook must map reference_id -> journey.

A Razorpay payment_link.paid webhook does NOT carry payload.subscription
(subscriptions are not tied to a single payment link). The link itself
has a reference_id we set to "{journey_id}:{attempt_no}" when we create
the link. The gateway must parse that and look the journey up by id
(JourneyRepo.get), then use that journey's subscription_id as the
aggregate for the recovered event and capture task. Without this fix,
the recovered event lands on a dead aggregate, the capture task never
finds the journey, and the journey NEVER closes from the webhook.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from revive.clock import FakeClock
from revive.events import E_PAYMENT_RECOVERED
from revive.ingest.gateway import SIGNATURE_HEADER, create_webhook_router
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import JourneyRepo

WEBHOOK_SECRET = "s3cret"

pytestmark = [pytest.mark.integration]


def _sign(raw: bytes) -> str:
    import hashlib, hmac
    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _post_signed(client: TestClient, body: dict[str, Any]):
    raw = json.dumps(body).encode("utf-8")
    return client.post("/webhooks/razorpay", content=raw,
                       headers={SIGNATURE_HEADER: _sign(raw)})


def _plink_paid_body(*, reference_id: str, payment_id: str = "pay_PLINK1",
                     payment_link_id: str = "plink_REAL1") -> dict[str, Any]:
    return {
        "id": "evt_PLINK_PAID_1",
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": payment_link_id,
                    "reference_id": reference_id,
                    "short_url": "https://rzp.io/i/abc",
                }
            },
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 49900,
                    "currency": "INR",
                    "status": "captured",
                }
            },
        },
    }


def _seed_journey(db: Database, journey_id: str, subscription_id: str) -> None:
    from revive.clock import utc_iso
    jr = JourneyRepo(db)
    now = utc_iso(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))
    jr.create(
        journey_id=journey_id,
        subscription_id=subscription_id,
        customer_id="cust_W2",
        amount_minor=49900,
        currency="INR",
        failure_code="NO_FUNDS",
        opened_at=now,
    )


def test_payment_link_paid_uses_reference_id_to_find_journey(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """The happy path: reference_id 'j_X:1' closes journey j_X RECOVERED."""
    _seed_journey(tmp_db, journey_id="j_W2_happy", subscription_id="sub_HAPPY")
    app = FastAPI()
    app.include_router(
        create_webhook_router(db=tmp_db, webhook_secret=WEBHOOK_SECRET, clock=fake_clock)
    )
    client = TestClient(app)

    response = _post_signed(
        client, _plink_paid_body(reference_id="j_W2_happy:1", payment_id="pay_OK_W2")
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "accepted"}

    # The E_PAYMENT_RECOVERED event must land on the journey aggregate
    # (sub_HAPPY) — not the dedupe key, not a dead aggregate.
    store = EventStore(tmp_db)
    events = store.get_by_aggregate("journey", "sub_HAPPY")
    types = [e.type for e in events]
    assert E_PAYMENT_RECOVERED in types, (
        f"expected E_PAYMENT_RECOVERED on aggregate 'sub_HAPPY', got {types}"
    )


def test_payment_link_paid_with_unparseable_reference_does_not_crash(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """Malformed reference_id must fall back gracefully and not raise."""
    _seed_journey(tmp_db, journey_id="j_W2_other", subscription_id="sub_OTHER")
    app = FastAPI()
    app.include_router(
        create_webhook_router(db=tmp_db, webhook_secret=WEBHOOK_SECRET, clock=fake_clock)
    )
    client = TestClient(app)

    # No colon -> no journey id to look up. The legacy dedupe_key path
    # is used. The endpoint must still return 200 and persist a
    # payment.recovered event (somewhere), without crashing.
    response = _post_signed(
        client, _plink_paid_body(reference_id="not_a_known_format", payment_id="pay_BAD")
    )
    assert response.status_code == 200, response.text
    store = EventStore(tmp_db)
    # There must be at least one E_PAYMENT_RECOVERED event in the chain
    # — even if it lands on a different aggregate, the chain is intact.
    sink_events = store.get_by_aggregate("journey", "not_a_known_format")
    sink_recovered = [e for e in sink_events if e.type == E_PAYMENT_RECOVERED]
    # And the seed journey's chain is NOT polluted with the bad event
    # (we did not find any real journey for "not_a_known_format").
    seed_events = store.get_by_aggregate("journey", "sub_OTHER")
    seed_recovered = [e for e in seed_events if e.type == E_PAYMENT_RECOVERED]
    assert seed_recovered == [], (
        "the seed journey must not receive the recovered event when the "
        "reference is unparseable; the recovered event is supposed to "
        "land on the synthetic dedupe-key aggregate"
    )
