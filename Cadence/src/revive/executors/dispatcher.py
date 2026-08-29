"""Executor dispatcher: turns approved interventions into actions + events.

The engine enqueues ``TASK_EXECUTE_INTENT``; a worker hands the payload here.
Every branch emits ``action.executed`` (or a domain outcome event) and never
raises — an unknown intervention must degrade to a recorded failure, not crash
the worker loop. Retry outcomes come from an injectable ``OutcomeFn`` so tests
pin both branches deterministically.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from revive.agents.ptp_parser import KIND_REFUSAL, parse_reply, ptp_to_timer_days
from revive.classify.taxonomy import (
    EMAIL_NUDGE,
    GRACE_OFFER,
    PAYMENT_LINK,
    RETRY_LATER,
    RETRY_NOW,
    RETRY_PAYDAY,
    SWITCH_METHOD,
    WHATSAPP_NUDGE,
)
from revive.clock import Clock, utc_iso
from revive.config import PolicyConfig
from revive.events import (
    AGG_JOURNEY,
    E_ACTION_EXECUTED,
    E_CUSTOMER_REPLIED,
    E_JOURNEY_CLOSED,
    E_PAYMENT_FAILED,
    E_PAYMENT_RECOVERED,
    E_PTP_COMMITTED,
)
from revive.executors.channels import email_nudge_text, whatsapp_nudge_text
from revive.executors.contracts import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    TASK_AWAIT_CUSTOMER_REPLY,
    TASK_HANDLE_PAYMENT_FAILED,
    TASK_OUTCOME_CHECK,
    InterventionRequest,
    InterventionResult,
)
from revive.executors.razorpay_client import RazorpayLike
from revive.journey import fsm
from revive.journey.fsm import IllegalTransition
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import (
    STATE_CLOSED_UNRECOVERED,
    STATE_INTERVENING,
    STATE_RECOVERED,
    STATE_WAITING_OUTCOME,
    Journey,
    JourneyRepo,
)
from revive.store.queue_repo import QueueRepo

OutcomeFn = Callable[[str], bool]

_RETRY_INTERVENTIONS = frozenset({RETRY_NOW, RETRY_LATER, RETRY_PAYDAY})
_CHANNEL_INTERVENTIONS = frozenset({SWITCH_METHOD, WHATSAPP_NUDGE, EMAIL_NUDGE})
_OUTCOME_CHECK_DELAY = timedelta(hours=48)
_FAILURE_COOL_OFF = timedelta(seconds=60)
_REPLY_WAIT = timedelta(hours=24)
_SIMULATED_RECOVERY_RATE = 0.42
_CHANNEL_FOR_INTERVENTION = {WHATSAPP_NUDGE: "whatsapp", EMAIL_NUDGE: "email"}
_CUSTOMER_REFUSED_REASON = "customer_refused"
_PTP_FAILURE_CODE = "customer_ptp_reschedule"


def default_outcome_fn(seed: str) -> bool:
    """Deterministic simulated debit outcome keyed by subscription:attempt."""
    return random.Random(seed).random() < _SIMULATED_RECOVERY_RATE


DEFAULT_OUTCOME_FN: OutcomeFn = default_outcome_fn


class Dispatcher:
    def __init__(
        self,
        db: Database,
        event_store: EventStore,
        journeys: JourneyRepo,
        queue: QueueRepo,
        client: RazorpayLike,
        cfg: PolicyConfig,
        clock: Clock,
        outcome_fn: OutcomeFn = DEFAULT_OUTCOME_FN,
        channels: dict[str, Any] | None = None,
        page_base_url: str | None = None,
        llm: LLMClient | None = None,  # PHASE 6: optional message-writer LLM
    ) -> None:
        self._db = db
        self._event_store = event_store
        self._journeys = journeys
        self._queue = queue
        self._client = client
        self._cfg = cfg
        self._clock = clock
        self._outcome_fn = outcome_fn
        self._channels = channels
        self._page_base_url = page_base_url
        self._llm = llm

    def execute(self, req: InterventionRequest) -> InterventionResult:
        if req.intervention == GRACE_OFFER:
            return self._exec_grace_offer(req)
        if req.intervention == PAYMENT_LINK:
            return self._exec_payment_link(req)
        if req.intervention in _RETRY_INTERVENTIONS:
            return self._exec_mandate_retry(req)
        if req.intervention in _CHANNEL_INTERVENTIONS:
            if self._channels is None or req.intervention not in _CHANNEL_FOR_INTERVENTION:
                return self._exec_skipped_channel(req)
            return self._exec_channel_nudge(req)
        return self._exec_unknown(req)

    def resolve_outcome_check(self, payload: dict[str, Any]) -> None:
        """Runtime hook for ``outcome_check`` tasks: did the offered link get paid?

        Live path (PHASE 2): if the journey has a stored Razorpay payment_id
        from its payment-link action, call ``client.fetch_payment(payment_id)``
        and read the live ``status`` field. If the link is captured, close
        the journey RECOVERED. If the link is unpaid, loop the journey back
        with an honest failure code so touch caps and the save ladder keep
        governing cadence.

        Fallback: the legacy list-payments-by-reference probe, and finally the
        injectable OutcomeFn for the keyless simulator. Unpaid means the
        attempt did not convert.
        """
        journey = self._journeys.get(str(payload["journey_id"]))
        if journey is None or journey.state != STATE_WAITING_OUTCOME:
            return
        journey_id = journey.journey_id
        attempt_no = max(int(payload.get("attempt_no", 1)), 1)
        reference_id = f"{journey_id}:{attempt_no}"
        won = self._fetch_outcome(reference_id, payload=payload, journey=journey)
        if won is True:
            self._finish_recovered(
                self._request_from(journey, attempt_no=attempt_no, intervention=PAYMENT_LINK),
                self._last_link_ref(journey_id) or reference_id,
            )
            return
        if won is False:
            self._finish_retry_failed(
                self._request_from(journey, attempt_no=attempt_no, intervention=PAYMENT_LINK),
                code="payment_link_unpaid",
                description="payment link went unpaid",
            )
            return
        # won is None -> unknown: do nothing this tick, the worker will re-poll.

    def _fetch_outcome(
        self,
        reference_id: str,
        *,
        payload: dict[str, Any],
        journey: Any,
    ) -> bool | None:
        """Probe Razorpay (live) or the simulator (offline) for whether the
        payment attached to this journey captured.

        Returns True on captured, False on confirmed unpaid, None on
        "can't tell yet" (Razorpay still processing, transport error, etc.).
        """
        # PHASE 2 primary path: live Razorpay fetch by payment_id (single-call).
        # The payment_id was stored on the journey's most recent payment-link
        # action event when the link was created. This is exact, fast, and
        # race-free.
        live_payment_id = self._live_payment_id_for_journey(journey.journey_id)
        if live_payment_id:
            try:
                payment = self._client.fetch_payment(payment_id=live_payment_id)
                status = str(payment.get("status", "")).lower()
                if status == "captured":
                    return True
                if status in ("failed", "cancelled", "expired"):
                    return False
                # authorized / created / pending: still processing -> retry next tick
                return None
            except Exception:
                # transport error, 5xx, etc. -> fall through to the next probe
                pass

        # Fallback: list payments by reference_id (the older path, works
        # for the simulator and for live when no payment_id was stored).
        probe = getattr(self._client, "payment_captured_for", None)
        if probe is not None:
            try:
                return bool(probe(reference_id=reference_id))
            except Exception:
                pass

        # Final fallback: injectable outcome function (keyless demo).
        try:
            subscription_id = str(payload.get("subscription_id", journey.subscription_id))
            return bool(self._outcome_fn(f"{subscription_id}:{attempt_no}"))
        except Exception:
            return None

    def _live_payment_id_for_journey(self, journey_id: str) -> str | None:
        """Look at the most recent action event for a Razorpay payment_id.

        The dispatcher stores the Razorpay payment_id (or, in the simulator,
        a ``plink_sim_xxx`` id) as the ``ref`` field on the action event. For
        a real Razorpay payment_link that has been paid, the corresponding
        payment has its own ``pay_xxx`` id, and the link action carries the
        ``payment_id`` as a separate field. We check both.
        """
        events = sorted(
            self._event_store.get_by_aggregate(AGG_JOURNEY, journey_id),
            key=lambda e: e.seq,
        )
        for event in reversed(events):
            if event.type != E_ACTION_EXECUTED:
                continue
            payload = event.payload
            kind = payload.get("kind")
            if kind != PAYMENT_LINK:
                continue
            payment_id = payload.get("payment_id")
            if payment_id:
                return str(payment_id)
            ref = payload.get("ref")
            if ref and (ref.startswith("pay_") or ref.startswith("plink_")):
                return str(ref)
        return None

    def resolve_reply_wait(self, payload: dict[str, Any]) -> None:
        """Runtime hook for ``await_customer_reply`` tasks: the wait elapsed, no reply.

        Real inbound replies flow through ``handle_customer_reply``; this fires
        when the reply window closes silent. The nudge did not convert - loop
        the journey back so the ladder keeps governing (same contract as the
        simulator's resolver).
        """
        journey = self._journeys.get(str(payload["journey_id"]))
        if journey is None or journey.state != STATE_WAITING_OUTCOME:
            return
        attempt_no = max(int(payload.get("attempt_no", 1)), 1)
        self._finish_retry_failed(
            self._request_from(
                journey,
                attempt_no=attempt_no,
                intervention=str(payload.get("channel", "nudge")),
                customer_id=str(payload.get("customer_id", journey.customer_id)),
            ),
            code="nudge_no_reply",
            description="nudge got no reply within the wait window",
        )

    def _request_from(
        self,
        journey: Journey,
        *,
        attempt_no: int,
        intervention: str,
        customer_id: str | None = None,
    ) -> InterventionRequest:
        return InterventionRequest(
            journey_id=journey.journey_id,
            subscription_id=journey.subscription_id,
            customer_id=customer_id or journey.customer_id,
            intervention=intervention,
            amount_minor=int(journey.amount_minor or 0),
            currency=journey.currency,
            attempt_no=attempt_no,
            scheduled_at="",
        )

    def _last_link_ref(self, journey_id: str) -> str | None:
        """Payment-link ref from this journey's most recent link action event."""
        events = sorted(
            self._event_store.get_by_aggregate(AGG_JOURNEY, journey_id), key=lambda e: e.seq
        )
        for event in reversed(events):
            if event.type == E_ACTION_EXECUTED and event.payload.get("kind") == PAYMENT_LINK:
                ref = event.payload.get("ref")
                if ref is not None:
                    return str(ref)
        return None

    def _now(self) -> str:
        return utc_iso(self._clock.now())

    def _emit(self, event_type: str, journey_id: str, payload: dict[str, Any]) -> None:
        moment = self._clock.now()
        self._event_store.append(
            event_type=event_type,
            aggregate_type=AGG_JOURNEY,
            aggregate_id=journey_id,
            payload=payload,
            occurred_at=utc_iso(moment),
            recorded_at=utc_iso(moment),
            event_id=f"act_{uuid.uuid4().hex[:12]}",
        )

    def _advance(self, req: InterventionRequest, fsm_event: str, extra: dict[str, Any]) -> None:
        journey = self._journeys.get(req.journey_id)
        current = journey.state if journey else STATE_INTERVENING
        fields = {"state": fsm.transition(current, fsm_event), **extra}
        self._journeys.update_fields(req.journey_id, fields, updated_at=self._now())

    def _exec_grace_offer(self, req: InterventionRequest) -> InterventionResult:
        """Grant a 7-day grace period. Critically: also enqueue a +7d follow-up
        so the journey re-enters the engine after the grace window. Without
        this, a granted grace would strand the journey in INTERVENING forever.
        PHASE 3 fix.
        """
        self._emit(
            E_ACTION_EXECUTED,
            req.journey_id,
            {
                "kind": req.intervention,
                "status": STATUS_EXECUTED,
                "detail": "grace period granted",
                "attempt_no": req.attempt_no,
            },
        )
        # Re-fire payment_failed after the 7-day grace so the engine picks
        # a real recovery move (link, retry-payday, etc.) — the sim's
        # calibrated (NO_FUNDS, grace) = 0.10 already accounts for some
        # in-window conversion, but most grace recipients need a follow-up.
        self._queue.enqueue(
            task_type=TASK_HANDLE_PAYMENT_FAILED,
            payload={
                "subscription_id": req.subscription_id,
                "customer_id": req.customer_id,
                "failure_code": "save_window_expiry",
                "error_description": "save window expiry",
                "amount_minor": req.amount_minor,
                "currency": req.currency,
            },
            available_at=utc_iso(self._clock.now() + timedelta(days=7)),
            created_at=self._now(),
            idempotency_key=f"save_grace:{req.journey_id}:{req.attempt_no}",
        )
        return InterventionResult(status=STATUS_EXECUTED, detail="grace period granted")

    def _exec_payment_link(self, req: InterventionRequest) -> InterventionResult:
        link = self._client.create_payment_link(
            amount_minor=req.amount_minor,
            currency=req.currency,
            customer_id=req.customer_id,
            description="Revive: complete your pending subscription payment",
            reference_id=f"{req.journey_id}:{req.attempt_no}",
        )
        ref = str(link["id"])
        self._emit(
            E_ACTION_EXECUTED,
            req.journey_id,
            {"kind": req.intervention, "status": STATUS_EXECUTED, "ref": ref},
        )
        self._advance(req, fsm.EVENT_ACTION_EXECUTED, {"attempts_used": req.attempt_no})
        self._enqueue_outcome_check(req)
        return InterventionResult(
            status=STATUS_EXECUTED, detail=f"payment link sent ({ref})", ref=ref
        )

    def _enqueue_outcome_check(self, req: InterventionRequest) -> None:
        self._queue.enqueue(
            task_type=TASK_OUTCOME_CHECK,
            payload={
                "journey_id": req.journey_id,
                "subscription_id": req.subscription_id,
                "attempt_no": req.attempt_no,
            },
            available_at=utc_iso(self._clock.now() + _OUTCOME_CHECK_DELAY),
            created_at=self._now(),
            idempotency_key=f"oc:{req.journey_id}:{req.attempt_no}",
        )

    def _exec_channel_nudge(self, req: InterventionRequest) -> InterventionResult:
        channel_name = _CHANNEL_FOR_INTERVENTION[req.intervention]
        message = self._nudge_text(req)
        ref_key = f"{req.journey_id}:{req.attempt_no}:{channel_name}"
        sent = self._channels[channel_name].send(
            to_customer_id=req.customer_id, message=message, ref=ref_key
        )
        ref = str(sent["ref"])
        self._emit(
            E_ACTION_EXECUTED,
            req.journey_id,
            {
                "kind": req.intervention,
                "status": STATUS_EXECUTED,
                "ref": ref,
                "attempt_no": req.attempt_no,
            },
        )
        journey = self._journeys.get(req.journey_id)
        touches = (journey.touches_used if journey else 0) + 1
        self._advance(req, fsm.EVENT_ACTION_EXECUTED, {"touches_used": touches})
        self._enqueue_reply_wait(req, channel_name)
        return InterventionResult(
            status=STATUS_EXECUTED, detail=f"nudge sent via {channel_name}", ref=ref
        )

    def _page_url(self, journey_ref: str) -> str | None:
        """Self-service recovery page link; None when no page base is configured."""
        if not self._page_base_url:
            return None
        return f"{self._page_base_url.rstrip('/')}/pay/{journey_ref}"

    def _nudge_text(self, req: InterventionRequest) -> str:
        """PHASE 6: route through the LLM message writer when an LLM is
        configured. Fallback to the static templates if no LLM is set, the
        LLM fails, or the response is invalid. The writer also records an
        agent.thinking event in the audit chain for every call."""
        from revive.agents.message_writer import write_nudge

        page_url = self._page_url(req.journey_id)
        channel = _CHANNEL_FOR_INTERVENTION[req.intervention]
        body, _subject = write_nudge(
            store=self._event_store,
            llm=self._llm,
            clock=self._clock,
            journey_id=req.journey_id,
            channel=channel,
            amount_minor=req.amount_minor,
            attempt_no=req.attempt_no,
            link_url=page_url,
        )
        return body

    def _enqueue_reply_wait(self, req: InterventionRequest, channel_name: str) -> None:
        self._queue.enqueue(
            task_type=TASK_AWAIT_CUSTOMER_REPLY,
            payload={
                "journey_id": req.journey_id,
                "subscription_id": req.subscription_id,
                "customer_id": req.customer_id,
                "attempt_no": req.attempt_no,
                "channel": channel_name,
            },
            available_at=utc_iso(self._clock.now() + _REPLY_WAIT),
            created_at=self._now(),
            idempotency_key=f"reply:{req.journey_id}:{req.attempt_no}:{channel_name}",
        )

    def _exec_mandate_retry(self, req: InterventionRequest) -> InterventionResult:
        attempt = self._client.simulate_mandate_retry(
            subscription_id=req.subscription_id,
            amount_minor=req.amount_minor,
            seed=f"{req.subscription_id}:{req.attempt_no}",
        )
        ref = str(attempt["id"])
        self._emit(
            E_ACTION_EXECUTED,
            req.journey_id,
            {
                "kind": req.intervention,
                "status": STATUS_EXECUTED,
                "ref": ref,
                "attempt_no": req.attempt_no,
            },
        )
        # PHASE 5: record when the most recent successful retry happened
        # so the Guardian can enforce the NPCI 18h UPI cooling rule on the
        # next attempt. We update only when the retry is genuinely sent (i.e.
        # the action is executed); failed outcomes that the simulator rolls
        # separately do not consume the 18h window.
        try:
            self._journeys.update_fields(
                req.journey_id,
                {"last_retry_at": self._now()},
                updated_at=self._now(),
            )
        except Exception:
            pass  # noqa: BLE001
        self._advance(req, fsm.EVENT_ACTION_EXECUTED, {"attempts_used": req.attempt_no})
        recovered = self._outcome_fn(f"{req.subscription_id}:{req.attempt_no}")
        if recovered:
            return self._finish_recovered(req, ref)
        return self._finish_retry_failed(req)

    def _finish_recovered(self, req: InterventionRequest, payment_ref: str) -> InterventionResult:
        closed_at = self._now()
        self._emit(
            E_PAYMENT_RECOVERED,
            req.journey_id,
            {"via": "intervention", "payment_ref": payment_ref, "attempt_no": req.attempt_no},
        )
        self._journeys.update_fields(
            req.journey_id,
            {"state": STATE_RECOVERED, "closed_at": closed_at},
            updated_at=closed_at,
        )
        return InterventionResult(
            status=STATUS_EXECUTED, detail="payment recovered", ref=payment_ref
        )

    def _finish_retry_failed(
        self,
        req: InterventionRequest,
        *,
        code: str = "retry_debit_failed",
        description: str = "retry debit failed",
    ) -> InterventionResult:
        self._emit(
            E_PAYMENT_FAILED,
            req.journey_id,
            {"failure_code": code, "attempt_no": req.attempt_no},
        )
        self._advance(req, fsm.EVENT_PAYMENT_FAILED, {})
        self._queue.enqueue(
            task_type=TASK_HANDLE_PAYMENT_FAILED,
            payload={
                "subscription_id": req.subscription_id,
                "customer_id": req.customer_id,
                "failure_code": None,
                "error_description": description,
                "amount_minor": req.amount_minor,
                "currency": req.currency,
            },
            available_at=utc_iso(self._clock.now() + _FAILURE_COOL_OFF),
            created_at=self._now(),
            idempotency_key=f"hpf:{req.journey_id}:{req.attempt_no}:retryfail",
        )
        return InterventionResult(
            status=STATUS_EXECUTED, detail=f"{description}; cool-off queued"
        )

    def handle_customer_reply(self, payload: dict[str, Any]) -> None:
        """Runtime hook for ``await_customer_reply`` tasks: record the reply, then
        close on refusal or reschedule a retry at the promised time."""
        journey_id = str(payload["journey_id"])
        attempt_no = int(payload.get("attempt_no", 1))
        text = str(payload.get("text", ""))
        journey = self._journeys.get(journey_id)
        sub_id = str(payload.get("subscription_id", journey.subscription_id if journey else ""))
        customer_id = str(
            payload.get("customer_id", journey.customer_id if journey else "unknown")
        )
        self._emit(E_CUSTOMER_REPLIED, journey_id, {"text": text})
        local_now = self._clock.in_tz(self._cfg.timezone)
        ptp = parse_reply(text, today=local_now, tz=self._cfg.timezone)
        if ptp.kind == KIND_REFUSAL:
            self._close_for_refusal(journey_id)
            return
        days = ptp_to_timer_days(ptp, today=local_now.date())
        self._emit(
            E_PTP_COMMITTED,
            journey_id,
            {
                "kind": ptp.kind,
                "date": ptp.commit_date_iso,
                "confidence": ptp.confidence,
                "days": days,
            },
        )
        if days is None:
            return
        self._emit(
            E_PAYMENT_FAILED,
            journey_id,
            {"failure_code": _PTP_FAILURE_CODE, "attempt_no": attempt_no},
        )
        self._safe_advance(journey_id, fsm.EVENT_PAYMENT_FAILED)
        self._enqueue_ptp_retry(
            journey_id,
            attempt_no=attempt_no,
            fire_at=local_now + timedelta(days=days),
            sub_id=sub_id,
            customer_id=customer_id,
            journey=journey,
        )

    def _close_for_refusal(self, journey_id: str) -> None:
        closed_at = self._now()
        self._emit(E_JOURNEY_CLOSED, journey_id, {"reason": _CUSTOMER_REFUSED_REASON})
        self._journeys.update_fields(
            journey_id,
            {"state": STATE_CLOSED_UNRECOVERED, "closed_at": closed_at},
            updated_at=closed_at,
        )

    def _safe_advance(self, journey_id: str, fsm_event: str) -> None:
        """Apply an FSM edge when legal; unexpected states stay put (no crash)."""
        journey = self._journeys.get(journey_id)
        if journey is None:
            return
        try:
            next_state = fsm.transition(journey.state, fsm_event)
        except IllegalTransition:
            return
        self._journeys.update_fields(journey_id, {"state": next_state}, updated_at=self._now())

    def _enqueue_ptp_retry(
        self,
        journey_id: str,
        *,
        attempt_no: int,
        fire_at: datetime,
        sub_id: str,
        customer_id: str,
        journey: Journey | None,
    ) -> None:
        self._queue.enqueue(
            task_type=TASK_HANDLE_PAYMENT_FAILED,
            payload={
                "subscription_id": sub_id,
                "customer_id": customer_id,
                "failure_code": None,
                "error_description": "retry scheduled from customer promise-to-pay",
                "amount_minor": journey.amount_minor or 0,
                "currency": journey.currency if journey else "INR",
            },
            available_at=utc_iso(fire_at),
            created_at=self._now(),
            idempotency_key=f"ptp:{journey_id}:{attempt_no}",
        )

    def _exec_skipped_channel(self, req: InterventionRequest) -> InterventionResult:
        self._emit(
            E_ACTION_EXECUTED,
            req.journey_id,
            {"kind": req.intervention, "status": STATUS_SKIPPED, "detail": "channel_not_wired"},
        )
        return InterventionResult(status=STATUS_SKIPPED, detail="channel_not_wired")

    def _exec_unknown(self, req: InterventionRequest) -> InterventionResult:
        self._emit(
            E_ACTION_EXECUTED,
            req.journey_id,
            {"kind": req.intervention, "status": STATUS_FAILED, "detail": "unknown_intervention"},
        )
        return InterventionResult(
            status=STATUS_FAILED, detail=f"unknown intervention: {req.intervention}"
        )
