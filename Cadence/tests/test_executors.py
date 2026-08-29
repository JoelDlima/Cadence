"""Executor tests: simulated Razorpay client paths + dispatcher branches."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest

from revive.classify.taxonomy import PAYMENT_LINK, RETRY_NOW, WHATSAPP_NUDGE
from revive.clock import utc_iso
from revive.config import ChannelConfig, PolicyConfig, RazorpayConfig
from revive.events import (
    AGG_JOURNEY,
    E_ACTION_EXECUTED,
    E_CUSTOMER_REPLIED,
    E_JOURNEY_CLOSED,
    E_PAYMENT_FAILED,
    E_PAYMENT_RECOVERED,
    E_PTP_COMMITTED,
)
from revive.executors.channels import EmailChannel, MockWhatsApp
from revive.executors.contracts import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    TASK_AWAIT_CUSTOMER_REPLY,
    TASK_HANDLE_PAYMENT_FAILED,
    TASK_OUTCOME_CHECK,
    InterventionRequest,
)
from revive.executors.dispatcher import Dispatcher, default_outcome_fn
from revive.executors.razorpay_client import (
    LiveRazorpayClient,
    SimulatedRazorpayClient,
    build_client,
)
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import (
    STATE_CLASSIFIED,
    STATE_CLOSED_UNRECOVERED,
    STATE_INTERVENING,
    STATE_RECOVERED,
    STATE_WAITING_OUTCOME,
    JourneyRepo,
)
from revive.store.queue_repo import QueueRepo

pytestmark = [pytest.mark.unit]

_POLICY = PolicyConfig(
    touch_cap_per_window=3,
    touch_window_days=14,
    max_retry_attempts=3,
    quiet_hours_start=21,
    quiet_hours_end=9,
    timezone="Asia/Kolkata",
)


def _seed_intervening_journey(journeys: JourneyRepo) -> None:
    journeys.create(
        journey_id="j-1",
        subscription_id="sub-1",
        customer_id="cust-1",
        amount_minor=49900,
        currency="INR",
        failure_code="insufficient_funds",
        opened_at="2026-08-22T09:55:00+00:00",
    )
    journeys.update_fields(
        "j-1", {"state": STATE_INTERVENING}, updated_at="2026-08-22T09:56:00+00:00"
    )


def _make_request(**overrides: Any) -> InterventionRequest:
    fields: dict[str, Any] = {
        "journey_id": "j-1",
        "subscription_id": "sub-1",
        "customer_id": "cust-1",
        "intervention": PAYMENT_LINK,
        "amount_minor": 49900,
        "currency": "INR",
        "attempt_no": 1,
        "scheduled_at": "2026-08-22T10:00:00+00:00",
    }
    fields.update(overrides)
    return InterventionRequest(**fields)


def _make_dispatcher(
    db: Database,
    fake_clock: Any,
    outcome_fn: Any = default_outcome_fn,
    channels: dict[str, Any] | None = None,
) -> Dispatcher:
    return Dispatcher(
        db=db,
        event_store=EventStore(db),
        journeys=JourneyRepo(db),
        queue=QueueRepo(db),
        client=SimulatedRazorpayClient(),
        cfg=_POLICY,
        clock=fake_clock,
        outcome_fn=outcome_fn,
        channels=channels,
    )


def _mock_channels() -> dict[str, Any]:
    return {
        "whatsapp": MockWhatsApp(),
        "email": EmailChannel(
            cfg=ChannelConfig(resend_api_key="", email_from="revive@example.com")
        ),
    }


def _pending_tasks(db: Database) -> list[Any]:
    return db.conn.execute(
        """
        SELECT task_type, available_at, payload, idempotency_key FROM task_queue
         WHERE status='pending' ORDER BY task_id ASC
        """
    ).fetchall()


def test_payment_link_executes_and_schedules_outcome_check(
    tmp_db: Database, fake_clock: Any
) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_intervening_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock)

    # Act
    result = dispatcher.execute(_make_request())

    # Assert
    assert result.status == STATUS_EXECUTED
    assert result.ref is not None
    assert result.ref.startswith("plink_sim_")
    assert journeys.get("j-1").state == STATE_WAITING_OUTCOME
    rows = _pending_tasks(tmp_db)
    assert [row["task_type"] for row in rows] == [TASK_OUTCOME_CHECK]
    assert rows[0]["available_at"] == utc_iso(fake_clock.now() + timedelta(seconds=20))
    assert json.loads(rows[0]["payload"]) == {
        "journey_id": "j-1",
        "subscription_id": "sub-1",
        "attempt_no": 1,
    }


def test_retry_success_recovers_and_closes_journey(tmp_db: Database, fake_clock: Any) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_intervening_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock, outcome_fn=lambda seed: True)

    # Act
    result = dispatcher.execute(_make_request(intervention=RETRY_NOW))

    # Assert
    assert result.status == STATUS_EXECUTED
    journey = journeys.get("j-1")
    assert journey.state == STATE_RECOVERED
    assert journey.closed_at == utc_iso(fake_clock.now())
    assert journey.attempts_used == 1
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "j-1")
    recovered = [e for e in events if e.type == E_PAYMENT_RECOVERED]
    assert len(recovered) == 1
    assert recovered[0].payload["via"] == "intervention"
    assert recovered[0].payload["payment_ref"] == result.ref


def test_retry_failure_loops_back_and_queues_cool_off(tmp_db: Database, fake_clock: Any) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_intervening_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock, outcome_fn=lambda seed: False)

    # Act
    result = dispatcher.execute(_make_request(intervention=RETRY_NOW))

    # Assert
    assert result.status == STATUS_EXECUTED
    journey = journeys.get("j-1")
    assert journey.state == STATE_CLASSIFIED
    assert journey.attempts_used == 1
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "j-1")
    failures = [e for e in events if e.type == E_PAYMENT_FAILED]
    assert len(failures) == 1
    assert failures[0].payload["failure_code"] == "retry_debit_failed"
    rows = _pending_tasks(tmp_db)
    assert [row["task_type"] for row in rows] == [TASK_HANDLE_PAYMENT_FAILED]
    assert rows[0]["available_at"] == utc_iso(fake_clock.now() + timedelta(seconds=60))
    payload = json.loads(rows[0]["payload"])
    assert payload["subscription_id"] == "sub-1"
    assert payload["customer_id"] == "cust-1"
    assert payload["failure_code"] is None
    assert payload["error_description"] == "retry debit failed"
    assert payload["amount_minor"] == 49900
    assert payload["currency"] == "INR"


def test_whatsapp_nudge_is_skipped_without_state_change(
    tmp_db: Database, fake_clock: Any
) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_intervening_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock)

    # Act
    result = dispatcher.execute(_make_request(intervention=WHATSAPP_NUDGE))

    # Assert
    assert result.status == STATUS_SKIPPED
    assert journeys.get("j-1").state == STATE_INTERVENING
    assert _pending_tasks(tmp_db) == []
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "j-1")
    skipped = [
        e
        for e in events
        if e.type == E_ACTION_EXECUTED and e.payload["status"] == "skipped"
    ]
    assert len(skipped) == 1


def test_whatsapp_nudge_executes_when_channel_wired(
    tmp_db: Database, fake_clock: Any
) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_intervening_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock, channels=_mock_channels())

    # Act
    result = dispatcher.execute(_make_request(intervention=WHATSAPP_NUDGE))

    # Assert
    assert result.status == STATUS_EXECUTED
    assert result.ref.startswith("wa_")
    journey = journeys.get("j-1")
    assert journey.state == STATE_WAITING_OUTCOME
    assert journey.touches_used == 1
    rows = _pending_tasks(tmp_db)
    assert [row["task_type"] for row in rows] == [TASK_AWAIT_CUSTOMER_REPLY]
    assert rows[0]["available_at"] == utc_iso(fake_clock.now() + timedelta(hours=24))
    assert rows[0]["idempotency_key"] == "reply:j-1:1:whatsapp"
    assert json.loads(rows[0]["payload"]) == {
        "journey_id": "j-1",
        "subscription_id": "sub-1",
        "customer_id": "cust-1",
        "attempt_no": 1,
        "channel": "whatsapp",
    }


def test_handle_customer_reply_refusal_closes_journey(
    tmp_db: Database, fake_clock: Any
) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_waiting_outcome_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock)

    # Act
    dispatcher.handle_customer_reply(
        {
            "journey_id": "j-1",
            "subscription_id": "sub-1",
            "customer_id": "cust-1",
            "attempt_no": 1,
            "channel": "whatsapp",
            "text": "Cancel kar do subscription",
        }
    )

    # Assert
    journey = journeys.get("j-1")
    assert journey.state == STATE_CLOSED_UNRECOVERED
    assert journey.closed_at == utc_iso(fake_clock.now())
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "j-1")
    replied = [e for e in events if e.type == E_CUSTOMER_REPLIED]
    assert [e.payload["text"] for e in replied] == ["Cancel kar do subscription"]
    assert [e for e in events if e.type == E_PTP_COMMITTED] == []
    closed = [e for e in events if e.type == E_JOURNEY_CLOSED]
    assert [e.payload["reason"] for e in closed] == ["customer_refused"]
    assert _pending_tasks(tmp_db) == []


def test_handle_customer_reply_vague_schedules_three_day_retry(
    tmp_db: Database, fake_clock: Any
) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_waiting_outcome_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock)

    # Act
    dispatcher.handle_customer_reply(
        {
            "journey_id": "j-1",
            "subscription_id": "sub-1",
            "customer_id": "cust-1",
            "attempt_no": 1,
            "channel": "whatsapp",
            "text": "Pakka try karta hu",
        }
    )

    # Assert
    assert journeys.get("j-1").state == STATE_CLASSIFIED
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "j-1")
    committed = [e for e in events if e.type == E_PTP_COMMITTED]
    assert len(committed) == 1
    assert committed[0].payload == {
        "kind": "vague",
        "date": None,
        "confidence": 0.5,
        "days": 3,
    }
    failures = [e for e in events if e.type == E_PAYMENT_FAILED]
    assert len(failures) == 1
    rows = _pending_tasks(tmp_db)
    assert [row["task_type"] for row in rows] == [TASK_HANDLE_PAYMENT_FAILED]
    fire_at = fake_clock.in_tz(_POLICY.timezone) + timedelta(days=3)
    assert rows[0]["available_at"] == utc_iso(fire_at)
    assert rows[0]["idempotency_key"] == "ptp:j-1:1"
    payload = json.loads(rows[0]["payload"])
    assert payload["subscription_id"] == "sub-1"
    assert payload["customer_id"] == "cust-1"
    assert payload["amount_minor"] == 49900


def _seed_waiting_outcome_journey(journeys: JourneyRepo) -> None:
    _seed_intervening_journey(journeys)
    journeys.update_fields(
        "j-1", {"state": STATE_WAITING_OUTCOME}, updated_at="2026-08-22T09:57:00+00:00"
    )


def test_unknown_intervention_fails_without_raising(tmp_db: Database, fake_clock: Any) -> None:
    # Arrange
    journeys = JourneyRepo(tmp_db)
    _seed_intervening_journey(journeys)
    dispatcher = _make_dispatcher(tmp_db, fake_clock)

    # Act
    result = dispatcher.execute(_make_request(intervention="TELEPORT_CUSTOMER"))

    # Assert
    assert result.status == STATUS_FAILED
    assert journeys.get("j-1").state == STATE_INTERVENING
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "j-1")
    failed = [
        e
        for e in events
        if e.type == E_ACTION_EXECUTED and e.payload["status"] == "failed"
    ]
    assert len(failed) == 1


def test_live_client_posts_basic_auth_json_to_payment_links() -> None:
    # Arrange
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200, json={"id": "plink_live_1", "short_url": "https://rzp.io/i/x", "status": "created"}
        )

    client = LiveRazorpayClient(
        RazorpayConfig("key_id_x", "key_secret_x", "whsec_x"),
        transport=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    # Act
    link = client.create_payment_link(
        amount_minor=49900,
        currency="INR",
        customer_id="cust-1",
        description="Revive recovery",
        reference_id="j-1:1",
    )

    # Assert
    assert link["id"] == "plink_live_1"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.razorpay.com/v1/payment_links"
    assert captured["authorization"].startswith("Basic ")
    assert captured["body"]["amount"] == 49900


def test_build_client_picks_live_iff_keys_present() -> None:
    # Act / Assert
    assert isinstance(build_client(RazorpayConfig("", "", "s")), SimulatedRazorpayClient)
    assert isinstance(build_client(RazorpayConfig("key", "sec", "s")), LiveRazorpayClient)
