"""Journey lifecycle finite state machine.

Pure transition table between journey states (canonical strings live in
`revive.store.journey_repo`). No I/O: callers record the resulting state change
as an event themselves. Every state must have a row in the table; terminal
states simply map to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from revive.store.journey_repo import (
    ALL_STATES,
    STATE_CLASSIFIED,
    STATE_CLOSED_UNRECOVERED,
    STATE_HUMAN_REVIEW,
    STATE_INTERVENING,
    STATE_OPENED,
    STATE_RECOVERED,
    STATE_WAITING_OUTCOME,
)

EVENT_CLASSIFIED = "classification.completed"
EVENT_NEEDS_HUMAN = "classification.needs_human"
EVENT_APPROVED = "intervention.approved"
EVENT_ACTION_EXECUTED = "action.executed"
EVENT_RECOVERED = "payment.recovered"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_JOURNEY_CLOSED = "journey.closed"

ALLOWED: dict[str, dict[str, str]] = {
    STATE_OPENED: {
        EVENT_CLASSIFIED: STATE_CLASSIFIED,
        EVENT_NEEDS_HUMAN: STATE_HUMAN_REVIEW,
        EVENT_JOURNEY_CLOSED: STATE_CLOSED_UNRECOVERED,
    },
    STATE_CLASSIFIED: {
        EVENT_APPROVED: STATE_INTERVENING,
        EVENT_JOURNEY_CLOSED: STATE_CLOSED_UNRECOVERED,
    },
    STATE_INTERVENING: {
        EVENT_ACTION_EXECUTED: STATE_WAITING_OUTCOME,
        EVENT_JOURNEY_CLOSED: STATE_CLOSED_UNRECOVERED,
    },
    STATE_WAITING_OUTCOME: {
        EVENT_RECOVERED: STATE_RECOVERED,
        EVENT_PAYMENT_FAILED: STATE_CLASSIFIED,
        EVENT_JOURNEY_CLOSED: STATE_CLOSED_UNRECOVERED,
    },
    STATE_HUMAN_REVIEW: {
        EVENT_APPROVED: STATE_INTERVENING,
        EVENT_JOURNEY_CLOSED: STATE_CLOSED_UNRECOVERED,
    },
    STATE_RECOVERED: {},
    STATE_CLOSED_UNRECOVERED: {},
}

# Cheap import-time invariant: the table must cover every canonical state.
_UNCOVERED_STATES: frozenset[str] = ALL_STATES - ALLOWED.keys()
if _UNCOVERED_STATES:
    raise RuntimeError(f"journey FSM missing rows for states: {sorted(_UNCOVERED_STATES)}")


@dataclass(frozen=True)
class IllegalTransition(Exception):
    """Raised when an event cannot be applied to a journey state."""

    state: str
    event: str

    def __post_init__(self) -> None:
        super().__init__(f"illegal transition: {self.state} --{self.event}-->")


def transition(state: str, event: str) -> str:
    """Return next state. Raises IllegalTransition for unknown state/event combos."""
    next_state: str | None = ALLOWED.get(state, {}).get(event)
    if next_state is None:
        raise IllegalTransition(state=state, event=event)
    return next_state


def is_terminal(state: str) -> bool:
    """True when state has no outgoing transitions."""
    return len(ALLOWED.get(state, {})) == 0
