"""Preventive pre-debit nudge workflow: distinct events, Guardian guardrails,
and the test-safe API trigger.

The pre-debit nudge is the *proactive* counterpart to the reactive failure
recovery: it fires BEFORE a scheduled AutoPay debit (the RBI 24h pre-debit
notice). It appends two distinct events — ``predebit.scheduled`` and
``predebit.notified`` — and suppresses the notice (recording
``intervention.vetoed``) when the kill switch is on or it is quiet hours.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from cadence.clock import FakeClock
from cadence.config import PolicyConfig
from cadence.events import (
    E_INTERVENTION_VETOED,
    E_PREDEBIT_NOTIFIED,
    E_PREDEBIT_SCHEDULED,
)
from cadence.journey.engine import RecoveryEngine
from cadence.store.db import Database
from cadence.store.event_store import EventStore
from cadence.store.journey_repo import JourneyRepo
from cadence.store.queue_repo import QueueRepo
from tests.test_api import _config

_DEBIT_AT = "2026-08-24T04:30:00+00:00"  # 24h ahead of the failure clock


def _policy_config() -> PolicyConfig:
    return PolicyConfig(
        touch_cap_per_window=3,
        touch_window_days=14,
        max_retry_attempts=3,
        quiet_hours_start=21,
        quiet_hours_end=9,
        timezone="Asia/Kolkata",
    )


def _engine(db: Database, clock: FakeClock) -> RecoveryEngine:
    return RecoveryEngine(
        db=db,
        event_store=EventStore(db),
        journeys=JourneyRepo(db),
        queue=QueueRepo(db),
        cfg=_policy_config(),
        clock=clock,
    )


def _types(db: Database, sub_id: str) -> list[str]:
    return [e.type for e in EventStore(db).get_by_aggregate("journey", sub_id)]


def test_schedule_appends_scheduled_and_notified(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    # Default FakeClock = 2026-08-22T10:00Z = 15:30 IST -> contactable.
    engine = _engine(tmp_db, fake_clock)

    result = engine.schedule_predebit_nudge(
        subscription_id="sub_pdn",
        customer_id="cust_pdn",
        amount_minor=49900,
        currency="INR",
        debit_at=_DEBIT_AT,
        channel="whatsapp",
    )

    assert result["notified"] is True
    assert result["reason"] == "ok"
    assert result["scheduled_event"] is True
    assert result["notified_event"] is True
    assert result["ref"] and result["ref"].startswith("pdn_")

    types = _types(tmp_db, "sub_pdn")
    assert E_PREDEBIT_SCHEDULED in types
    assert E_PREDEBIT_NOTIFIED in types
    assert E_INTERVENTION_VETOED not in types

    # The notice payload carries the amount only (no PII) and the channel.
    notified = [
        e
        for e in EventStore(tmp_db).get_by_aggregate("journey", "sub_pdn")
        if e.type == E_PREDEBIT_NOTIFIED
    ]
    assert len(notified) == 1
    assert notified[0].payload["channel"] == "whatsapp"
    assert notified[0].payload["debit_at"] == _DEBIT_AT
    assert "\u20b9499" in notified[0].payload["message"]


def test_email_channel_notice(tmp_db: Database, fake_clock: FakeClock) -> None:
    engine = _engine(tmp_db, fake_clock)
    result = engine.schedule_predebit_nudge(
        subscription_id="sub_email",
        customer_id="cust_email",
        amount_minor=120000,
        debit_at=_DEBIT_AT,
        channel="email",
    )
    assert result["notified"] is True
    assert result["channel"] == "email"
    notified = [
        e
        for e in EventStore(tmp_db).get_by_aggregate("journey", "sub_email")
        if e.type == E_PREDEBIT_NOTIFIED
    ]
    assert len(notified) == 1
    assert "Team Cadence" in notified[0].payload["message"]


def test_quiet_hours_vetoes_notification(tmp_db: Database) -> None:
    # 22:00 UTC == 03:30 IST -> quiet hours (03 < quiet_hours_end 09).
    clock = FakeClock(datetime(2026, 8, 22, 22, 0, tzinfo=UTC))
    engine = _engine(tmp_db, clock)

    result = engine.schedule_predebit_nudge(
        subscription_id="sub_quiet",
        customer_id="cust_quiet",
        amount_minor=49900,
        debit_at=_DEBIT_AT,
    )

    assert result["notified"] is False
    assert result["reason"] == "quiet_hours"
    assert result["notified_event"] is False

    types = _types(tmp_db, "sub_quiet")
    assert E_PREDEBIT_SCHEDULED in types      # intent still recorded
    assert E_INTERVENTION_VETOED in types     # suppression recorded
    assert E_PREDEBIT_NOTIFIED not in types   # no notice went out


def test_kill_switch_blocks(tmp_db: Database, fake_clock: FakeClock) -> None:
    tmp_db.conn.execute(
        """
        INSERT INTO system_flags (flag, enabled, updated_at)
        VALUES ('kill_switch', 1, ?)
        ON CONFLICT(flag) DO UPDATE SET enabled = 1
        """,
        ("2026-08-22T10:00:00+00:00",),
    )
    engine = _engine(tmp_db, fake_clock)

    result = engine.schedule_predebit_nudge(
        subscription_id="sub_kill",
        customer_id="cust_kill",
        amount_minor=49900,
        debit_at=_DEBIT_AT,
    )

    assert result["notified"] is False
    assert result["reason"] == "kill_switch"

    types = _types(tmp_db, "sub_kill")
    assert E_PREDEBIT_SCHEDULED in types
    assert E_INTERVENTION_VETOED in types
    assert E_PREDEBIT_NOTIFIED not in types


@pytest.mark.integration
def test_api_predebit_schedule_endpoint(tmp_path: Path) -> None:
    app = create_app(cfg=_config(tmp_path / "pdn.db"))
    client = TestClient(app)

    response = client.post(
        "/api/predebit/schedule",
        json={
            "subscription_id": "sub_api_pdn",
            "customer_id": "cust_api_pdn",
            "amount_minor": 49900,
            "debit_at": _DEBIT_AT,
            "channel": "whatsapp",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notified"] is True
    assert body["reason"] == "ok"
    assert body["scheduled_event"] is True
    assert body["notified_event"] is True

    # The two distinct events are appended under the subscription aggregate.
    # The pre-debit workflow opens no recovery journey, so we read the events
    # directly from the runtime's event store (the timeline endpoint requires
    # a journey row, which this proactive path deliberately does not create).
    runtime = app.state.runtime
    types = [
        e.type
        for e in runtime.store.get_by_aggregate("journey", "sub_api_pdn")
    ]
    assert E_PREDEBIT_SCHEDULED in types
    assert E_PREDEBIT_NOTIFIED in types
