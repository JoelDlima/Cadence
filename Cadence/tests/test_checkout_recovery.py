"""Tests for the checkout drop-off recovery state machine + API."""
from __future__ import annotations

import pytest
from datetime import datetime, UTC, timedelta
from pathlib import Path
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from cadence.checkout.recovery import (
    ABANDON_AFTER,
    EXPIRE_AFTER,
    MAX_NUDGES,
    NUDGE_T1_AFTER,
    NUDGE_T2_AFTER,
    STATUS_ABANDONED,
    STATUS_EXPIRED,
    STATUS_NUDGED,
    STATUS_OPEN,
    STATUS_RECOVERED,
    CheckoutSession,
    decide,
)
from tests.test_api import _config

pytestmark = [pytest.mark.integration]


# --- pure state machine ---


def _session(
    *,
    status: str = STATUS_OPEN,
    started_at: datetime | None = None,
    abandoned_at: datetime | None = None,
    last_nudge_at: datetime | None = None,
    nudges_sent: int = 0,
) -> CheckoutSession:
    return CheckoutSession(
        id="co_test",
        customer_id="cust_test",
        amount_minor=49900,
        status=status,
        started_at=started_at or datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        abandoned_at=abandoned_at,
        last_nudge_at=last_nudge_at,
        nudges_sent=nudges_sent,
    )


def test_open_session_within_window_does_nothing() -> None:
    s = _session(status=STATUS_OPEN)
    now = s.started_at + timedelta(minutes=10)
    d = decide(s, now=now)
    assert d.next_status == STATUS_OPEN
    assert d.should_nudge is False
    assert "still in checkout window" in d.reason


def test_open_session_past_abandon_threshold_moves_to_abandoned() -> None:
    s = _session(status=STATUS_OPEN)
    now = s.started_at + ABANDON_AFTER + timedelta(seconds=1)
    d = decide(s, now=now)
    assert d.next_status == STATUS_ABANDONED
    assert d.should_nudge is True
    assert d.include_discount is False


def test_abandoned_session_fires_first_nudge() -> None:
    s = _session(
        status=STATUS_ABANDONED,
        abandoned_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC) + ABANDON_AFTER,
    )
    d = decide(s, now=datetime(2026, 8, 22, 10, 30, tzinfo=UTC))
    assert d.next_status == STATUS_NUDGED
    assert d.should_nudge is True
    assert d.include_discount is False
    assert "first nudge" in d.reason


def test_nudged_session_too_soon_for_second_nudge() -> None:
    s = _session(
        status=STATUS_NUDGED,
        last_nudge_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        nudges_sent=1,
    )
    now = s.last_nudge_at + timedelta(hours=1)  # less than NUDGE_T1_AFTER
    d = decide(s, now=now)
    assert d.next_status == STATUS_NUDGED
    assert d.should_nudge is False
    assert "too soon" in d.reason


def test_nudged_session_after_t1_fires_second_nudge() -> None:
    s = _session(
        status=STATUS_NUDGED,
        last_nudge_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        nudges_sent=1,
    )
    now = s.last_nudge_at + NUDGE_T1_AFTER + timedelta(seconds=1)
    d = decide(s, now=now)
    assert d.next_status == STATUS_NUDGED
    assert d.should_nudge is True
    assert d.include_discount is False
    assert "nudge #2" in d.reason


def test_nudged_session_after_t2_fires_third_nudge_with_discount() -> None:
    s = _session(
        status=STATUS_NUDGED,
        last_nudge_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        nudges_sent=2,
    )
    now = s.last_nudge_at + NUDGE_T2_AFTER + timedelta(seconds=1)
    d = decide(s, now=now)
    assert d.next_status == STATUS_NUDGED
    assert d.should_nudge is True
    assert d.include_discount is True
    assert "nudge #3" in d.reason


def test_nudged_session_at_max_nudges_expires() -> None:
    s = _session(
        status=STATUS_NUDGED,
        last_nudge_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        nudges_sent=MAX_NUDGES,
    )
    now = s.last_nudge_at + NUDGE_T2_AFTER + timedelta(seconds=1)
    d = decide(s, now=now)
    assert d.next_status == STATUS_EXPIRED
    assert d.should_nudge is False


