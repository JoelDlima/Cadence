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
def test_engine_degrades_to_retry_later_during_cause_outage(
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

    # ...and the journey was approved, not stranded in human review: the
    # cause's own outage-safe retry is not logged as a veto against itself
    # (that would misrepresent an approved action as blocked).
    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "sub_new")
    vetoes = [e for e in events if e.type == E_INTERVENTION_VETOED]
    assert vetoes == []
    approvals = [e for e in events if e.type == "intervention.approved"]
    assert len(approvals) == 1
    assert approvals[0].payload["intervention"] == RETRY_LATER


@pytest.mark.integration
def test_no_funds_outage_pause_still_approves_retry_payday_not_human_review(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """Regression: NO_FUNDS has no RETRY_LATER legal move, so pausing on
    RETRY_LATER alone left every NO_FUNDS journey with zero legal moves during
    a detected outage and it dead-ended in HUMAN_REVIEW with no audit trail
    explaining why. The cause's own retry (RETRY_PAYDAY) must be offered
    instead, and every other candidate the pause skips must still be
    recorded as a veto."""
    store = EventStore(tmp_db)
    for i in range(5):
        moment = utc_iso(fake_clock.now() - timedelta(minutes=30) + timedelta(seconds=i))
        store.append(
            event_type=E_PAYMENT_FAILED,
            aggregate_type=AGG_JOURNEY,
            aggregate_id=f"sub_seed_nf_{i}",
            payload={"failure_code": "insufficient_funds"},
            occurred_at=moment,
            recorded_at=moment,
            event_id=f"pf_seed_nf_{i}",
        )
    engine = _engine(tmp_db, fake_clock)
    engine.handle_payment_failed({
        "subscription_id": "sub_nf_target",
        "customer_id": "cust_nf_target",
        "failure_code": "insufficient_funds",
        "error_description": "Insufficient funds",
        "amount_minor": 49900,
        "currency": "INR",
    })

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_nf_target")
    assert journey is not None
    assert journey.state == "INTERVENING"

    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "sub_nf_target")
    approvals = [e for e in events if e.type == "intervention.approved"]
    assert len(approvals) == 1
    assert approvals[0].payload["intervention"] == "RETRY_PAYDAY"

    # RETRY_PAYDAY is ranked #1 for NO_FUNDS, so the loop approves it on the
    # first candidate and never evaluates (let alone vetoes) the rest.
    vetoes = [e for e in events if e.type == E_INTERVENTION_VETOED]
    assert vetoes == []


@pytest.mark.integration
def test_outage_pause_audits_a_candidate_ranked_ahead_of_the_safe_retry(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    """When a higher-ranked candidate is not the cause's outage-safe retry,
    the pause must record why it was skipped rather than silently continuing
    past it — the original silent-skip is what let NO_FUNDS journeys dead-end
    into HUMAN_REVIEW with zero audit trail."""
    from cadence.agents.planner import DiagnosisProposal, PlannerProposal

    class _StubPlanner:
        def diagnose(self, *, failure_context, attempt_no):
            return DiagnosisProposal(
                root_cause=BANK_DOWN, confidence=0.9, rationale="stub diagnosis",
            )

        def propose(self, *, root_cause, legal_moves, failure_context, attempt_no):
            return PlannerProposal(
                intervention="RETRY_NOW", delay_hours=0.0, rationale="stub proposal",
            )

    _seed_bank_failures(tmp_db, 5, fake_clock.now() - timedelta(minutes=30))
    engine = RecoveryEngine(
        db=tmp_db,
        event_store=EventStore(tmp_db),
        journeys=JourneyRepo(tmp_db),
        queue=QueueRepo(tmp_db),
        cfg=_policy_config(),
        clock=fake_clock,
        planner=_StubPlanner(),
    )
    # An unrecognized failure code classifies UNKNOWN, which routes through
    # the stub planner: diagnosed as BANK_DOWN, with RETRY_NOW proposed and
    # prepended ahead of the bandit ranking. RETRY_NOW is a legal BANK_DOWN
    # move but not the outage-safe retry, so it must be skipped-and-audited
    # before RETRY_LATER is reached and approved.
    engine.handle_payment_failed({
        "subscription_id": "sub_planner_target",
        "customer_id": "cust_planner_target",
        "failure_code": "totally_unrecognized_code",
        "error_description": "",
        "amount_minor": 49900,
        "currency": "INR",
    })

    events = EventStore(tmp_db).get_by_aggregate(AGG_JOURNEY, "sub_planner_target")
    vetoes = [e for e in events if e.type == E_INTERVENTION_VETOED]
    assert any(
        v.payload["intervention"] == "RETRY_NOW" and v.payload["reason"] == "cause_outage_pause"
        for v in vetoes
    )
    approvals = [e for e in events if e.type == "intervention.approved"]
    assert len(approvals) == 1
    assert approvals[0].payload["intervention"] == RETRY_LATER
