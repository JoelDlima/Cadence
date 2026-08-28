"""Tests for the B2B receivables chaser state machine + API."""
from __future__ import annotations

import pytest
from datetime import datetime, UTC, timedelta
from pathlib import Path
from fastapi.testclient import TestClient

from revive.api.app import create_app
from revive.b2b.chaser import (
    ACTION_FIRMER,
    ACTION_FRIENDLY,
    ACTION_MANAGER,
    ACTION_NONE,
    ACTION_PRE_DUE,
    ACTION_WRITTEN,
    ACTION_WRITEOFF,
    STATUS_CANCELLED,
    STATUS_IN_DISPUTE,
    STATUS_ISSUED,
    STATUS_PAID,
    Invoice,
    decide,
)
from tests.test_api import _config

pytestmark = [pytest.mark.integration]


# --- pure state machine ---


def _invoice(
    *,
    due_offset_days: int = 0,
    status: str = STATUS_ISSUED,
    chases_sent: int = 0,
    due_at: datetime | None = None,
) -> Invoice:
    base = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    return Invoice(
        id="inv_test",
        org_id="org_test",
        amount_minor=1250000,  # ₹12,500
        due_date=due_at or (base + timedelta(days=due_offset_days)),
        status=status,
        chases_sent=chases_sent,
        last_chase_at=None,
    )


def test_paid_invoice_does_nothing() -> None:
    inv = _invoice(status=STATUS_PAID, due_offset_days=10)
    d = decide(inv, now=datetime(2026, 8, 25, 10, 0, tzinfo=UTC))
    assert d.action == ACTION_NONE
    assert d.should_chase is False


def test_in_dispute_pauses_chases() -> None:
    inv = _invoice(status=STATUS_IN_DISPUTE, due_offset_days=-10)
    d = decide(inv, now=datetime(2026, 8, 25, 10, 0, tzinfo=UTC))
    assert d.action == ACTION_NONE
    assert d.should_chase is False


def test_pre_due_reminder_fires_at_t_minus_3() -> None:
    inv = _invoice(due_offset_days=-2)  # 2 days from now (within T-3)
    d = decide(inv, now=datetime(2026, 8, 22, 10, 0, tzinfo=UTC))
    assert d.action == ACTION_PRE_DUE
    assert d.should_chase is True
    assert d.channel == "email"


def test_friendly_nudge_at_t_plus_3() -> None:
    inv = _invoice(
        due_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
    )
    d = decide(inv, now=datetime(2026, 8, 25, 10, 0, tzinfo=UTC))  # 3 days past
    assert d.action == ACTION_FRIENDLY
    assert d.should_chase is True
    assert d.days_past_due == 3


def test_firmer_nudge_at_t_plus_7() -> None:
    inv = _invoice(
        due_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
    )
    d = decide(inv, now=datetime(2026, 8, 29, 10, 0, tzinfo=UTC))  # 7 days past
    assert d.action == ACTION_FIRMER
    assert d.should_chase is True


def test_manager_escalation_at_t_plus_14() -> None:
    inv = _invoice(
        due_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
    )
    d = decide(inv, now=datetime(2026, 9, 5, 10, 0, tzinfo=UTC))  # 14 days past
    assert d.action == ACTION_MANAGER
    assert d.should_chase is True
    assert d.channel == "manager"
    assert d.recipient == "manager"


def test_written_notice_at_t_plus_21() -> None:
    inv = _invoice(
        due_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
    )
    d = decide(inv, now=datetime(2026, 9, 12, 10, 0, tzinfo=UTC))  # 21 days past
    assert d.action == ACTION_WRITTEN
    assert d.should_chase is True
    assert d.channel == "legal"


def test_writeoff_at_t_plus_45() -> None:
    inv = _invoice(
        due_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
    )
    d = decide(inv, now=datetime(2026, 10, 6, 10, 0, tzinfo=UTC))  # 45 days past
    assert d.action == ACTION_WRITEOFF
    assert d.should_chase is True


def test_issued_invoice_within_terms_does_nothing() -> None:
    inv = _invoice(due_offset_days=20)  # due in 20 days, no chases yet
    d = decide(inv, now=datetime(2026, 8, 22, 10, 0, tzinfo=UTC))
    assert d.action == ACTION_NONE
    assert d.should_chase is False


def test_3_chases_does_not_re_friendly_nudge() -> None:
    """Once chases_sent >= 3, the friendly-nudge window is exhausted."""
    inv = _invoice(due_offset_days=-5, chases_sent=3)
    d = decide(inv, now=datetime(2026, 8, 27, 10, 0, tzinfo=UTC))
    assert d.action == ACTION_NONE


# --- API integration ---


def test_create_invoice_then_list(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.post("/api/b2b/invoice/create", json={
        "org_id": "org_acme",
        "contact_email": "ar@acme.test",
        "amount_minor": 1250000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == STATUS_ISSUED
    assert body["chases_sent"] == 0

    r = client.get("/api/b2b/invoices?status=issued&limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]


def test_funnel_counts(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    client.post("/api/b2b/invoice/create", json={
        "org_id": "org_a", "amount_minor": 100,
    })
    client.post("/api/b2b/invoice/create", json={
        "org_id": "org_b", "amount_minor": 200,
    })
    r = client.get("/api/b2b/funnel")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["issued"] == 2


def test_chase_endpoint_records_action(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    # Past due by 7 days
    long_past = (datetime(2026, 8, 15, 10, 0, tzinfo=UTC)).isoformat()
    r = client.post("/api/b2b/invoice/create", json={
        "org_id": "org_x",
        "contact_email": "ar@x.test",
        "amount_minor": 99900,
        "due_date": long_past,
    })
    inv_id = r.json()["id"]
    r = client.post(f"/api/b2b/invoice/{inv_id}/chase")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chases_sent"] == 1
    assert body["last_chase_action"] in (ACTION_FRIENDLY, ACTION_FIRMER, ACTION_MANAGER,
                                          ACTION_WRITTEN, ACTION_WRITEOFF, ACTION_PRE_DUE)


def test_unknown_invoice_returns_404(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.post("/api/b2b/invoice/inv_nope/chase")
    assert r.status_code == 404


def test_overdue_lists_only_overdue(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    past = (datetime(2026, 8, 1, 10, 0, tzinfo=UTC)).isoformat()
    future = (datetime(2026, 12, 1, 10, 0, tzinfo=UTC)).isoformat()
    client.post("/api/b2b/invoice/create", json={
        "org_id": "org_past", "amount_minor": 100,
        "due_date": past,
    })
    client.post("/api/b2b/invoice/create", json={
        "org_id": "org_future", "amount_minor": 100,
        "due_date": future,
    })
    r = client.get("/api/b2b/invoices/overdue?limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["org_id"] == "org_past"


def test_tick_processes_overdue_invoices(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    # 7 days past due
    past = (datetime(2026, 8, 15, 10, 0, tzinfo=UTC)).isoformat()
    client.post("/api/b2b/invoice/create", json={
        "org_id": "org_chase", "amount_minor": 99900,
        "due_date": past,
    })
    r = client.post("/api/b2b/tick")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["considered"] == 1
    assert body["chased"] == 1
    assert len(body["decisions"]) == 1
