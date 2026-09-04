"""Policy Guardian veto rules: one test per rule plus quiet-hours boundary cases."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from cadence.classify.taxonomy import (
    EMAIL_NUDGE,
    GRACE_OFFER,
    HARD_DECLINE,
    NO_FUNDS,
    RETRY_LATER,
    RETRY_PAYDAY,
    WHATSAPP_NUDGE,
)
from cadence.clock import FakeClock, utc_iso
from cadence.config import PolicyConfig
from cadence.policy.guardian import Decision, JourneyContext, Proposal, evaluate
from cadence.policy.preferences import Preferences

BASELINE = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


def _policy_config() -> PolicyConfig:
    return PolicyConfig(
        touch_cap_per_window=3,
        touch_window_days=14,
        max_retry_attempts=3,
        quiet_hours_start=21,
        quiet_hours_end=9,
        timezone="Asia/Kolkata",
    )


def _proposal(intervention: str = RETRY_PAYDAY, scheduled_at: str | None = None) -> Proposal:
    moment = scheduled_at if scheduled_at is not None else utc_iso(BASELINE)
    return Proposal(intervention=intervention, scheduled_at=moment, amount_minor=49900)


def _context(**overrides: Any) -> JourneyContext:
    base = JourneyContext(
        journey_id="jrny-001",
        customer_id="cust-001",
        root_cause=NO_FUNDS,
        attempts_used=0,
        touches_used=0,
        window_started_at=utc_iso(BASELINE - timedelta(days=2)),
    )
    return replace(base, **overrides)


def _baseline_clock() -> FakeClock:
    clock = FakeClock()
    clock.set(BASELINE)
    return clock


def test_kill_switch_vetoes_any_proposal() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(), _context(), cfg=_policy_config(), clock=clock, kill_switch=True
    )

    assert decision == Decision(approved=False, reason="kill_switch")


def test_dnd_listed_customer_is_vetoed() -> None:
    clock = _baseline_clock()

    decision = evaluate(_proposal(), _context(dnd=True), cfg=_policy_config(), clock=clock)

    assert decision == Decision(approved=False, reason="dnd_listed")


def test_hard_decline_stops_even_a_move_legal_for_other_causes() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(RETRY_PAYDAY),
        _context(root_cause=HARD_DECLINE),
        cfg=_policy_config(),
        clock=clock,
    )

    assert decision == Decision(approved=False, reason="hard_decline_stop")


def test_illegal_intervention_for_root_cause_is_vetoed() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(RETRY_LATER), _context(root_cause=NO_FUNDS), cfg=_policy_config(), clock=clock
    )

    assert decision == Decision(approved=False, reason="illegal_intervention")


def test_mandate_sequence_allows_third_retry_at_sequence_four() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(RETRY_PAYDAY),
        _context(attempts_used=3),
        cfg=_policy_config(),
        clock=clock,
    )

    assert decision.approved is True


def test_mandate_sequence_vetoes_fifth_execution() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(RETRY_PAYDAY),
        _context(attempts_used=4),
        cfg=_policy_config(),
        clock=clock,
    )

    assert decision == Decision(approved=False, reason="mandate_retry_limit_exhausted")


def test_touch_cap_reached_vetoes_even_non_retry_interventions() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(GRACE_OFFER),
        _context(touches_used=3),
        cfg=_policy_config(),
        clock=clock,
    )

    assert decision == Decision(approved=False, reason="touch_cap_reached")


def test_window_expired_beyond_touch_window_days_is_vetoed() -> None:
    clock = _baseline_clock()
    stale_window = utc_iso(BASELINE - timedelta(days=15))

    decision = evaluate(
        _proposal(), _context(window_started_at=stale_window), cfg=_policy_config(), clock=clock
    )

    assert decision == Decision(approved=False, reason="window_expired")


def test_quiet_hours_whatsapp_nudge_is_approved_with_deferral_to_next_quiet_end() -> None:
    clock = FakeClock()
    clock.set(datetime(2026, 8, 22, 16, 30, tzinfo=UTC))
    expected_defer_until = utc_iso(datetime(2026, 8, 23, 3, 30, tzinfo=UTC))

    decision = evaluate(
        _proposal(WHATSAPP_NUDGE), _context(), cfg=_policy_config(), clock=clock
    )

    assert decision == Decision(
        approved=True, reason="quiet_hours_deferred", defer_until=expected_defer_until
    )


def test_quiet_hours_boundary_at_quiet_end_local_time_approves_normally() -> None:
    clock = FakeClock()
    clock.set(datetime(2026, 8, 22, 3, 30, tzinfo=UTC))

    decision = evaluate(
        _proposal(WHATSAPP_NUDGE), _context(), cfg=_policy_config(), clock=clock
    )

    assert decision == Decision(approved=True, reason="ok", conditions=())


def test_retry_without_predebit_notification_carries_rbi_notify_condition() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(RETRY_PAYDAY),
        _context(predebit_notified=False),
        cfg=_policy_config(),
        clock=clock,
    )

    assert decision == Decision(
        approved=True, reason="ok", conditions=("predebit_notify_rbi_24h",)
    )


def test_small_amount_after_repeated_attempts_hits_cost_ceiling() -> None:
    clock = _baseline_clock()
    cheap = Proposal(
        intervention=RETRY_PAYDAY, scheduled_at=utc_iso(BASELINE), amount_minor=9_900
    )

    decision = evaluate(cheap, _context(attempts_used=2), cfg=_policy_config(), clock=clock)

    assert decision == Decision(approved=False, reason="cost_ceiling")


def test_small_amount_before_the_cost_ceiling_attempt_threshold_still_passes() -> None:
    clock = _baseline_clock()
    cheap = Proposal(
        intervention=RETRY_PAYDAY, scheduled_at=utc_iso(BASELINE), amount_minor=9_900
    )

    decision = evaluate(cheap, _context(attempts_used=1), cfg=_policy_config(), clock=clock)

    assert decision == Decision(
        approved=True, reason="ok", conditions=("predebit_notify_rbi_24h",)
    )


def test_retry_with_predebit_already_notified_has_no_conditions() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(RETRY_PAYDAY),
        _context(predebit_notified=True),
        cfg=_policy_config(),
        clock=clock,
    )

    assert decision == Decision(approved=True, reason="ok", conditions=())


EMAIL_ONLY = Preferences(
    customer_id="cust-001",
    allowed_channels=("email",),
    preferred_window_start=0,
    preferred_window_end=24,
)


def test_nudge_on_disallowed_channel_is_vetoed_as_channel_not_preferred() -> None:
    clock = _baseline_clock()

    decision = evaluate(
        _proposal(WHATSAPP_NUDGE), _context(), cfg=_policy_config(), clock=clock,
        prefs=EMAIL_ONLY,
    )

    assert decision == Decision(approved=False, reason="channel_not_preferred")


def test_outside_preferred_window_defers_to_window_start_instead_of_quiet_hours() -> None:
    # 10:00 UTC == 15:30 IST: outside the 18-21 preference window but ALSO outside
    # cfg quiet hours (21-09) - deferral proves the preference window governs.
    clock = FakeClock()
    clock.set(datetime(2026, 8, 22, 10, 0, tzinfo=UTC))
    expected_defer_until = utc_iso(datetime(2026, 8, 22, 12, 30, tzinfo=UTC))
    evenings = Preferences(
        customer_id="cust-001",
        allowed_channels=("email",),
        preferred_window_start=18,
        preferred_window_end=21,
    )

    decision = evaluate(
        _proposal(EMAIL_NUDGE), _context(), cfg=_policy_config(), clock=clock,
        prefs=evenings,
    )

    assert decision == Decision(
        approved=True, reason="quiet_hours_deferred", defer_until=expected_defer_until
    )