def test_paid_event_always_recovers() -> None:
    s = _session(status=STATUS_NUDGED, nudges_sent=1)
    d = decide(s, now=datetime(2026, 8, 22, 10, 0, tzinfo=UTC), paid_event=True)
    assert d.next_status == STATUS_RECOVERED
    assert d.should_nudge is False


def test_already_recovered_is_terminal() -> None:
    s = _session(status=STATUS_RECOVERED)
    d = decide(s, now=datetime(2026, 8, 22, 11, 0, tzinfo=UTC))
    assert d.next_status == STATUS_RECOVERED
    assert d.should_nudge is False


def test_expire_ceiling_applies_even_at_nudged() -> None:
    s = _session(
        status=STATUS_NUDGED,
        last_nudge_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        nudges_sent=1,
    )
    # Way past EXPIRE_AFTER even though we're only 1 nudge in.
    now = s.started_at + EXPIRE_AFTER + timedelta(seconds=1)
    d = decide(s, now=now)
    assert d.next_status == STATUS_EXPIRED
    assert d.should_nudge is False


# --- API integration ---


def _abandon(client: TestClient, *, customer: str, amount: int, started_at: str | None = None) -> dict:
    body = {"customer_id": customer, "amount_minor": amount, "currency": "INR"}
    if started_at:
        body["started_at"] = started_at
    r = client.post("/api/checkout/abandon", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_abandon_then_list(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    _abandon(client, customer="cust_a", amount=49900)
    _abandon(client, customer="cust_b", amount=19900)
    r = client.get("/api/checkout/sessions?limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {r["customer_id"] for r in rows} == {"cust_a", "cust_b"}


def test_funnel_counts(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    _abandon(client, customer="cust_a", amount=49900)
    _abandon(client, customer="cust_b", amount=49900)
    r = client.get("/api/checkout/funnel")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["OPEN"] == 2


def test_tick_does_nothing_when_all_open_within_window(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    # Insert a session with started_at = now
    r = client.post("/api/checkout/abandon", json={
        "customer_id": "cust_a", "amount_minor": 49900,
    })
    sid = r.json()["id"]
    # Tick: all sessions are still in window
    r = client.post("/api/checkout/tick")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["considered"] == 1
    assert body["no_op"] >= 0  # may count as no-op
    # The session should still be OPEN
    r = client.get("/api/checkout/sessions?limit=10")
    rows = r.json()
    assert rows[0]["status"] == STATUS_OPEN


def test_tick_transitions_to_abandoned_when_past_window(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    # Started 2 hours ago -> well past ABANDON_AFTER
    long_ago = "2026-08-22T08:00:00+00:00"
    r = client.post("/api/checkout/abandon", json={
        "customer_id": "cust_long_ago", "amount_minor": 49900,
        "started_at": long_ago,
    })
    sid = r.json()["id"]
    r = client.post("/api/checkout/tick")
    assert r.status_code == 200
    body = r.json()
    assert body["considered"] == 1
    # First tick: OPEN -> ABANDONED (and the side-effect should_nudge
    # fires a NUDGED state with nudges_sent=1). Either is acceptable
    # for a single-tick call; we just need the chaser to have moved
    # the row out of OPEN.
    r = client.get("/api/checkout/sessions?limit=10")
    rows = r.json()
    assert rows[0]["status"] in (STATUS_ABANDONED, STATUS_NUDGED)
    assert rows[0]["nudges_sent"] >= 1
    # Second tick should leave the row in NUDGED (no further nudge
    # within T1 window of the last nudge).
    r = client.post("/api/checkout/tick")
    assert r.status_code == 200
    r = client.get("/api/checkout/sessions?limit=10")
    rows = r.json()
    assert rows[0]["status"] == STATUS_NUDGED


def test_recover_endpoint_closes_session(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    long_ago = "2026-08-22T08:00:00+00:00"
    r = client.post("/api/checkout/abandon", json={
        "customer_id": "cust_x", "amount_minor": 49900,
        "started_at": long_ago,
    })
    sid = r.json()["id"]
    r = client.post(f"/api/checkout/recover/{sid}", json={
        "payment_id": "pay_test_001",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == STATUS_RECOVERED
    assert body["recovery_payment_id"] == "pay_test_001"
    assert body["recovered_at"] is not None


def test_recover_unknown_session_returns_404(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.post("/api/checkout/recover/co_nonexistent", json={
        "payment_id": "pay_x",
    })
    assert r.status_code == 404
