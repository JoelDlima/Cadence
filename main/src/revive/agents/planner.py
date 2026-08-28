"""LLM-backed recovery planner producing Pydantic-validated proposals.

Two jobs, both bounded to the taxonomy:
- ``diagnose``: map an unclassifiable failure code/description onto one of the
  recoverable root causes (never HARD_DECLINE - only a human may stop recovery).
- ``propose``: pick one legal intervention for a diagnosed cause.

Every output is validated against the same taxonomy tables the deterministic
fast path uses, and the Policy Guardian still vetoes whatever comes back, so
the LLM can only ever choose from legal moves, never invent new ones.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from revive.agents.llm_client import BudgetExhausted, LLMClient
from revive.classify.taxonomy import HARD_DECLINE, ROOT_CAUSES, UNKNOWN

_DIAGNOSABLE_CAUSES: tuple[str, ...] = tuple(
    sorted(ROOT_CAUSES - {UNKNOWN, HARD_DECLINE})
)

SYSTEM_PROMPT = (
    "You are a payments recovery planner for subscription payments in India. "
    "Choose exactly one intervention from the provided legal list. "
    "Prefer the least intrusive option that could recover the payment. "
    'Respond with JSON only: {"intervention": "...", "delay_hours": number, "rationale": "..."}.'
)

DIAGNOSE_SYSTEM_PROMPT = (
    "You diagnose why a UPI AutoPay / recurring subscription debit failed in India, "
    "given the raw error code and description. Classify it as exactly one of the "
    "provided root causes. "
    'Respond with JSON only: {"root_cause": "...", "confidence": number, "rationale": "..."}.'
)


class PlannerProposal(BaseModel):
    intervention: str
    delay_hours: float = Field(ge=0, le=72)
    rationale: str = Field(max_length=300)
    provider: str = ""


class DiagnosisProposal(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0, le=1, default=0.5)
    rationale: str = Field(max_length=300)
    provider: str = ""


class PlannerAgent:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def propose(
        self,
        *,
        root_cause: str,
        legal_moves: list[str],
        failure_context: dict,
        attempt_no: int,
    ) -> PlannerProposal | None:
        user_prompt = json.dumps(
            {
                "root_cause": root_cause,
                "legal_moves": legal_moves,
                "failure_context": failure_context,
                "attempt_no": attempt_no,
            }
        )
        try:
            obj, provider = self._llm.complete_json(system=SYSTEM_PROMPT, prompt=user_prompt)
        except BudgetExhausted:
            return None
        if obj is None:
            return None
        try:
            proposal = PlannerProposal.model_validate(obj)
        except ValidationError:
            return None
        if proposal.intervention not in legal_moves:
            return None
        return proposal.model_copy(update={"provider": provider})

    def diagnose(
        self,
        *,
        failure_context: dict,
        attempt_no: int,
    ) -> DiagnosisProposal | None:
        """Map an unclassifiable failure onto one recoverable root cause, or None.

        HARD_DECLINE and UNKNOWN are deliberately absent from the candidate list:
        stopping recovery (HARD_DECLINE) and giving up (UNKNOWN->human) are human
        calls, never an LLM's.
        """
        user_prompt = json.dumps(
            {
                "candidate_root_causes": list(_DIAGNOSABLE_CAUSES),
                "failure_context": failure_context,
                "attempt_no": attempt_no,
            }
        )
        try:
            obj, provider = self._llm.complete_json(
                system=DIAGNOSE_SYSTEM_PROMPT, prompt=user_prompt
            )
        except BudgetExhausted:
            return None
        if obj is None:
            return None
        try:
            proposal = DiagnosisProposal.model_validate(obj)
        except ValidationError:
            return None
        if proposal.root_cause not in _DIAGNOSABLE_CAUSES:
            return None
        return proposal.model_copy(update={"provider": provider})
