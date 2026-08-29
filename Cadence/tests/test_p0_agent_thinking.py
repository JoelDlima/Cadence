"""W1: agent.thinking events must reach the audit chain.

The MessageWriter always tries to record an agent.thinking event after
the LLM has been called (or the template fallback fired). The PHASE 6
implementation was using E_LLM_THINKING = "agent.thinking", but the
EVENT_TYPES frozenset did not include it, so store.append raised
InvalidEvent and the trace was lost. This test makes the contract
explicit: a single write_nudge() call must produce at least one
agent.thinking event for the journey.
"""
from __future__ import annotations

from datetime import datetime, timezone

from revive.agents.message_writer import write_nudge
from revive.clock import FakeClock
from revive.events import E_LLM_THINKING, EVENT_TYPES
from revive.store.db import Database
from revive.store.event_store import EventStore


def test_e_llm_thinking_in_event_types_whitelist() -> None:
    """Regression guard: the constant is in the registry."""
    assert "agent.thinking" in EVENT_TYPES


def test_write_nudge_template_fallback_records_agent_thinking_event() -> None:
    """When no LLM is configured, the writer falls back to the static
    template but still records an agent.thinking event for audit."""
    db = Database(":memory:")
    store = EventStore(db)
    clock = FakeClock()
    clock.set(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))

    body, subject = write_nudge(
        channel="whatsapp",
        amount_minor=49900,
        attempt_no=1,
        link_url="https://rzp.io/i/test",
        language="hinglish",
        llm=None,                # no LLM -> template path
        store=store,
        clock=clock,
        journey_id="j_W1_test",
    )

    assert body, "writer should always return a body"
    events = store.get_by_aggregate("journey", "j_W1_test")
    thinking = [e for e in events if e.type == E_LLM_THINKING]
    assert thinking, "writer must persist at least one agent.thinking event"
    p = thinking[0].payload
    assert p.get("agent") == "nudge_writer"
    assert p.get("source") in ("template", "template_fallback", "llm")
    # The audit payload must include the prompt + the final text.
    assert "prompt" in p
    assert "body" in p
    assert p["body"] == body


def test_write_nudge_no_store_still_returns_body() -> None:
    """Without a store, the writer returns a body but does not raise.
    (This is the dispatcher path when the audit chain is mid-init.)"""
    from revive.clock import FakeClock
    body, subject = write_nudge(
        channel="whatsapp",
        amount_minor=49900,
        attempt_no=1,
        link_url=None,
        language="hinglish",
        llm=None,
        store=None,
        clock=FakeClock(),
        journey_id="j_W1_no_store",
    )
    assert body
    assert subject is None or isinstance(subject, str)
