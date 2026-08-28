"""Recovery journey engine: turns payment-failure webhooks into governed interventions.

Deterministic spine, probabilistic edges: classification -> preferred legal
intervention -> Policy Guardian veto/approval -> durable executor task (a timer
when scheduled in the future). Every state change is an appended, hash-chained
event; the journeys table is kept in sync as a rebuildable projection.

Known failure codes ride the pure-code fast path (zero LLM tokens). Only an
UNCLASSIFIABLE code escalates: sticky diagnosis (this journey's already-
confirmed cause) -> LLM diagnoser (taxonomy-bounded, Guardian-vetoed) ->
NEEDS_HUMAN. The LLM can therefore only ever name a legal cause and a legal
intervention - compliance never depends on the model behaving.

Save-offer ladder (2026 studies: pause offers convert 15-25% of cancels;
retention sequences hit a 34% median save rate). A journey escalates:
recovery attempts -> 7-day save-offer grace -> CLOSED_UNRECOVERED. When a
closing veto fires (touch cap / window expired / attempts exhausted), the
engine arms one save strike - a TASK_HANDLE_PAYMENT_FAILED timer at now+7d -
instead of closing. Only if that save attempt ALSO fails (caps still exceeded,
idempotency key already seen) does the close path trigger: a natural
two-strike design. HARD_DECLINE and DND journeys still close immediately.
"""

from __future__ import annotations

import json
import zlib
import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from revive.agents.planner import PlannerAgent
from revive.classify.classifier import (
    SOURCE_LLM,
    SOURCE_STICKY,
    Classification,
    classify,
)
from revive.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    EMAIL_NUDGE,
    EXPIRED_INSTRUMENT,
    GRACE_OFFER,
    HARD_DECLINE,
    NO_FUNDS,
    PAYMENT_LINK,
    RETRY_LATER,
    RETRY_PAYDAY,
    ROOT_CAUSES,
    SWITCH_METHOD,
    TIMEOUT,
    UNKNOWN,
    WHATSAPP_NUDGE,
    legal_moves,
)
from revive.clock import Clock, parse_iso, utc_iso
from revive.config import PolicyConfig
from revive.events import (
    AGG_JOURNEY,
    E_ACTION_EXECUTED,
    E_CLASSIFICATION_COMPLETED,
    E_INTERVENTION_APPROVED,
    E_INTERVENTION_PROPOSED,
    E_INTERVENTION_VETOED,
    E_JOURNEY_CLOSED,
    E_JOURNEY_OPENED,
    E_JOURNEY_STATE_CHANGED,
    E_PAYMENT_FAILED,
    E_TIMER_SET,
)
from revive.executors.contracts import TASK_EXECUTE_INTENT, TASK_HANDLE_PAYMENT_FAILED
from revive.journey.fsm import (
    EVENT_ACTION_EXECUTED,
    EVENT_APPROVED,
    EVENT_CLASSIFIED,
    EVENT_NEEDS_HUMAN,
    EVENT_RECOVERED,
    IllegalTransition,
    is_terminal,
    transition,
)
from revive.policy.guardian import (
    PREDEBIT_NOTIFY_CONDITION,
    Decision,
    JourneyContext,
    Proposal,
    evaluate,
)
from revive.policy.outage import detect_cause_outage
from revive.policy.timing import hold_release_shift, next_contactable_moment, retry_delay_for_cause
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import (
    STATE_CLOSED_UNRECOVERED,
    STATE_HUMAN_REVIEW,
    STATE_INTERVENING,
    Journey,
    JourneyRepo,
)
from revive.store.queue_repo import QueueRepo

FAST_PATH_PREFERENCE: dict[str, tuple[str, ...]] = {
    NO_FUNDS: (RETRY_PAYDAY, GRACE_OFFER, WHATSAPP_NUDGE),
    BANK_DOWN: (RETRY_LATER, EMAIL_NUDGE),
    TIMEOUT: (RETRY_LATER, PAYMENT_LINK, EMAIL_NUDGE),
    CUSTOMER_ABORTED: (PAYMENT_LINK, WHATSAPP_NUDGE),
    BAD_VPA: (SWITCH_METHOD, EMAIL_NUDGE),
    EXPIRED_INSTRUMENT: (SWITCH_METHOD, EMAIL_NUDGE),
    UNKNOWN: (),
    HARD_DECLINE: (),
}

