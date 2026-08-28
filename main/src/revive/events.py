"""Revive event taxonomy.

Events are the source of truth (event sourcing). Every state change in the system
is an immutable, hash-chained event. Payloads are plain JSON-serializable dicts;
this module defines the allowed types and constructors that guarantee shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- aggregate kinds ---------------------------------------------------------
AGG_WEBHOOK = "webhook"
AGG_JOURNEY = "journey"
AGG_SYSTEM = "system"

# --- event types -------------------------------------------------------------
E_WEBHOOK_RECEIVED = "webhook.received"
E_PAYMENT_FAILED = "payment.failed"
E_PAYMENT_RECOVERED = "payment.recovered"
E_JOURNEY_OPENED = "journey.opened"
E_JOURNEY_STATE_CHANGED = "journey.state_changed"
E_JOURNEY_CLOSED = "journey.closed"
E_CLASSIFICATION_COMPLETED = "classification.completed"
E_INTERVENTION_PROPOSED = "intervention.proposed"
E_INTERVENTION_APPROVED = "intervention.approved"
E_INTERVENTION_VETOED = "intervention.vetoed"
E_ACTION_EXECUTED = "action.executed"
E_CUSTOMER_REPLIED = "customer.replied"
E_PTP_COMMITTED = "ptp.committed"
E_TIMER_SET = "timer.set"
E_KILL_SWITCH_CHANGED = "killswitch.changed"

EVENT_TYPES: frozenset[str] = frozenset(
    {
        E_WEBHOOK_RECEIVED,
        E_PAYMENT_FAILED,
        E_PAYMENT_RECOVERED,
        E_JOURNEY_OPENED,
        E_JOURNEY_STATE_CHANGED,
        E_JOURNEY_CLOSED,
        E_CLASSIFICATION_COMPLETED,
        E_INTERVENTION_PROPOSED,
        E_INTERVENTION_APPROVED,
        E_INTERVENTION_VETOED,
        E_ACTION_EXECUTED,
        E_CUSTOMER_REPLIED,
        E_PTP_COMMITTED,
        E_TIMER_SET,
        E_KILL_SWITCH_CHANGED,
    }
)


class InvalidEvent(ValueError):
    """Raised when an event would violate the taxonomy."""


@dataclass(frozen=True)
class Event:
    """A single immutable fact. Construct via `make_event` after validation."""

    seq: int
    event_id: str
    occurred_at: str
    recorded_at: str
    type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str

    def to_row(self) -> dict[str, Any]:
        import json

        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "type": self.type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "payload": json.dumps(self.payload, sort_keys=True, separators=(",", ":")),
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


def make_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    occurred_at: str,
    recorded_at: str,
    event_id: str,
) -> dict[str, Any]:
    """Validate and return a plain dict ready for the event store.

    Kept as a plain dict (not the frozen dataclass) because hashing/serialization
    happens inside the store before the Event is materialized.
    """
    if event_type not in EVENT_TYPES:
        raise InvalidEvent(f"unknown event type: {event_type}")
    if not aggregate_id:
        raise InvalidEvent("aggregate_id must be non-empty")
    if not isinstance(payload, dict):
        raise InvalidEvent("payload must be a dict")
    return {
        "event_id": event_id,
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
        "type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "payload": payload,
    }
