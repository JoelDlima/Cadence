"""Engine escalation-ladder tests: sticky -> LLM diagnosis -> human, and the
payment.captured projection. Plus the served-app runtime: gateway task
rehydration and the wired handler map.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.test_engine import _engine, _payload, _policy_config

from revive.agents.planner import PlannerAgent
from revive.clock import FakeClock
from revive.events import (
    E_CLASSIFICATION_COMPLETED,
    E_INTERVENTION_PROPOSED,
    E_JOURNEY_STATE_CHANGED,
)
from revive.executors.contracts import (
    TASK_EXECUTE_INTENT,
)
from revive.journey.engine import RecoveryEngine
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import (
    STATE_HUMAN_REVIEW,
    STATE_INTERVENING,
    STATE_RECOVERED,
    STATE_WAITING_OUTCOME,
    JourneyRepo,
)
from revive.store.queue_repo import QueueRepo

pytestmark = [pytest.mark.integration]

_UNKNOWN_PAYLOAD = {
    "failure_code": "XR_9F7Q",
    "error_description": "issuer nap rejected the mandate",
}


class _ScriptedLLM:
    """Fake complete_json: returns scripted (obj, provider) per call."""

    def __init__(self, scripted: list[dict | None]) -> None:
        self._scripted = iter(scripted)
        self.calls: list[str] = []

    def complete_json(self, *, system: str, prompt: str) -> tuple[dict | None, str]:
        self.calls.append(prompt)
        return next(self._scripted), "fake"


def _planner_engine(db: Database, clock: FakeClock, scripted: list[dict | None]) -> RecoveryEngine:
    planner = PlannerAgent(llm=_ScriptedLLM(scripted))  # type: ignore[arg-type]
    return RecoveryEngine(
        db=db,
        event_store=EventStore(db),
        journeys=JourneyRepo(db),
        queue=QueueRepo(db),
        cfg=_policy_config(),
        clock=clock,
        planner=planner,
    )


def _classifications(db: Database, sub_id: str) -> list[dict[str, Any]]:
    store = EventStore(db)
    return [
        e.payload
        for e in store.get_by_aggregate("journey", sub_id)
        if e.type == E_CLASSIFICATION_COMPLETED
    ]


def test_unknown_with_no_planner_still_routes_to_human(tmp_db: Database, fake_clock: FakeClock) -> None:
    engine = _engine(tmp_db, fake_clock)

    engine.handle_payment_failed(_payload("sub_u1", **_UNKNOWN_PAYLOAD))

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_u1")
    assert journey is not None
    assert journey.state == STATE_HUMAN_REVIEW
    assert journey.root_cause == "UNKNOWN"


def test_llm_diagnosis_routes_fast_path_and_audits_provider(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _planner_engine(
        tmp_db,
        fake_clock,
        scripted=[
            {"root_cause": "BANK_DOWN", "confidence": 0.7, "rationale": "issuer-side reject"},
            {
                "intervention": "EMAIL_NUDGE",
                "delay_hours": 2.0,
                "rationale": "inform customer, low friction",
            },
        ],
    )

    engine.handle_payment_failed(_payload("sub_u2", **_UNKNOWN_PAYLOAD))

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_u2")
    assert journey is not None
    assert journey.state == STATE_INTERVENING
    assert journey.root_cause == "BANK_DOWN"
    assert journey.classify_source == "llm"
    llm_rows = [c for c in _classifications(tmp_db, "sub_u2") if c["source"] == "llm"]
    assert llm_rows and llm_rows[-1]["provider"] == "fake"
    store = EventStore(tmp_db)
    proposed = [
        e.payload
        for e in store.get_by_aggregate("journey", "sub_u2")
        if e.type == E_INTERVENTION_PROPOSED
    ]
    assert proposed and proposed[0]["intervention"] == "EMAIL_NUDGE"
    rows = tmp_db.conn.execute(
        "SELECT payload FROM task_queue WHERE task_type=?", (TASK_EXECUTE_INTENT,)
    ).fetchall()
    assert rows and json.loads(rows[0]["payload"])["intervention"] == "EMAIL_NUDGE"


def test_llm_unavailable_diagnosis_falls_back_to_human(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _planner_engine(tmp_db, fake_clock, scripted=[None])

    engine.handle_payment_failed(_payload("sub_u3", **_UNKNOWN_PAYLOAD))

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_u3")
    assert journey is not None
    assert journey.state == STATE_HUMAN_REVIEW
    llm_rows = [c for c in _classifications(tmp_db, "sub_u3") if c["source"] == "llm"]
    assert llm_rows and llm_rows[-1]["root_cause"] == "UNKNOWN"


def test_llm_never_diagnoses_hard_decline(tmp_db: Database, fake_clock: FakeClock) -> None:
    engine = _planner_engine(
        tmp_db,
        fake_clock,
        scripted=[{"root_cause": "HARD_DECLINE", "confidence": 0.9, "rationale": "stop"}],
    )

    engine.handle_payment_failed(_payload("sub_u4", **_UNKNOWN_PAYLOAD))

    journey = JourneyRepo(tmp_db).get_by_subscription("sub_u4")
    assert journey is not None
    assert journey.state == STATE_HUMAN_REVIEW  # invalid diagnosis -> human, never a stop


def test_sticky_diagnosis_reuses_prior_cause_without_llm(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    scripted: list[dict | None] = [
        {"root_cause": "NO_FUNDS", "confidence": 0.8, "rationale": "insufficient balance"},
        None,  # propose() may be consulted once for the first diagnosis
        None,
    ]
    engine = _planner_engine(tmp_db, fake_clock, scripted=scripted)
    engine.handle_payment_failed(_payload("sub_u5", **_UNKNOWN_PAYLOAD))
    scripted.clear()

    # A second unknown failure (e.g. ignored nudge loops back) must NOT call the LLM.
    engine.handle_payment_failed(_payload("sub_u5", **_UNKNOWN_PAYLOAD))

    sticky = [c for c in _classifications(tmp_db, "sub_u5") if c["source"] == "sticky"]
    assert sticky, "repeat unknown should reuse the journey's confirmed cause"
    llm_calls = (engine._planner._llm.calls)  # noqa: SLF001 - test seam
    assert len(llm_calls) == 2  # diagnose + propose on the FIRST failure only


def test_failure_context_never_carries_customer_identity(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _planner_engine(
        tmp_db,
        fake_clock,
        scripted=[
            {"root_cause": "TIMEOUT", "confidence": 0.6, "rationale": "upstream timeout"},
            None,  # propose(): none -> deterministic preference table
        ],
    )

    engine.handle_payment_failed(_payload("sub_u6", **_UNKNOWN_PAYLOAD))

    prompts = engine._planner._llm.calls  # noqa: SLF001 - test seam
    assert prompts, "diagnose() must have been called"
    for prompt in prompts:
        assert "sub_u6" not in prompt and "cust_sub_u6" not in prompt


def test_captured_closes_waiting_outcome_journey(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)
    engine.handle_payment_failed(_payload("sub_c1"))
    journeys = JourneyRepo(tmp_db)
    journey = journeys.get_by_subscription("sub_c1")
    assert journey is not None
    journeys.update_fields(journey.journey_id, {"state": STATE_WAITING_OUTCOME}, updated_at="")

    engine.handle_payment_captured({"subscription_id": "sub_c1", "payment_id": "pay_X"})

    journey = journeys.get_by_subscription("sub_c1")
    assert journey is not None
    assert journey.state == STATE_RECOVERED
    assert journey.closed_at is not None


def test_captured_is_idempotent_for_terminal_journeys(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    engine = _engine(tmp_db, fake_clock)
    engine.handle_payment_failed(_payload("sub_c2"))
    journeys = JourneyRepo(tmp_db)
    journey = journeys.get_by_subscription("sub_c2")
    assert journey is not None
    journeys.update_fields(
        journey.journey_id, {"state": STATE_RECOVERED, "closed_at": "x"}, updated_at=""
    )

    engine.handle_payment_captured({"subscription_id": "sub_c2", "payment_id": "pay_Y"})

    store = EventStore(tmp_db)
    changes = [
        e
        for e in store.get_by_aggregate("journey", "sub_c2")
        if e.type == E_JOURNEY_STATE_CHANGED
    ]
    assert changes == []  # terminal: nothing to do, no events


def test_gateway_task_rehydrates_full_payload_from_event_store(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    from revive.api.app import _rehydrated_failure_payload

    store = EventStore(tmp_db)
    store.append(
        event_type="payment.failed",
        aggregate_type="journey",
        aggregate_id="sub_g1",
        payload={
            "failure_code": "insufficient_funds",
            "error_description": "insufficient balance",
            "amount_minor": 49900,
            "currency": "INR",
            "customer_id": "cust_g1",
            "payment_id": "pay_g1",
        },
        occurred_at="2026-08-22T10:00:00+00:00",
        recorded_at="2026-08-22T10:00:00+00:00",
        event_id="pf_1",
    )

    rehydrated = _rehydrated_failure_payload(
        store, {"subscription_id": "sub_g1", "payment_id": "pay_g1"}
    )

    assert rehydrated["amount_minor"] == 49900
    assert rehydrated["customer_id"] == "cust_g1"
    loopback = _rehydrated_failure_payload(
        store,
        {
            "subscription_id": "sub_g1",
            "customer_id": "cust_g1",
            "error_description": "retry debit failed",
            "amount_minor": 49900,
        },
    )
    assert loopback["error_description"] == "retry debit failed"
