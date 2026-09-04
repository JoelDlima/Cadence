"""Promise-to-pay tracker: simulated inbound reply + projection endpoint.

No Resend inbound webhook is configured (no verified domain with Inbound
enabled), so these tests exercise the same production parser/dispatcher path
through a Cadence-only "simulate customer reply" trigger. The parsing, event
emission, and retry scheduling are real; only the entry point is simulated.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from tests.test_p1_lifecycle_routes import _config

pytestmark = [pytest.mark.integration]


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(cfg=_config(tmp_path)))


def _open_journey(client: TestClient) -> dict:
    customer = client.post("/api/live/customer", json={
        "name": "PTP Test", "email": "ptp@x.local", "contact": "+919999900002",
    })
    assert customer.status_code == 200, customer.text
    failure = client.post("/api/live/failure", json={"customer_id": customer.json()["id"]})
    assert failure.status_code == 200, failure.text
    return failure.json()


def test_simulated_reply_with_a_date_commits_a_promise(tmp_path) -> None:
    client = _client(tmp_path)
    opened = _open_journey(client)
    journey_id = opened["journey_id"]

    resp = client.post("/api/promises/simulate-reply", json={
        "reference_id": f"{journey_id}:1",
        "text": "25 tarikh ko paisa bhej dunga",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert body["kind"] == "date"
    assert body["commit_date"]

    events = client.get(f"/api/journeys/{journey_id}/timeline").json()["events"]
    event_types = {e["type"] for e in events}
    assert "customer.replied" in event_types
    assert "ptp.committed" in event_types
    assert client.get("/api/audit/verify").json()["chain_ok"] is True

    listing = client.get("/api/promises").json()
    assert listing["open_count"] >= 1
    row = next(r for r in listing["promises"] if r["journey_id"] == journey_id)
    assert row["kind"] == "date"
    assert row["status"] == "open"
    assert row["reply_text"] == "25 tarikh ko paisa bhej dunga"


def test_simulated_refusal_closes_the_journey(tmp_path) -> None:
    client = _client(tmp_path)
    opened = _open_journey(client)
    journey_id = opened["journey_id"]

    resp = client.post("/api/promises/simulate-reply", json={
        "reference_id": f"{journey_id}:1",
        "text": "please cancel, do not charge me again",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "refusal"

    journey = client.get(f"/api/journey/{journey_id}").json()
    assert journey["state"] == "CLOSED_UNRECOVERED"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


def test_unparseable_reply_is_committed_with_no_promised_date(tmp_path) -> None:
    client = _client(tmp_path)
    opened = _open_journey(client)
    journey_id = opened["journey_id"]

    resp = client.post("/api/promises/simulate-reply", json={
        "reference_id": f"{journey_id}:1",
        "text": "asdkjhaskjdh",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert body["kind"] == "unparseable"
    assert body["commit_date"] is None


def test_unknown_reference_returns_404(tmp_path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/promises/simulate-reply", json={
        "reference_id": "j_nope:1",
        "text": "kal paisa bhejta hoon",
    })
    assert resp.status_code == 404
