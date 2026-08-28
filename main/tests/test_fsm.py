"""Unit tests for the journey FSM transition table."""

from __future__ import annotations

import pytest

from revive.journey.fsm import (
    EVENT_ACTION_EXECUTED,
    EVENT_APPROVED,
    EVENT_CLASSIFIED,
    EVENT_JOURNEY_CLOSED,
    EVENT_NEEDS_HUMAN,
    EVENT_PAYMENT_FAILED,
    EVENT_RECOVERED,
    IllegalTransition,
    is_terminal,
    transition,
)
from revive.store.journey_repo import (
    STATE_CLASSIFIED,
    STATE_CLOSED_UNRECOVERED,
    STATE_HUMAN_REVIEW,
    STATE_INTERVENING,
    STATE_OPENED,
    STATE_RECOVERED,
    STATE_WAITING_OUTCOME,
)

pytestmark = [pytest.mark.unit]

NON_TERMINAL_STATES: list[str] = [
    STATE_OPENED,
    STATE_CLASSIFIED,
    STATE_INTERVENING,
    STATE_WAITING_OUTCOME,
    STATE_HUMAN_REVIEW,
]

TERMINAL_EVENTS: list[str] = [
    EVENT_CLASSIFIED,
    EVENT_NEEDS_HUMAN,
    EVENT_APPROVED,
    EVENT_ACTION_EXECUTED,
    EVENT_RECOVERED,
    EVENT_PAYMENT_FAILED,
    EVENT_JOURNEY_CLOSED,
]


def test_happy_path_walks_step_by_step_to_recovered() -> None:
    # Arrange
    state = STATE_OPENED

    # Act / Assert — one legal edge per step.
    state = transition(state, EVENT_CLASSIFIED)
    assert state == STATE_CLASSIFIED

    state = transition(state, EVENT_APPROVED)
    assert state == STATE_INTERVENING

    state = transition(state, EVENT_ACTION_EXECUTED)
    assert state == STATE_WAITING_OUTCOME

    state = transition(state, EVENT_RECOVERED)
    assert state == STATE_RECOVERED


def test_payment_failure_loops_back_into_intervening() -> None:
    # Act
    classified = transition(STATE_WAITING_OUTCOME, EVENT_PAYMENT_FAILED)

    # Assert
    assert classified == STATE_CLASSIFIED

    # Act
    intervening = transition(classified, EVENT_APPROVED)

    # Assert
    assert intervening == STATE_INTERVENING


def test_human_review_detour_goes_in_and_back_out() -> None:
    # Act
    reviewed = transition(STATE_OPENED, EVENT_NEEDS_HUMAN)

    # Assert
    assert reviewed == STATE_HUMAN_REVIEW

    # Act
    approved = transition(reviewed, EVENT_APPROVED)

    # Assert
    assert approved == STATE_INTERVENING


@pytest.mark.parametrize("state", NON_TERMINAL_STATES)
def test_close_from_any_nonterminal_state_ends_unrecovered(state: str) -> None:
    # Act
    closed = transition(state, EVENT_JOURNEY_CLOSED)

    # Assert
    assert closed == STATE_CLOSED_UNRECOVERED


@pytest.mark.parametrize("event", TERMINAL_EVENTS)
@pytest.mark.parametrize("state", [STATE_RECOVERED, STATE_CLOSED_UNRECOVERED])
def test_terminal_states_reject_every_event(state: str, event: str) -> None:
    # Act / Assert
    with pytest.raises(IllegalTransition) as excinfo:
        transition(state, event)

    # Assert — exception carries the offending pair.
    assert excinfo.value.state == state
    assert excinfo.value.event == event


def test_unknown_event_raises_illegal_transition() -> None:
    # Act / Assert
    with pytest.raises(IllegalTransition) as excinfo:
        transition(STATE_OPENED, "not.a.real_event")

    assert "OPENED" in str(excinfo.value)


def test_unknown_state_raises_illegal_transition() -> None:
    # Act / Assert
    with pytest.raises(IllegalTransition) as excinfo:
        transition("ATLANTIS", EVENT_APPROVED)

    assert "ATLANTIS" in str(excinfo.value)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (STATE_OPENED, False),
        (STATE_CLASSIFIED, False),
        (STATE_INTERVENING, False),
        (STATE_WAITING_OUTCOME, False),
        (STATE_HUMAN_REVIEW, False),
        (STATE_RECOVERED, True),
        (STATE_CLOSED_UNRECOVERED, True),
    ],
)
def test_is_terminal_only_for_the_two_terminal_states(state: str, expected: bool) -> None:
    # Act / Assert
    assert is_terminal(state) is expected
