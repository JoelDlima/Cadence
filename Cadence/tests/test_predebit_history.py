"""Preventive notice history: the Dashboard-visible projection of pre-debit events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from tests.test_p1_lifecycle_routes import _config

pytestmark = [pytest.mark.integration]


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(cfg=_config(tmp_path)))


def test_history_lists_a_notice_with_its_actual_outcome(tmp_path) -> None:
    """Uses the real system clock, so this may land inside or outside IST
    quiet hours depending on when the suite runs; the history endpoint must
    honestly reflect whichever outcome the Guardian actually reached, not
    assume notified=True regardless of wall-clock time."""
    client = _client(tmp_path)
    debit_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    resp = client.post("/api/predebit/schedule", json={
        "subscription_id": "sub_history_notified",
        "customer_id": "cust_history_notified",
        "amount_minor": 49900,
        "debit_at": debit_at,
        "channel": "email",
    })
    assert resp.status_code == 200, resp.text
    scheduled = resp.json()

    history = client.get("/api/predebit/history").json()
    row = next(r for r in history["notices"] if r["subscription_id"] == "sub_history_notified")
    assert row["notified"] == scheduled["notified"]
    assert row["reason"] == scheduled["reason"]
    assert row["channel"] == "email"
    if scheduled["notified"]:
        assert history["notified_count"] >= 1
    else:
        assert history["suppressed_count"] >= 1


def test_history_lists_a_suppressed_notice_with_reason(tmp_path) -> None:
    client = _client(tmp_path)
    client.post("/api/flags/kill-switch", json={"enabled": True})
    debit_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    resp = client.post("/api/predebit/schedule", json={
        "subscription_id": "sub_history_suppressed",
        "customer_id": "cust_history_suppressed",
        "amount_minor": 49900,
        "debit_at": debit_at,
        "channel": "whatsapp",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["notified"] is False

    history = client.get("/api/predebit/history").json()
    row = next(r for r in history["notices"] if r["subscription_id"] == "sub_history_suppressed")
    assert row["notified"] is False
    assert row["reason"] == "kill_switch"
    assert history["suppressed_count"] >= 1
