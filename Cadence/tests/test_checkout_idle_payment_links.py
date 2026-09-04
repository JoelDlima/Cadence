"""Self-managed idle recovery for existing Payment Links.

This verifies Cadence's own audit-derived idle detector. It intentionally does
not claim a Razorpay Magic Checkout abandonment signal: it acts only on a
locally-created Payment Link that remains in Razorpay's ``created`` state.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from tests.test_p1_lifecycle_routes import _config

pytestmark = [pytest.mark.integration]


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(cfg=_config(tmp_path)))


def _open_link(client: TestClient) -> dict:
    customer = client.post("/api/live/customer", json={
        "name": "Idle Link Test", "email": "idle@x.local", "contact": "+919999900001",
    })
    assert customer.status_code == 200, customer.text
    response = client.post("/api/live/failure", json={"customer_id": customer.json()["id"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_created_idle_link_runs_the_full_agent_path_once(tmp_path) -> None:
    client = _client(tmp_path)
    opened = _open_link(client)

    scan = client.post("/api/checkout-idle/scan?idle_minutes=0")
    assert scan.status_code == 200, scan.text
    body = scan.json()
    assert body["threshold_minutes"] == 0
    assert len(body["detected"]) == 1
    finding = body["detected"][0]
    assert finding["payment_link_id"] == opened["payment_link"]["id"]
    assert finding["journey_id"]

    events = client.get(f"/api/journeys/{finding['journey_id']}/timeline").json()["events"]
    event_types = {event["type"] for event in events}
    assert "checkout.idle_detected" in event_types
    assert "classification.completed" in event_types
    assert "bandit.ranked" in event_types
    assert event_types & {"intervention.approved", "intervention.vetoed"}
    classification = next(event for event in events if event["type"] == "classification.completed")
    assert classification["payload"]["root_cause"] == "ABANDONED_CHECKOUT"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True

    replay = client.post("/api/checkout-idle/scan?idle_minutes=0")
    assert replay.status_code == 200, replay.text
    assert replay.json()["detected"] == []
    assert replay.json()["already_detected"] == 1
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


def test_paid_and_expired_links_are_ignored_by_idle_scan(tmp_path) -> None:
    client = _client(tmp_path)
    paid = _open_link(client)
    expired = _open_link(client)
    assert client.post("/api/live/lifecycle/force-paid", json={
        "reference_id": paid["payment_link"]["reference_id"],
    }).status_code == 200
    assert client.post("/api/live/lifecycle/force-expired", json={
        "reference_id": expired["payment_link"]["reference_id"],
    }).status_code == 200

    scan = client.post("/api/checkout-idle/scan?idle_minutes=0")
    assert scan.status_code == 200, scan.text
    assert scan.json()["detected"] == []
    assert scan.json()["skipped_non_created"] >= 2
    assert client.get("/api/audit/verify").json()["chain_ok"] is True
