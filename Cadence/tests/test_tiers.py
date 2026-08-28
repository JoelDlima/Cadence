"""Amount-tiered human approval tiers (research adoption): auto / manager / finance."""

import pytest

from revive.clock import FakeClock
from revive.config import PolicyConfig
from revive.journey.engine import RecoveryEngine
from revive.policy.guardian import JourneyContext, Proposal, evaluate
from revive.store.event_store import EventStore
from revive.store.journey_repo import STATE_HUMAN_REVIEW, JourneyRepo
from revive.store.queue_repo import QueueRepo


def _cfg() -> PolicyConfig:
    return PolicyConfig(
        touch_cap_per_window=3,
        touch_window_days=14,
        max_retry_attempts=3,
        quiet_hours_start=21,
        quiet_hours_end=9,
        timezone="Asia/Kolkata",
        auto_approve_below_minor=500_000,
        require_human_above_minor=5_000_000,
    )


def _ctx(amount_minor: int) -> JourneyContext:
    return JourneyContext(
        journey_id="j_t",
        customer_id="c_t",
        root_cause="NO_FUNDS",
        attempts_used=0,
        touches_used=0,
        window_started_at=None,
    )


def _prop(amount_minor: int) -> Proposal:
    return Proposal(
        intervention="RETRY_PAYDAY", scheduled_at="2026-08-25T04:30:00+00:00",
        amount_minor=amount_minor,
    )


@pytest.mark.unit
def test_auto_approve_below_tier_has_no_condition_change():
    d = evaluate(_prop(499_000), _ctx(499_000), cfg=_cfg(), clock=FakeClock())
    assert d.approved is True


@pytest.mark.unit
def test_mid_tier_requires_manager_approval():
    d = evaluate(_prop(2_000_000), _ctx(2_000_000), cfg=_cfg(), clock=FakeClock())
    assert d.approved is False
    assert d.reason == "manager_approval_required"


@pytest.mark.unit
def test_top_tier_requires_finance_approval():
    d = evaluate(_prop(6_000_000), _ctx(6_000_000), cfg=_cfg(), clock=FakeClock())
    assert d.approved is False
    assert d.reason == "finance_approval_required"


@pytest.mark.integration
def test_engine_routes_large_amount_to_human_review(tmp_db, fake_clock):
    store = EventStore(tmp_db)
    journeys = JourneyRepo(tmp_db)
    queue = QueueRepo(tmp_db)
    engine = RecoveryEngine(tmp_db, store, journeys, queue, _cfg(), fake_clock)
    before_events = store.count()
    before_tasks = queue.pending_count()
    engine.handle_payment_failed(
        {
            "subscription_id": "sub_big",
            "customer_id": "cust_big",
            "failure_code": "insufficient_funds",
            "error_description": "insufficient balance",
            "amount_minor": 6_000_000,
            "currency": "INR",
        }
    )
    journey = journeys.get_by_subscription("sub_big")
    assert journey is not None
    assert journey.state == STATE_HUMAN_REVIEW
    assert queue.pending_count() - before_tasks == 0
    assert store.count() > before_events
