"""Tests for the mandate retry sequencer."""
from __future__ import annotations

import pytest
from datetime import datetime, UTC, timedelta
from pathlib import Path
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from cadence.mandate.sequencer import (
    ACTION_REMITTER_OUTREACH,
    ACTION_RETRY_24H,
    ACTION_RETRY_NOW,
    ACTION_STOP_AND_HUMAN_REVIEW,
    ACTION_SWITCH_METHOD,
    MandateFailure,
    MandateState,
    decide,
)
from tests.test_api import _config

pytestmark = [pytest.mark.integration]


def _state(
    *,
    status: str = "active",
    paused_at: datetime | None = None,
    recent: list[MandateFailure] | None = None,
) -> MandateState:
    return MandateState(
        id="mnd_test",
        customer_id="cust_test",
        status=status,
        paused_at=paused_at,
        recent_failures=tuple(recent or []),
    )


def _f(cause: str, when: datetime) -> MandateFailure:
    return MandateFailure(cause=cause, occurred_at=when)


# --- pure state machine ---


def test_default_same_day_retry_for_non_bank_down_cause() -> None:
    s = _state()
    d = decide(s, now=datetime(2026, 8, 22, 10, 0, tzinfo=UTC), cause="NO_FUNDS")
    assert d.action == ACTION_RETRY_NOW
    assert d.schedule_after == timedelta(0)


def test_bank_down_cause_gets_24h_retry() -> None:
    s = _state()
    d = decide(s, now=datetime(2026, 8, 22, 10, 0, tzinfo=UTC), cause="BANK_DOWN")
    assert d.action == ACTION_RETRY_24H
    assert d.schedule_after == timedelta(hours=24)


def test_three_bank_down_in_7d_triggers_remitter_outreach() -> None:
    now = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    s = _state(recent=[
        _f("BANK_DOWN", now - timedelta(days=1)),
        _f("BANK_DOWN", now - timedelta(days=3)),
        _f("BANK_DOWN", now - timedelta(days=5)),
    ])
    d = decide(s, now=now, cause="BANK_DOWN")
    assert d.action == ACTION_REMITTER_OUTREACH


def test_two_bank_down_in_7d_does_not_trigger_outreach() -> None:
    now = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    s = _state(recent=[
        _f("BANK_DOWN", now - timedelta(days=1)),
        _f("BANK_DOWN", now - timedelta(days=3)),
    ])
    d = decide(s, now=now, cause="BANK_DOWN")
    assert d.action == ACTION_RETRY_24H  # not yet 3


def test_three_distinct_causes_triggers_human_review() -> None:
    now = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    s = _state(recent=[
        _f("NO_FUNDS", now - timedelta(days=1)),
        _f("BANK_DOWN", now - timedelta(days=2)),
        _f("TIMEOUT", now - timedelta(days=3)),
    ])
    d = decide(s, now=now, cause="BAD_VPA")
    assert d.action == ACTION_STOP_AND_HUMAN_REVIEW


def test_mandate_paused_over_14d_triggers_switch_method() -> None:
    now = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    s = _state(status="paused", paused_at=now - timedelta(days=20))
    d = decide(s, now=now, cause="NO_FUNDS")
    assert d.action == ACTION_SWITCH_METHOD


def test_mandate_paused_under_14d_does_not_trigger_switch() -> None:
    now = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    s = _state(status="paused", paused_at=now - timedelta(days=7))
    d = decide(s, now=now, cause="NO_FUNDS")
    assert d.action == ACTION_RETRY_NOW


# --- API integration ---


def test_post_mandate_failed_returns_decision(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.post("/api/mandate/failed", json={
        "subscription_id": "sub_x",
        "customer_id": "cust_x",
        "mandate_id": "mnd_x",
        "cause": "BANK_DOWN",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == ACTION_RETRY_24H
    assert body["schedule_after_seconds"] == 86400


def test_post_mandate_failed_with_recent_outreach(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    from datetime import datetime as _dt, UTC, timedelta as _td
    now_dt = _dt.now(tz=UTC)
    now_iso = now_dt.isoformat()
    recent = [
        {"cause": "BANK_DOWN", "occurred_at": (now_dt - _td(days=1)).isoformat()},
        {"cause": "BANK_DOWN", "occurred_at": (now_dt - _td(days=3)).isoformat()},
        {"cause": "BANK_DOWN", "occurred_at": (now_dt - _td(days=5)).isoformat()},
    ]
    r = client.post("/api/mandate/failed", json={
        "subscription_id": "sub_y",
        "customer_id": "cust_y",
        "mandate_id": "mnd_y",
        "cause": "BANK_DOWN",
        "occurred_at": now_iso,
        "recent_failures": recent,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == ACTION_REMITTER_OUTREACH


def test_get_sequenced_returns_recent_decisions(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    # Record two decisions
    for cid in ("a", "b"):
        client.post("/api/mandate/failed", json={
            "subscription_id": f"sub_{cid}",
            "customer_id": f"cust_{cid}",
            "mandate_id": f"mnd_{cid}",
            "cause": "NO_FUNDS",
        })
    r = client.get("/api/mandate/sequenced?limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 2
    # Newest first since we read the tail of the file
    mandate_ids = {r["mandate_id"] for r in rows}
    assert "mnd_a" in mandate_ids
    assert "mnd_b" in mandate_ids


def test_summary_counts_by_action(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    client.post("/api/mandate/failed", json={
        "subscription_id": "sub_z1", "customer_id": "cust_z1",
        "mandate_id": "mnd_z1", "cause": "NO_FUNDS",
    })
    client.post("/api/mandate/failed", json={
        "subscription_id": "sub_z2", "customer_id": "cust_z2",
        "mandate_id": "mnd_z2", "cause": "BANK_DOWN",
    })
    r = client.get("/api/mandate/sequenced/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"].get("RETRY_NOW", 0) >= 1
    assert body["counts"].get("RETRY_24H", 0) >= 1
