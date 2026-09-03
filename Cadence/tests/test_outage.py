"""Bank-outage circuit breaker: pure spike detection + engine degradation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from cadence.classify.taxonomy import BANK_DOWN, NO_FUNDS, RETRY_LATER
from cadence.clock import FakeClock, parse_iso, utc_iso
from cadence.config import PolicyConfig
from cadence.events import AGG_JOURNEY, E_INTERVENTION_VETOED, E_PAYMENT_FAILED
from cadence.journey.engine import RecoveryEngine
from cadence.policy.outage import detect_cause_outage
from cadence.store.db import Database
from cadence.store.event_store import EventStore
from cadence.store.journey_repo import JourneyRepo
from cadence.store.queue_repo import QueueRepo

pytestmark = [pytest.mark.unit]


# --- pure function -------------------------------------------------------------


def test_empty_history_means_no_outage() -> None:
    assert detect_cause_outage(recent_failure_causes=[], cause=BANK_DOWN) is False


def test_below_threshold_is_not_an_outage() -> None:
    causes = [BANK_DOWN] * 4

    assert detect_cause_outage(recent_failure_causes=causes, cause=BANK_DOWN) is False


def test_at_threshold_is_an_outage() -> None:
    causes = [BANK_DOWN] * 5

    assert detect_cause_outage(recent_failure_causes=causes, cause=BANK_DOWN) is True


def test_above_threshold_is_an_outage() -> None:
    causes = [BANK_DOWN] * 7

    assert detect_cause_outage(recent_failure_causes=causes, cause=BANK_DOWN) is True


def test_other_causes_do_not_count_toward_the_spike() -> None:
    causes = [BANK_DOWN] * 5 + [NO_FUNDS] * 3

    assert detect_cause_outage(recent_failure_causes=causes, cause=NO_FUNDS) is False
    assert detect_cause_outage(recent_failure_causes=causes, cause=BANK_DOWN) is True


def test_custom_threshold_and_window_are_honored() -> None:
    causes = [NO_FUNDS, NO_FUNDS]

    assert (
        detect_cause_outage(
            recent_failure_causes=causes, cause=NO_FUNDS, window_minutes=60, threshold=2
        )
        is True
    )
    assert (
        detect_cause_outage(
            recent_failure_causes=causes, cause=NO_FUNDS, window_minutes=60, threshold=3
        )
        is False
    )


# --- engine integration --------------------------------------------------------


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


def _seed_bank_failures(db: Database, count: int, at: datetime) -> None:
    store = EventStore(db)
    for i in range(count):
        moment = utc_iso(at + timedelta(seconds=i))
        store.append(
            event_type=E_PAYMENT_FAILED,
            aggregate_type=AGG_JOURNEY,
            aggregate_id=f"sub_seed_{i}",
            payload={"failure_code": "bank_technical_error"},
            occurred_at=moment,
            recorded_at=moment,
            event_id=f"pf_seed_{i}",
        )


@pytest.mark.integration
def test_engine_degrades_to_retry_later_with_veto_event_during_cause_outage(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    # Arrange: 5 prior BANK_DOWN failures across other journeys within the window.
    _seed_bank_failures(tmp_db, 5, fake_clock.now() - timedelta(minutes=30))
    engine = _engine(tmp_db, fake_clock)
    payload: dict[str, Any] = {
        "subscription_id": "sub_new",
        "customer_id": "cust_new",
        "failure_code": "bank_technical_error",
        "error_description": "bank downtime",
        "amount_minor": 49900,
        "currency": "INR",
    }

    # Act
    engine.handle_payment_failed(payload)

    # Assert: the scheduled intervention degraded to a +6h RETRY_LATER...
    rows = tmp_db.conn.execute(
        "SELECT payload, available_at FROM task_queue WHERE task_type='execute_intervention'"
    ).fetchall()
    assert len(rows) == 1
    task_payload: dict[str, Any] = json.loads(str(rows[0]["payload"]))
    assert task_payload["intervention"] == RETRY_LATER
    assert task_payload["subscription_id"] == "sub_new"
    assert parse_iso(str(rows[0]["available_at"])) == datetime(
        2026, 8, 23, 4, 30, tzinfo=UTC
    )

    # ...and the pause is on the record as a guardian-style veto event.
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "sub_new")
    vetoes = [e for e in events if e.type == E_INTERVENTION_VETOED]
    assert [v.payload["reason"] for v in vetoes] == ["cause_outage_pause"]
