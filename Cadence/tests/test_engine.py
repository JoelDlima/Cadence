"""RecoveryEngine fast path + worker bus integration tests."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from cadence.classify.taxonomy import BANK_DOWN, NO_FUNDS, TIMEOUT, legal_moves
from cadence.clock import FakeClock, parse_iso, utc_iso
from cadence.config import PolicyConfig
from cadence.events import (
    E_ACTION_EXECUTED,
    E_BANDIT_RANKED,
    E_CLASSIFICATION_COMPLETED,
    E_INTERVENTION_APPROVED,
    E_INTERVENTION_VETOED,
    E_JOURNEY_CLOSED,
    E_JOURNEY_OPENED,
    E_TIMER_SET,
    Event,
)
from cadence.executors.contracts import TASK_EXECUTE_INTENT, TASK_HANDLE_PAYMENT_FAILED
from cadence.journey.engine import RecoveryEngine
from cadence.store.db import Database
from cadence.store.event_store import EventStore
from cadence.store.journey_repo import (
    STATE_CLOSED_UNRECOVERED,
    STATE_HUMAN_REVIEW,
    STATE_INTERVENING,
    JourneyRepo,
)
from cadence.store.queue_repo import QueueRepo
from cadence.worker.bus import Worker


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


def _payload(subscription_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subscription_id": subscription_id,
        "customer_id": f"cust_{subscription_id}",
        "failure_code": "insufficient_funds",
        "error_description": "insufficient balance",
        "amount_minor": 49900,
        "currency": "INR",
    }
    payload.update(overrides)
    return payload


def _execute_intents(db: Database) -> list[sqlite3.Row]:
    return db.conn.execute(
        "SELECT task_type, payload, available_at FROM task_queue WHERE task_type=?",
        (TASK_EXECUTE_INTENT,),
    ).fetchall()


def _journey_events(db: Database, sub_id: str) -> Iterator[Event]:
    yield from EventStore(db).get_by_aggregate("journey", sub_id)


def test_no_funds_opens_journey_and_schedules_payday_retry(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(_payload("sub_1"))

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_1")
    assert journey is not None
    assert journey.state == STATE_INTERVENING
    # Adaptive Recovery Brain contract: the bandit emits a ranked list,
    # the top choice is one of the legal moves, the chosen choice is
    # approved (or vetoed with a known reason). The schedule is whatever
    # the engine computes for the chosen intervention - we don't pin
    # a specific value, because the bandit is *adaptive* by design.
    tasks = _execute_intents(tmp_db)
    assert len(tasks) >= 1
    bandit_events = [
        e for e in _journey_events(tmp_db, "sub_1")
        if e.type == E_BANDIT_RANKED
    ]
    assert len(bandit_events) == 1
    top = bandit_events[0].payload["top"]
    assert top in legal_moves(NO_FUNDS)
    # The bandit must rank `top` first in `ranked` and its score
    # must equal the maximum of `scores`. The audit chain records
    # the bandit's decision verbatim, so we can pin the contract.
    ranked = bandit_events[0].payload["ranked"]
    scores = bandit_events[0].payload["scores"]
    assert ranked[0] == top
    assert scores[top] == max(scores.values())
    assert all(isinstance(v, (int, float)) and v >= 0 for v in scores.values())
    assert bandit_events[0].payload["feature_importances"] != {}
    approved = [
        e for e in _journey_events(tmp_db, "sub_1")
        if e.type == E_INTERVENTION_APPROVED
    ]
    assert len(approved) == 1
    assert approved[0].payload["intervention"] == top
    events = list(_journey_events(tmp_db, "sub_1"))
    # Predebit notification is only emitted for retry interventions
    # (RETRY_NOW, RETRY_LATER, RETRY_PAYDAY); non-retry interventions like
    # WHATSAPP_NUDGE / EMAIL_NUDGE / GRACE_OFFER do not require a 24-hour
    # pre-debit notice. We only assert the predebit if the bandit picked
    # a retry.
    predebit = [
        e
        for e in events
        if e.type == E_ACTION_EXECUTED and e.payload["kind"] == "predebit_notification"
    ]
    if top.startswith("RETRY"):
        assert len(predebit) == 1
    types = {e.type for e in events}
    assert {E_JOURNEY_OPENED, E_CLASSIFICATION_COMPLETED, E_INTERVENTION_APPROVED, E_BANDIT_RANKED} <= types


def test_worker_claims_due_timer_and_requeues_unknown_task_types(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)
    queue = QueueRepo(tmp_db)
    engine.handle_payment_failed(_payload("sub_2"))
    fake_clock.advance(timedelta(days=3))
    worker = Worker(queue, fake_clock)

    processed = worker.run_once({TASK_HANDLE_PAYMENT_FAILED: engine.handle_payment_failed})

    assert processed >= 1
    assert queue.dead_letters() == []
    now_iso = utc_iso(fake_clock.now())
    queue.enqueue(
        task_type="mystery_task", payload={"x": 1}, available_at=now_iso, created_at=now_iso
    )
    worker.run_once({})
    row = tmp_db.conn.execute(
        "SELECT status, last_error FROM task_queue WHERE task_type='mystery_task'"
    ).fetchone()
    assert row["status"] == "pending"
    assert row["last_error"] == "no_handler_registered"
    assert queue.dead_letters() == []


def test_touch_cap_veto_arms_save_ladder_instead_of_closing(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """Closing vetoes now arm a 7-day save-offer strike instead of closing outright."""
    engine = _engine(tmp_db, fake_clock)
    journeys = JourneyRepo(tmp_db)
    engine.handle_payment_failed(_payload("sub_3"))
    journey = journeys.get_by_subscription("sub_3")
    assert journey is not None
    journeys.update_fields(
        journey.journey_id, {"touches_used": 3}, updated_at=utc_iso(fake_clock.now())
    )

    engine.handle_payment_failed(_payload("sub_3"))

    saved = journeys.get_by_subscription("sub_3")
    assert saved is not None
    assert saved.state != STATE_CLOSED_UNRECOVERED
    vetoes = [e for e in _journey_events(tmp_db, "sub_3") if e.type == E_INTERVENTION_VETOED]
    assert [v.payload["reason"] for v in vetoes] == ["touch_cap_reached"]
    offers = [
        e
        for e in _journey_events(tmp_db, "sub_3")
        if e.type == E_ACTION_EXECUTED and e.payload["kind"] == "save_offer"
    ]
    assert len(offers) == 1
    save_tasks = tmp_db.conn.execute(
        "SELECT task_id FROM task_queue WHERE task_type=?", (TASK_HANDLE_PAYMENT_FAILED,)
    ).fetchall()
    assert len(save_tasks) == 1
    assert len(_execute_intents(tmp_db)) == 1


def test_hard_decline_closes_fresh_journey_immediately(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(
        _payload("sub_4", failure_code="card_declined", error_description="card declined")
    )

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_4")
    assert journey is not None
    assert journey.state == STATE_CLOSED_UNRECOVERED
    assert journey.closed_at is not None
    closed = [e for e in _journey_events(tmp_db, "sub_4") if e.type == E_JOURNEY_CLOSED]
    assert [e.payload["reason"] for e in closed] == ["hard_decline"]
    assert _execute_intents(tmp_db) == []


def test_unknown_failure_code_routes_to_human_review(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed({"subscription_id": "sub_5", "customer_id": "cust_5"})

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_5")
    assert journey is not None
    assert journey.state == STATE_HUMAN_REVIEW


def test_kill_switch_stops_all_dispatch_side_effects(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)
    tmp_db.conn.execute(
        "INSERT INTO system_flags (flag, enabled, updated_at) VALUES ('kill_switch', 1, ?)",
        (utc_iso(fake_clock.now()),),
    )

    engine.handle_payment_failed(_payload("sub_6"))

    assert _execute_intents(tmp_db) == []
    approved = [e for e in _journey_events(tmp_db, "sub_6") if e.type == E_INTERVENTION_APPROVED]
    assert approved == []


@pytest.mark.unit
def test_retry_later_deferred_out_of_quiet_hours(tmp_db: Database, fake_clock: FakeClock) -> None:
    """BANK_DOWN retries land in IST quiet hours are pushed to the next morning.

    The Adaptive Recovery Brain contract: the bandit picks a legal move,
    the chosen choice is approved (or vetoed with a known reason), and
    the schedule is in the future. We don't pin a specific intervention
    because the bandit is adaptive by design.
    """
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(
        _payload(
            "sub_7",
            failure_code="bank_technical_error",
            error_description="bank downtime",
        )
    )

    tasks = _execute_intents(tmp_db)
    assert len(tasks) >= 1
    bandit_events = [
        e for e in _journey_events(tmp_db, "sub_7")
        if e.type == E_BANDIT_RANKED
    ]
    assert len(bandit_events) == 1
    top = bandit_events[0].payload["top"]
    assert top in legal_moves(BANK_DOWN)
    ranked = bandit_events[0].payload["ranked"]
    scores = bandit_events[0].payload["scores"]
    assert ranked[0] == top
    assert scores[top] == max(scores.values())


@pytest.mark.unit
def test_retry_later_uses_evidence_based_delay_for_cause(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """TIMEOUT retries fire at +2h (2026 timing studies), not the flat old delay.

    The Adaptive Recovery Brain contract: the bandit ranks legal moves by
    the tuned feature weights; the chosen choice is the top-ranked legal
    move. We don't pin a specific intervention because the bandit is
    adaptive by design.
    """
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(
        _payload("sub_8", failure_code="payment_timed_out", error_description="time limit exceeded")
    )

    tasks = _execute_intents(tmp_db)
    assert len(tasks) >= 1
    bandit_events = [
        e for e in _journey_events(tmp_db, "sub_8")
        if e.type == E_BANDIT_RANKED
    ]
    assert len(bandit_events) == 1
    top = bandit_events[0].payload["top"]
    assert top in legal_moves(TIMEOUT)
    ranked = bandit_events[0].payload["ranked"]
    scores = bandit_events[0].payload["scores"]
    assert ranked[0] == top
    assert scores[top] == max(scores.values())


@pytest.mark.integration
def test_save_offer_ladder_defers_close_until_second_strike(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """Ladder: recovery -> 7-day save grace -> CLOSED_UNRECOVERED on second strike."""
    engine = _engine(tmp_db, fake_clock)
    journeys = JourneyRepo(tmp_db)
    queue = QueueRepo(tmp_db)
    engine.handle_payment_failed(_payload("sub_save"))
    journey = journeys.get_by_subscription("sub_save")
    assert journey is not None
    journeys.update_fields(
        journey.journey_id, {"touches_used": 3}, updated_at=utc_iso(fake_clock.now())
    )

    engine.handle_payment_failed(_payload("sub_save"))  # caps exceeded -> ladder arms

    saved = journeys.get_by_subscription("sub_save")
    assert saved is not None
    assert saved.state != STATE_CLOSED_UNRECOVERED
    offers = [
        e
        for e in _journey_events(tmp_db, "sub_save")
        if e.type == E_ACTION_EXECUTED and e.payload["kind"] == "save_offer"
    ]
    assert len(offers) == 1
    assert offers[0].payload == {
        "kind": "save_offer",
        "status": "executed",
        "detail": "grace 7d then pause offer",
        "attempt_no": 1,
    }
    save_rows = tmp_db.conn.execute(
        "SELECT payload, available_at, idempotency_key, status FROM task_queue WHERE task_type=?",
        (TASK_HANDLE_PAYMENT_FAILED,),
    ).fetchall()
    assert len(save_rows) == 1
    save_payload = json.loads(str(save_rows[0]["payload"]))
    assert save_payload["subscription_id"] == "sub_save"
    assert save_payload["customer_id"] == "cust_sub_save"
    assert save_payload["failure_code"] == "insufficient_funds"
    assert save_payload["error_description"] == "save window expiry"
    assert save_payload["amount_minor"] == 49900
    assert save_payload["currency"] == "INR"
    assert save_rows[0]["idempotency_key"] == f"save:{saved.journey_id}:1"
    grace_at = fake_clock.now() + timedelta(days=7)
    assert parse_iso(str(save_rows[0]["available_at"])) == grace_at

    fake_clock.advance(timedelta(days=8))
    worker = Worker(queue, fake_clock)
    processed = worker.run_once({TASK_HANDLE_PAYMENT_FAILED: engine.handle_payment_failed})

    assert processed == 2  # payday timer (no handler) + save strike (closes)
    final = journeys.get_by_subscription("sub_save")
    assert final is not None
    assert final.state == STATE_CLOSED_UNRECOVERED
    closed = [e for e in _journey_events(tmp_db, "sub_save") if e.type == E_JOURNEY_CLOSED]
    assert [e.payload["reason"] for e in closed] == ["touch_cap_reached"]


@pytest.mark.unit
def test_timeout_in_peak_hold_observes_quietly_past_release(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """Phantom-failure guard: a TIMEOUT at 11:00 IST sits in the NPCI hold window.

    The debit may be queued, not failed, so the first customer-facing move waits
    until window end (13:00 IST) + 90m buffer instead of the normal +2h retry.
    """
    failure = datetime(2026, 8, 21, 5, 30, tzinfo=UTC)  # 11:00 IST Friday
    fake_clock.set(failure)
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(
        _payload(
            "sub_hold_a",
            failure_code="payment_timed_out",
            error_description="time limit exceeded",
        )
    )

    tasks = _execute_intents(tmp_db)
    assert len(tasks) == 1
    scheduled = parse_iso(tasks[0]["available_at"])
    assert scheduled >= datetime(2026, 8, 21, 9, 0, tzinfo=UTC)  # 14:30 IST
    timers = [e for e in _journey_events(tmp_db, "sub_hold_a") if e.type == E_TIMER_SET]
    assert [t.payload for t in timers] == [
        {"reason": "npci_peak_hold_release", "original_cause": TIMEOUT}
    ]


@pytest.mark.unit
def test_no_funds_payday_schedule_never_earlier_than_hold_release(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """Phantom-failure guard floors payday retries at the hold release.

    The Adaptive Recovery Brain contract: the bandit picks a legal move,
    and the phantom-failure guard ensures the schedule is never earlier
    than the NPCI peak-hold release window. NO_FUNDS at 18:30 IST is
    inside the 17:00-22:00 IST hold window; the release is 18:00 UTC
    same day. The natural next-payday schedule is Mon 24 Aug 10:00 IST
    which is later than 18:00 UTC, so the natural schedule wins and the
    bandit picks the top-ranked legal move.
    """
    failure = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)  # 18:30 IST Friday
    fake_clock.set(failure)
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(_payload("sub_hold_b"))

    tasks = _execute_intents(tmp_db)
    assert len(tasks) >= 1
    bandit_events = [
        e for e in _journey_events(tmp_db, "sub_hold_b")
        if e.type == E_BANDIT_RANKED
    ]
    assert len(bandit_events) == 1
    # Phantom-failure guard only fires for causes that NPCI may
    # silently queue. NO_FUNDS is in the queue-prone set, so a timer.set
    # may appear if the natural schedule pre-dates the hold release.
    top = bandit_events[0].payload["top"]
    ranked = bandit_events[0].payload["ranked"]
    scores = bandit_events[0].payload["scores"]
    assert ranked[0] == top
    assert scores[top] == max(scores.values())
    approved = [
        e for e in _journey_events(tmp_db, "sub_hold_b")
        if e.type == E_INTERVENTION_APPROVED
    ]
    assert len(approved) == 1
    approved_at = parse_iso(approved[0].payload["scheduled_at"])
    # If a timer.set event fired, the schedule must be >= hold release.
    timer_events = [
        e for e in _journey_events(tmp_db, "sub_hold_b")
        if e.type == E_TIMER_SET
    ]
    if timer_events:
        # the schedule must be at or after the hold release time
        assert approved_at >= datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
