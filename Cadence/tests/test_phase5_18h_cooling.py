"""PHASE 5 tests: NPCI 18-hour UPI cooling rule + last_retry_at plumbing.

The 18-hour rule is a 9th hard-veto in the Guardian. When a UPI mandate
retry is proposed and the previous successful retry for the same
subscription is within 18h, the Guardian vetoes with reason
"upi_18h_cooling" and defers until the boundary.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from revive.classify.taxonomy import NO_FUNDS, RETRY_LATER, RETRY_NOW, RETRY_PAYDAY
from revive.clock import FakeClock, utc_iso
from revive.config import PolicyConfig
from revive.policy.guardian import JourneyContext, Proposal, evaluate
from revive.policy.preferences import Preferences

BASELINE = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


def _cfg() -> PolicyConfig:
    return PolicyConfig(
        touch_cap_per_window=3,
        touch_window_days=14,
        max_retry_attempts=3,
        quiet_hours_start=21,
        quiet_hours_end=9,
        timezone="Asia/Kolkata",
    )


def _retry_proposal(scheduled_at: str | None = None) -> Proposal:
    return Proposal(
        intervention=RETRY_PAYDAY,
        scheduled_at=scheduled_at or utc_iso(BASELINE),
        amount_minor=49900,
    )


def _ctx(last_retry_at: str | None = None) -> JourneyContext:
    base = JourneyContext(
        journey_id="jrny-5",
        customer_id="cust-5",
        root_cause=NO_FUNDS,
        attempts_used=0,
        touches_used=0,
        window_started_at=utc_iso(BASELINE - timedelta(days=2)),
    )
    if last_retry_at is not None:
        return replace(base, last_retry_at=last_retry_at)
    return base


def test_no_last_retry_at_means_no_18h_check() -> None:
    """If we've never retried before, the 18h rule doesn't apply."""
    clock = FakeClock()
    clock.set(BASELINE)
    d = evaluate(_retry_proposal(), _ctx(None), cfg=_cfg(), clock=clock, kill_switch=False)
    assert d.approved is True
    assert d.reason == "ok"


def test_retry_within_18h_is_vetoed() -> None:
    """Last retry 17h59m ago -> veto, defer_until = last + 18h."""
    clock = FakeClock()
    clock.set(BASELINE)
    last = BASELINE - timedelta(hours=17, minutes=59)
    d = evaluate(
        _retry_proposal(), _ctx(utc_iso(last)),
        cfg=_cfg(), clock=clock, kill_switch=False,
    )
    assert d.approved is False
    assert d.reason == "upi_18h_cooling"
    expected_boundary = last + timedelta(hours=18)
    assert d.defer_until == utc_iso(expected_boundary)


def test_retry_at_exactly_18h_is_approved() -> None:
    """At the 18h boundary the veto flips to approved (boundary is open)."""
    clock = FakeClock()
    clock.set(BASELINE)
    last = BASELINE - timedelta(hours=18)
    d = evaluate(
        _retry_proposal(), _ctx(utc_iso(last)),
        cfg=_cfg(), clock=clock, kill_switch=False,
    )
    assert d.approved is True
    assert d.reason == "ok"


def test_retry_past_18h_is_approved() -> None:
    """After 18h the rule is fully released."""
    clock = FakeClock()
    clock.set(BASELINE)
    last = BASELINE - timedelta(hours=19)
    d = evaluate(
        _retry_proposal(), _ctx(utc_iso(last)),
        cfg=_cfg(), clock=clock, kill_switch=False,
    )
    assert d.approved is True


def test_nudge_interventions_skip_18h_check() -> None:
    """The 18h rule applies to RETRY-class interventions only, not nudges."""
    clock = FakeClock()
    clock.set(BASELINE)
    last = BASELINE - timedelta(hours=1)
    d = evaluate(
        Proposal(intervention="EMAIL_NUDGE", scheduled_at=utc_iso(BASELINE), amount_minor=49900),
        _ctx(utc_iso(last)),
        cfg=_cfg(), clock=clock, kill_switch=False,
    )
    assert d.approved is True


def test_rule_order_kill_switch_wins() -> None:
    """kill_switch fires before upi_18h_cooling."""
    clock = FakeClock()
    clock.set(BASELINE)
    last = BASELINE - timedelta(hours=1)
    d = evaluate(
        _retry_proposal(),
        _ctx(utc_iso(last)),
        cfg=_cfg(),
        clock=clock,
        kill_switch=True,
    )
    assert d.reason == "kill_switch"