_CLOSING_VETO_REASONS: frozenset[str] = frozenset(
    {"touch_cap_reached", "window_expired", "attempts_exhausted", "dnd_listed"}
)
_HUMAN_REVIEW_VETO_REASONS: frozenset[str] = frozenset(
    {"manager_approval_required", "finance_approval_required"}
)
_KILL_SWITCH_REASON = "kill_switch"
_HARD_DECLINE_REASON = "hard_decline"
_NO_VIABLE_MOVE_REASON = "no_viable_move"
_CAUSE_OUTAGE_REASON = "cause_outage_pause"
_PAYDAY_WEEKDAYS = (0, 4)  # Monday / Friday paydays
_RUN_HOUR = 10  # 10:00 local for payday retries and quiet-hour exits
_OUTAGE_WINDOW_MINUTES = 1440
_SAVE_GRACE_PERIOD = timedelta(days=7)
_SAVE_OFFER_DETAIL = "grace 7d then pause offer"
_SAVE_WINDOW_DESCRIPTION = "save window expiry"
# Causes whose debits NPCI may silently queue inside peak-hold windows.
_PHANTOM_GUARD_CAUSES: frozenset[str] = frozenset({TIMEOUT, BANK_DOWN, NO_FUNDS})
_HOLD_RELEASE_REASON = "npci_peak_hold_release"
# Causes a sticky/LLM diagnosis may land on. HARD_DECLINE is deliberately
# excluded: stopping recovery is a human call, never the model's.
_STICKY_CAUSES: frozenset[str] = frozenset(ROOT_CAUSES) - {UNKNOWN, HARD_DECLINE}
_CAPTURED_REASON = "payment_captured"


def _failure_root_cause(payload: dict[str, Any]) -> str:
    """Root cause of a recorded payment.failed event (explicit field or reclassified)."""
    explicit = payload.get("root_cause")
    if explicit in ROOT_CAUSES:
        return str(explicit)
    return classify(payload.get("failure_code"), payload.get("error_description")).root_cause


def _llm_failure_context(payload: dict[str, Any]) -> dict[str, Any]:
    """What the LLM may see about a failure: the failure itself, no identities.

    customer_id / subscription_id / payment ids never leave the process.
    """
    return {
        key: payload[key]
        for key in ("failure_code", "error_description", "amount_minor", "currency")
        if payload.get(key) is not None
    }


def _failure_moment(payload: dict[str, Any], fallback: datetime) -> datetime:
    """Aware UTC moment the debit originally failed (webhook time as fallback)."""
    raw = payload.get("occurred_at")
    if not isinstance(raw, str):
        return fallback
    try:
        parsed = parse_iso(raw)
    except ValueError:
        return fallback
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _advance(state: str, event: str) -> str:
    """Apply an FSM edge; mid-flight states without that edge simply stay put."""
    try:
        return transition(state, event)
    except IllegalTransition:
        return state


def _is_quiet_hour(hour: int, cfg: PolicyConfig) -> bool:
    return hour >= cfg.quiet_hours_start or hour < cfg.quiet_hours_end


