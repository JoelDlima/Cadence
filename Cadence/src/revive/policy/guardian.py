"""Policy Guardian: deterministic veto layer between any proposal and any action.

Encodes the compliance and product guardrails from the implementation plan:
kill switch, DND list, hard-decline stop, legality matrix, retry-attempt cap,
touch cap per rolling window, quiet hours (defer to next quiet-hours-end local),
customer channel preferences (backlog item 9: disallowed channel vetoes, preferred
window replaces cfg quiet hours for nudges), and the RBI 24h pre-debit
notification condition before any retry. All logic is pure: no I/O, no logging,
fully clock-injected for deterministic tests.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta

from revive.classify.taxonomy import (
    EMAIL_NUDGE,
    HARD_DECLINE,
    RETRY_NOW,
    WHATSAPP_NUDGE,
    legal_moves,
)
from revive.clock import Clock, parse_iso, utc_iso
from revive.config import PolicyConfig
from revive.policy.preferences import Preferences

__all__ = ["Decision", "JourneyContext", "Proposal", "evaluate"]

PREDEBIT_NOTIFY_CONDITION: str = "predebit_notify_rbi_24h"
_COST_CEILING_REASON = "cost_ceiling"
_COST_CEILING_MIN_ATTEMPTS = 2
_CHANNEL_NOT_PREFERRED_REASON = "channel_not_preferred"
_QUIET_HOURS_INTERVENTIONS: frozenset[str] = frozenset(
    {WHATSAPP_NUDGE, EMAIL_NUDGE, RETRY_NOW}
)
_CHANNEL_BY_INTERVENTION: dict[str, str] = {
    WHATSAPP_NUDGE: "whatsapp",
    EMAIL_NUDGE: "email",
}


@dataclass(frozen=True)
class Proposal:
    intervention: str
    scheduled_at: str
    amount_minor: int = 0


@dataclass(frozen=True)
class JourneyContext:
    journey_id: str
    customer_id: str
    root_cause: str
    attempts_used: int
    touches_used: int
    window_started_at: str | None
    dnd: bool = False
    predebit_notified: bool = False
    last_retry_at: str | None = None  # PHASE 5: NPCI 18h UPI cooling


_NPCI_UPI_18H = timedelta(hours=18)


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str
    defer_until: str | None = None
    conditions: tuple[str, ...] = ()


def _is_retry(intervention: str) -> bool:
    return intervention.startswith("RETRY")


def _window_expired(ctx: JourneyContext, *, cfg: PolicyConfig, clock: Clock) -> bool:
    if ctx.window_started_at is None:
        return False
    started = parse_iso(ctx.window_started_at)
    return clock.now() - started > timedelta(days=cfg.touch_window_days)


def _in_quiet_hours(clock: Clock, cfg: PolicyConfig) -> bool:
    local_hour: int = clock.in_tz(cfg.timezone).hour
    return local_hour >= cfg.quiet_hours_start or local_hour < cfg.quiet_hours_end


def _next_quiet_end_utc(now: datetime, cfg: PolicyConfig) -> str:
    """ISO UTC of the next cfg.quiet_hours_end:00 local moment strictly after `now`."""
    local_now = now.astimezone(zoneinfo.ZoneInfo(cfg.timezone))
    candidate = local_now.replace(hour=cfg.quiet_hours_end, minute=0, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return utc_iso(candidate)


def _disallowed_channel(proposal: Proposal, prefs: Preferences) -> str | None:
    """Channel name when the proposal targets a channel the customer opted out of."""
    channel = _CHANNEL_BY_INTERVENTION.get(proposal.intervention)
    if channel is not None and channel not in prefs.allowed_channels:
        return channel
    return None


def _hour_in_window(hour: int, *, start: int, end: int) -> bool:
    """Membership in [start, end) IST hours; a wrapping window (start > end) spans
    midnight, and start == end means the whole day is contactable."""
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _in_preferred_window(clock: Clock, cfg: PolicyConfig, prefs: Preferences) -> bool:
    local_hour: int = clock.in_tz(cfg.timezone).hour
    return _hour_in_window(
        local_hour,
        start=prefs.preferred_window_start,
        end=prefs.preferred_window_end,
    )


def _next_preferred_start_utc(now: datetime, cfg: PolicyConfig, prefs: Preferences) -> str:
    """ISO UTC of the next preferred-window start:00 local moment strictly after now."""
    local_now = now.astimezone(zoneinfo.ZoneInfo(cfg.timezone))
    candidate = local_now.replace(
        hour=prefs.preferred_window_start, minute=0, second=0, microsecond=0
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return utc_iso(candidate)


def _hard_veto(
    proposal: Proposal,
    ctx: JourneyContext,
    *,
    cfg: PolicyConfig,
    clock: Clock,
    kill_switch: bool,
    prefs: Preferences | None,
) -> Decision | None:
    """Veto rules 1-8 in fixed order; first hit wins. None means continue evaluating."""
    if kill_switch:
        return Decision(approved=False, reason="kill_switch")
    if ctx.dnd:
        return Decision(approved=False, reason="dnd_listed")
    if prefs is not None and _disallowed_channel(proposal, prefs) is not None:
        return Decision(approved=False, reason=_CHANNEL_NOT_PREFERRED_REASON)
    if ctx.root_cause == HARD_DECLINE:
        return Decision(approved=False, reason="hard_decline_stop")
    if proposal.intervention not in legal_moves(ctx.root_cause):
        return Decision(approved=False, reason="illegal_intervention")
    if (
        proposal.amount_minor < cfg.min_recovery_worth_minor
        and ctx.attempts_used >= _COST_CEILING_MIN_ATTEMPTS
    ):
        return Decision(approved=False, reason=_COST_CEILING_REASON)
    if _is_retry(proposal.intervention) and ctx.attempts_used >= cfg.max_retry_attempts:
        return Decision(approved=False, reason="attempts_exhausted")
    # PHASE 5: NPCI 18-hour cooling rule. UPI mandates cannot be retried
    # on the same VPA within 18 hours; this vetoes any retry whose last
    # attempt is within the window and defers it to the boundary. The
    # first attempt of the day is always allowed (no last_retry_at yet).
    if (
        _is_retry(proposal.intervention)
        and ctx.last_retry_at is not None
    ):
        last = parse_iso(ctx.last_retry_at)
        boundary = last + _NPCI_UPI_18H
        if clock.now() < boundary:
            return Decision(
                approved=False,
                reason="upi_18h_cooling",
                defer_until=utc_iso(boundary),
            )
    if ctx.touches_used >= cfg.touch_cap_per_window:
        return Decision(approved=False, reason="touch_cap_reached")
    if _window_expired(ctx, cfg=cfg, clock=clock):
        return Decision(approved=False, reason="window_expired")
    return None


def _approve(proposal: Proposal, ctx: JourneyContext) -> Decision:
    conditions: tuple[str, ...] = ()
    if _is_retry(proposal.intervention) and not ctx.predebit_notified:
        conditions = (PREDEBIT_NOTIFY_CONDITION,)
    return Decision(approved=True, reason="ok", conditions=conditions)


def _tier_reason(amount_minor: int, *, cfg: PolicyConfig) -> str | None:
    """Human-approval tier for an otherwise-approved proposal; None = auto-approve."""
    if amount_minor >= cfg.require_human_above_minor:
        return "finance_approval_required"
    if amount_minor > cfg.auto_approve_below_minor:
        return "manager_approval_required"
    return None


def evaluate(
    proposal: Proposal,
    ctx: JourneyContext,
    *,
    cfg: PolicyConfig,
    clock: Clock,
    kill_switch: bool = False,
    prefs: Preferences | None = None,
) -> Decision:
    vetoed = _hard_veto(
        proposal, ctx, cfg=cfg, clock=clock, kill_switch=kill_switch, prefs=prefs
    )
    if vetoed is not None:
        return vetoed
    if proposal.intervention in _CHANNEL_BY_INTERVENTION and prefs is not None:
        if not _in_preferred_window(clock, cfg, prefs):
            return Decision(
                approved=True,
                reason="quiet_hours_deferred",
                defer_until=_next_preferred_start_utc(clock.now(), cfg, prefs),
                conditions=(),
            )
    elif proposal.intervention in _QUIET_HOURS_INTERVENTIONS and _in_quiet_hours(clock, cfg):
        return Decision(
            approved=True,
            reason="quiet_hours_deferred",
            defer_until=_next_quiet_end_utc(clock.now(), cfg),
            conditions=(),
        )
    tier_reason = _tier_reason(proposal.amount_minor, cfg=cfg)
    if tier_reason is not None:
        return Decision(approved=False, reason=tier_reason)
    return _approve(proposal, ctx)
