"""Unit tests for the planner agent: validation, legality gate, fallback on failure."""

from __future__ import annotations

from revive.agents.planner import PlannerAgent, PlannerProposal
from revive.classify.taxonomy import LEGAL_MOVES, NO_FUNDS


class FakeLLM:
    def __init__(self, scripted: list[dict | None]) -> None:
        self._scripted = iter(scripted)
        self.prompts: list[str] = []

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_hint: dict | None = None,
        max_tokens: int = 500,
    ) -> tuple[dict | None, str]:
        self.prompts.append(prompt)
        return next(self._scripted), "fake"


def _agent(fake: FakeLLM) -> PlannerAgent:
    return PlannerAgent(llm=fake)  # type: ignore[arg-type]


def test_valid_proposal_accepted_and_within_legal_list() -> None:
    legal = sorted(LEGAL_MOVES[NO_FUNDS])
    scripted = [
        {"intervention": "RETRY_PAYDAY", "delay_hours": 24.0, "rationale": "retry after salary"}
    ]
    fake = FakeLLM(scripted)

    proposal = _agent(fake).propose(
        root_cause=NO_FUNDS, legal_moves=legal, failure_context={}, attempt_no=1
    )

    assert proposal is not None
    assert proposal == PlannerProposal(
        intervention="RETRY_PAYDAY",
        delay_hours=24.0,
        rationale="retry after salary",
        provider="fake",
    )
    assert proposal.intervention in legal
    assert "NO_FUNDS" in fake.prompts[0]
    assert "attempt_no" in fake.prompts[0]


def test_intervention_outside_legal_moves_returns_none() -> None:
    legal = sorted(LEGAL_MOVES[NO_FUNDS])
    assert "HUMAN_REVIEW" not in legal
    scripted = [{"intervention": "HUMAN_REVIEW", "delay_hours": 0.0, "rationale": "escalate"}]

    result = _agent(FakeLLM(scripted)).propose(
        root_cause=NO_FUNDS, legal_moves=legal, failure_context={}, attempt_no=1
    )

    assert result is None


def test_invalid_json_output_returns_none() -> None:
    legal = sorted(LEGAL_MOVES[NO_FUNDS])

    result = _agent(FakeLLM([None])).propose(
        root_cause=NO_FUNDS, legal_moves=legal, failure_context={}, attempt_no=1
    )

    assert result is None


def test_delay_hours_out_of_bounds_fails_validation() -> None:
    legal = sorted(LEGAL_MOVES[NO_FUNDS])
    scripted = [{"intervention": "RETRY_PAYDAY", "delay_hours": 999.0, "rationale": "too long"}]

    result = _agent(FakeLLM(scripted)).propose(
        root_cause=NO_FUNDS, legal_moves=legal, failure_context={}, attempt_no=1
    )

    assert result is None


def test_rationale_over_max_length_fails_validation() -> None:
    legal = sorted(LEGAL_MOVES[NO_FUNDS])
    scripted = [
        {
            "intervention": "RETRY_PAYDAY",
            "delay_hours": 24.0,
            "rationale": "x" * 301,
        }
    ]

    result = _agent(FakeLLM(scripted)).propose(
        root_cause=NO_FUNDS, legal_moves=legal, failure_context={}, attempt_no=1
    )

    assert result is None


def test_rationale_at_exact_limit_is_accepted() -> None:
    legal = sorted(LEGAL_MOVES[NO_FUNDS])
    scripted = [{"intervention": "RETRY_PAYDAY", "delay_hours": 24.0, "rationale": "y" * 300}]

    result = _agent(FakeLLM(scripted)).propose(
        root_cause=NO_FUNDS, legal_moves=legal, failure_context={}, attempt_no=1
    )

    assert result is not None and result.rationale == "y" * 300