def _next_payday(moment: datetime, tz_name: str) -> datetime:
    """Next Mon/Fri at _RUN_HOUR local time, strictly after `moment`."""
    local = moment.astimezone(zoneinfo.ZoneInfo(tz_name))
    candidate = local.replace(hour=_RUN_HOUR, minute=0, second=0, microsecond=0)
    while candidate.weekday() not in _PAYDAY_WEEKDAYS or candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def _next_local_run_hour(moment: datetime, tz_name: str) -> datetime:
    """Next _RUN_HOUR:00 local time, strictly after `moment`."""
    local = moment.astimezone(zoneinfo.ZoneInfo(tz_name))
    candidate = local.replace(hour=_RUN_HOUR, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def _retry_seed(subscription_id: str) -> int:
    """Stable per-subscription seed for retry timing (keeps sims reproducible)."""
    return zlib.crc32(subscription_id.encode("utf-8"))


def _schedule(
    intervention: str,
    cause: str,
    attempt_no: int,
    sub_id: str,
    now: datetime,
    cfg: PolicyConfig,
) -> datetime:
    """Aware UTC fire time for a fast-path intervention, contactability-checked.

    RETRY_LATER delays come from the evidence-based per-cause timing table
    (replacing the old flat +6h); every scheduled moment is passed through
    next_contactable_moment so holidays, NPCI maintenance, and any residual
    quiet-hours overlap defer to the next morning. Payday logic is intact.
    """
    tz_name = cfg.timezone
    if intervention == RETRY_PAYDAY:
        return next_contactable_moment(_next_payday(now, tz_name), tz_name)
    if intervention == RETRY_LATER:
        delay = retry_delay_for_cause(cause, attempt_no, _retry_seed(sub_id))
        candidate = now + delay
        local_hour = candidate.astimezone(zoneinfo.ZoneInfo(tz_name)).hour
        if _is_quiet_hour(local_hour, cfg):
            candidate = _next_local_run_hour(candidate, tz_name)
        return next_contactable_moment(candidate, tz_name)
    return next_contactable_moment(now, tz_name)


class RecoveryEngine:
    def __init__(
        self,
        db: Database,
        event_store: EventStore,
        journeys: JourneyRepo,
        queue: QueueRepo,
        cfg: PolicyConfig,
        clock: Clock,
        planner: PlannerAgent | None = None,
    ) -> None:
        self._db = db
        self._event_store = event_store
        self._journeys = journeys
        self._queue = queue
        self._cfg = cfg
        self._clock = clock
        self._planner = planner

    def handle_payment_failed(self, payload: dict[str, Any]) -> None:
        """Fast path: open/refresh the journey, classify, govern, dispatch one move."""
        sub_id = str(payload["subscription_id"])
        journey = self._journeys.get_by_subscription(sub_id)
        if journey is not None and is_terminal(journey.state):
            return
        now = self._clock.now()
        now_iso = utc_iso(now)
        if journey is None:
            journey = self._open_journey(payload, sub_id=sub_id, now_iso=now_iso)
        classification = classify(payload.get("failure_code"), payload.get("error_description"))
        attempt_no = journey.attempts_used + 1
        self._append(
            E_CLASSIFICATION_COMPLETED,
            sub_id,
            {
                "root_cause": classification.root_cause,
                "source": classification.source,
                "confidence": classification.confidence,
                "matched_code": classification.matched_code,
                "attempt_no": attempt_no,
            },
            now_iso,
        )
        journey_state = _advance(journey.state, EVENT_CLASSIFIED)
        planner_intervention: str | None = None
        if classification.root_cause == UNKNOWN:
            reclassified = self._resolve_unknown(
                journey, payload, attempt_no=attempt_no, now_iso=now_iso
            )
            if reclassified is None:
                self._route_needs_human(journey, classification, journey.state, now_iso)
                return
            classification = reclassified
            if classification.source == SOURCE_LLM:
                planner_intervention = self._planner_intervention(
                    payload, classification, attempt_no=attempt_no, now_iso=now_iso
                )
        if classification.root_cause == HARD_DECLINE:
            self._close_journey(
                journey.journey_id, sub_id, classification, _HARD_DECLINE_REASON, now_iso
            )
            return
        self._dispatch_fast_path(
            journey,
            sub_id=sub_id,
            classification=classification,
            journey_state=journey_state,
            attempt_no=attempt_no,
            amount_minor=int(journey.amount_minor or 0),
            failure_occurred=_failure_moment(payload, now),
            now=now,
            now_iso=now_iso,
            planner_intervention=planner_intervention,
        )

    def _resolve_unknown(
        self,
        journey: Journey,
        payload: dict[str, Any],
        *,
        attempt_no: int,
        now_iso: str,
    ) -> Classification | None:
        """Escalation ladder for unclassifiable failures: sticky -> LLM -> human.

        Returns the diagnosis to ride the fast path with, or None for
        NEEDS_HUMAN. Every rung appends its own audited classification event.
        """
        sub_id = str(payload["subscription_id"])
        if journey.root_cause in _STICKY_CAUSES:
            # Repeat unknown codes on a diagnosed journey (unpaid link, ignored
            # nudge, replayed gateway error) keep the original diagnosis.
            sticky = Classification(
                root_cause=str(journey.root_cause),
                source=SOURCE_STICKY,
                confidence=0.8,
                matched_code=None,
            )
            self._append(
                E_CLASSIFICATION_COMPLETED,
                sub_id,
                {
                    "root_cause": sticky.root_cause,
                    "source": SOURCE_STICKY,
                    "confidence": sticky.confidence,
                    "matched_code": None,
                    "prior_root_cause": journey.root_cause,
                    "attempt_no": attempt_no,
                },
                now_iso,
            )
            return sticky
        if self._planner is None:
            return None
        diagnosis = self._planner.diagnose(
            failure_context=_llm_failure_context(payload), attempt_no=attempt_no
        )
        if diagnosis is None:
            self._append(
                E_CLASSIFICATION_COMPLETED,
                sub_id,
                {
                    "root_cause": UNKNOWN,
                    "source": SOURCE_LLM,
                    "confidence": 0.0,
                    "matched_code": None,
                    "rationale": "diagnosis unavailable; escalating to human",
                    "attempt_no": attempt_no,
                },
                now_iso,
            )
            return None
        diagnosed = Classification(
            root_cause=diagnosis.root_cause,
            source=SOURCE_LLM,
            confidence=diagnosis.confidence,
            matched_code=None,
        )
        self._append(
            E_CLASSIFICATION_COMPLETED,
            sub_id,
            {
                "root_cause": diagnosed.root_cause,
                "source": SOURCE_LLM,
                "confidence": diagnosed.confidence,
                "matched_code": None,
                "rationale": diagnosis.rationale,
                "provider": diagnosis.provider,
                "attempt_no": attempt_no,
            },
            now_iso,
        )
        return diagnosed

    def _planner_intervention(
        self,
        payload: dict[str, Any],
        classification: Classification,
        *,
        attempt_no: int,
        now_iso: str,
    ) -> str | None:
        """Optionally let the LLM pick the first candidate intervention.

        Only consulted for LLM-diagnosed journeys; the proposal still passes
        the same Guardian veto loop as every fast-path move, and an invalid or
        unavailable proposal simply falls back to the deterministic preference
        table.
        """
        if self._planner is None:
            return None
        proposal = self._planner.propose(
            root_cause=classification.root_cause,
            legal_moves=sorted(legal_moves(classification.root_cause)),
            failure_context=_llm_failure_context(payload),
            attempt_no=attempt_no,
        )
        if proposal is None:
            return None
        self._append(
            E_INTERVENTION_PROPOSED,
            str(payload["subscription_id"]),
            {
                "intervention": proposal.intervention,
                "source": SOURCE_LLM,
                "rationale": proposal.rationale,
                "provider": proposal.provider,
                "attempt_no": attempt_no,
            },
            now_iso,
        )
        return proposal.intervention

    def handle_payment_captured(self, payload: dict[str, Any]) -> None:
        """Webhook truth: money arrived. Close the journey RECOVERED when the FSM allows.

        The gateway has already appended E_PAYMENT_RECOVERED; this syncs the
        journeys projection. WAITING_OUTCOME recovers in one hop; INTERVENING
        takes its legal two-hop path (action executed -> recovered). Other open
        states have no recovery edge, so they stay open for a human - no FSM
        shortcuts, even for good news.
        """
        sub_id = str(payload["subscription_id"])
        journey = self._journeys.get_by_subscription(sub_id)
        if journey is None or is_terminal(journey.state):
            return
        now = self._clock.now()
        now_iso = utc_iso(now)
        state = _advance(journey.state, EVENT_RECOVERED)
        if state == journey.state and journey.state == STATE_INTERVENING:
            state = _advance(_advance(journey.state, EVENT_ACTION_EXECUTED), EVENT_RECOVERED)
        if state == journey.state:
            return
        self._append(
            E_JOURNEY_STATE_CHANGED,
            sub_id,
            {"from": journey.state, "to": state, "reason": _CAPTURED_REASON},
            now_iso,
        )
        fields: dict[str, Any] = {"state": state}
        if is_terminal(state):
            fields["closed_at"] = now_iso
        self._journeys.update_fields(journey.journey_id, fields, updated_at=now_iso)

    def _kill_switch(self) -> bool:
        row = self._db.conn.execute(
            "SELECT enabled FROM system_flags WHERE flag='kill_switch'"
        ).fetchone()
        return bool(row["enabled"]) if row is not None else False

    def _cause_outage(self, cause: str, *, now: datetime) -> bool:
        """Cross-journey spike check: enough same-cause failures in the last 24h?"""
        cutoff = utc_iso(now - timedelta(minutes=_OUTAGE_WINDOW_MINUTES))
        rows = self._db.conn.execute(
            "SELECT payload FROM events WHERE type = ? AND occurred_at >= ?",
            (E_PAYMENT_FAILED, cutoff),
        ).fetchall()
        causes = [_failure_root_cause(json.loads(row["payload"])) for row in rows]
        return detect_cause_outage(recent_failure_causes=causes, cause=cause)

    def _append(
        self, event_type: str, sub_id: str, event_payload: dict[str, Any], occurred_at: str
    ) -> None:
        self._event_store.append(
            event_type=event_type,
            aggregate_type=AGG_JOURNEY,
            aggregate_id=sub_id,
            payload=event_payload,
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            event_id=uuid4().hex[:12],
        )

    def _open_journey(self, payload: dict[str, Any], *, sub_id: str, now_iso: str) -> Journey:
        journey_id = f"j_{uuid4().hex[:12]}"
        self._journeys.create(
            journey_id=journey_id,
            subscription_id=sub_id,
            customer_id=str(payload.get("customer_id", "unknown")),
            amount_minor=int(payload.get("amount_minor") or 0),
            currency=str(payload.get("currency", "INR")),
            failure_code=payload.get("failure_code"),
            opened_at=now_iso,
        )
        self._append(E_JOURNEY_OPENED, sub_id, {"journey_id": journey_id}, now_iso)
        created = self._journeys.get_by_subscription(sub_id)
        if created is None:  # pragma: no cover - inserted one statement above
            raise LookupError(f"journey row vanished right after insert: {journey_id}")
        return created

    def _route_needs_human(
        self, journey: Journey, classification: Classification, journey_state: str, now_iso: str
    ) -> None:
        next_state = _advance(journey_state, EVENT_NEEDS_HUMAN)
        self._journeys.update_fields(
            journey.journey_id,
            {
                "root_cause": classification.root_cause,
                "classify_source": classification.source,
                "state": next_state,
            },
            updated_at=now_iso,
        )

    def _close_journey(
        self,
        journey_id: str,
        sub_id: str,
        classification: Classification,
        reason: str,
        now_iso: str,
    ) -> None:
        self._append(E_JOURNEY_CLOSED, sub_id, {"reason": reason}, now_iso)
        self._journeys.update_fields(
            journey_id,
            {
                "state": STATE_CLOSED_UNRECOVERED,
                "root_cause": classification.root_cause,
                "classify_source": classification.source,
                "closed_at": now_iso,
            },
            updated_at=now_iso,
        )

    def _dispatch_fast_path(
        self,
        journey: Journey,
        *,
        sub_id: str,
        classification: Classification,
        journey_state: str,
        attempt_no: int,
        amount_minor: int,
        failure_occurred: datetime,
        now: datetime,
        now_iso: str,
        planner_intervention: str | None = None,
    ) -> None:
        cause = classification.root_cause
        paused_for_outage = self._cause_outage(cause, now=now)
        candidates: tuple[str, ...] = FAST_PATH_PREFERENCE.get(cause, ())
        if planner_intervention is not None and planner_intervention in legal_moves(cause):
            candidates = (planner_intervention, *candidates)
        for intervention in candidates:
            if intervention not in legal_moves(cause):
                continue
            if paused_for_outage:
                if intervention != RETRY_LATER:
                    continue  # outage pause: only a batched deferred retry may proceed
                self._append(
                    E_INTERVENTION_VETOED,
                    sub_id,
                    {"intervention": intervention, "reason": _CAUSE_OUTAGE_REASON},
                    now_iso,
                )
                paused_for_outage = False
            scheduled = _schedule(intervention, cause, attempt_no, sub_id, now, self._cfg)
            scheduled = self._apply_phantom_failure_guard(
                sub_id=sub_id,
                cause=cause,
                scheduled=scheduled,
                failure_occurred=failure_occurred,
                now_iso=now_iso,
            )
            decision = self._govern(journey, cause, intervention, scheduled, amount_minor)
            if decision.approved:
                self._commit_approval(
                    journey,
                    sub_id=sub_id,
                    classification=classification,
                    journey_state=journey_state,
                    attempt_no=attempt_no,
                    amount_minor=amount_minor,
                    intervention=intervention,
                    scheduled=scheduled,
                    decision=decision,
                    now_iso=now_iso,
                )
                return
            self._append(
                E_INTERVENTION_VETOED,
                sub_id,
                {"intervention": intervention, "reason": decision.reason},
                now_iso,
            )
            if self._veto_stops_dispatch(
                journey,
                sub_id=sub_id,
                classification=classification,
                reason=decision.reason,
                attempt_no=attempt_no,
                amount_minor=amount_minor,
                now=now,
                now_iso=now_iso,
            ):
                return
        self._no_viable_move(journey, sub_id, classification, journey_state, now_iso)

    def _apply_phantom_failure_guard(
        self,
        *,
        sub_id: str,
        cause: str,
        scheduled: datetime,
        failure_occurred: datetime,
        now_iso: str,
    ) -> datetime:
        """Phantom-failure guard: observe quietly past an NPCI peak-hold release.

        Since 1 Aug 2025 NPCI holds UPI AutoPay debits during peak hours and
        releases them later, so a debit "failing" inside a hold window may be
        QUEUED, not failed (subshield.com/blog/upi-autopay-peak-window-failures,
        Jun 2026; Livemint Oct 2025 - AutoPay failures up to 90%, market
        retreating to cards). Recovery logic that cannot distinguish
        hold-queued from truly-failed manufactures problems: premature nudges,
        double-payment risk. For TIMEOUT / BANK_DOWN / NO_FUNDS failures that
        occurred inside a hold window we therefore push any customer-facing
        schedule to at least window-end + buffer and record E_TIMER_SET; no
        message goes out for a debit that may still succeed on its own. Payday
        schedules stay, but never earlier than the hold release.
        """
        if cause not in _PHANTOM_GUARD_CAUSES:
            return scheduled
        release = hold_release_shift(failure_occurred, tz=self._cfg.timezone)
        if release is None or release <= scheduled:
            return scheduled
        self._append(
            E_TIMER_SET,
            sub_id,
            {"reason": _HOLD_RELEASE_REASON, "original_cause": cause},
            now_iso,
        )
        return release

    def _veto_stops_dispatch(
        self,
        journey: Journey,
        *,
        sub_id: str,
        classification: Classification,
        reason: str,
        attempt_no: int,
        amount_minor: int,
        now: datetime,
        now_iso: str,
    ) -> bool:
        """Closing vetoes arm the save ladder before closing; kill switch halts only."""
        if reason in _CLOSING_VETO_REASONS:
            laddered = self._arm_save_ladder(
                journey,
                sub_id=sub_id,
                classification=classification,
                attempt_no=attempt_no,
                amount_minor=amount_minor,
                now=now,
                now_iso=now_iso,
            )
            if not laddered:
                self._close_journey(journey.journey_id, sub_id, classification, reason, now_iso)
            return True
        return reason == _KILL_SWITCH_REASON

    def _arm_save_ladder(
        self,
        journey: Journey,
        *,
        sub_id: str,
        classification: Classification,
        attempt_no: int,
        amount_minor: int,
        now: datetime,
        now_iso: str,
    ) -> bool:
        """Arm the save-offer strike instead of closing; False means two-strike close.

        Ladder (see module docstring): recovery -> 7-day save grace -> close.
        The save strike deliberately rides the grace window rather than the
        touch budget - the idempotency key pins ONE save offer per attempt, so
        a repeat veto for the same attempt is the second strike that closes.
        """
        if classification.root_cause == HARD_DECLINE:
            return False
        task_id = self._queue.enqueue(
            task_type=TASK_HANDLE_PAYMENT_FAILED,
            payload={
                "subscription_id": sub_id,
                "customer_id": journey.customer_id,
                "failure_code": classification.matched_code or journey.failure_code,
                "error_description": _SAVE_WINDOW_DESCRIPTION,
                "amount_minor": amount_minor,
                "currency": journey.currency,
            },
            idempotency_key=f"save:{journey.journey_id}:{attempt_no}",
            available_at=utc_iso(now + _SAVE_GRACE_PERIOD),
            created_at=now_iso,
        )
        if task_id is None:
            return False  # save already offered for this attempt: second strike
        self._append(
            E_ACTION_EXECUTED,
            sub_id,
            {
                "kind": "save_offer",
                "status": "executed",
                "detail": _SAVE_OFFER_DETAIL,
                "attempt_no": attempt_no,
            },
            now_iso,
        )
        return True

    def _govern(
        self,
        journey: Journey,
        cause: str,
        intervention: str,
        scheduled: datetime,
        amount_minor: int,
    ) -> Decision:
        return evaluate(
            Proposal(intervention, utc_iso(scheduled), amount_minor),
            JourneyContext(
                journey_id=journey.journey_id,
                customer_id=journey.customer_id,
                root_cause=cause,
                attempts_used=journey.attempts_used,
                touches_used=journey.touches_used,
                window_started_at=journey.window_started_at,
            ),
            cfg=self._cfg,
            clock=self._clock,
            kill_switch=self._kill_switch(),
        )

    def _commit_approval(
        self,
        journey: Journey,
        *,
        sub_id: str,
        classification: Classification,
        journey_state: str,
        attempt_no: int,
        amount_minor: int,
        intervention: str,
        scheduled: datetime,
        decision: Decision,
        now_iso: str,
    ) -> None:
        if PREDEBIT_NOTIFY_CONDITION in decision.conditions:
            self._append(
                E_ACTION_EXECUTED,
                sub_id,
                {"kind": "predebit_notification", "status": "executed", "attempt_no": attempt_no},
                now_iso,
            )
        defer_until = decision.defer_until or utc_iso(scheduled)
        self._append(
            E_INTERVENTION_APPROVED,
            sub_id,
            {"intervention": intervention, "scheduled_at": defer_until},
            now_iso,
        )
        self._queue.enqueue(
            task_type=TASK_EXECUTE_INTENT,
            payload={
                "journey_id": journey.journey_id,
                "subscription_id": sub_id,
                "customer_id": journey.customer_id,
                "intervention": intervention,
                "amount_minor": amount_minor,
                "currency": journey.currency,
                "attempt_no": attempt_no,
                "scheduled_at": defer_until,
            },
            idempotency_key=f"exec:{journey.journey_id}:{attempt_no}:{intervention}",
            available_at=defer_until,
            max_attempts=5,
            created_at=now_iso,
        )
        fields: dict[str, Any] = {
            "state": _advance(journey_state, EVENT_APPROVED),
            "root_cause": classification.root_cause,
            "classify_source": classification.source,
        }
        if not journey.window_started_at:
            fields["window_started_at"] = now_iso
        self._journeys.update_fields(journey.journey_id, fields, updated_at=now_iso)

    def _no_viable_move(
        self,
        journey: Journey,
        sub_id: str,
        classification: Classification,
        journey_state: str,
        now_iso: str,
    ) -> None:
        self._append(
            E_JOURNEY_STATE_CHANGED,
            sub_id,
            {"from": journey_state, "to": STATE_HUMAN_REVIEW, "reason": _NO_VIABLE_MOVE_REASON},
            now_iso,
        )
        self._journeys.update_fields(
            journey.journey_id,
            {
                "state": STATE_HUMAN_REVIEW,
                "root_cause": classification.root_cause,
                "classify_source": classification.source,
            },
            updated_at=now_iso,
        )
