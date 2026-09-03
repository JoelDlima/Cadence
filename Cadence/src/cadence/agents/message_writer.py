"""PHASE 6: LLM-powered Hinglish message writer + support summarizer.

When the dispatcher fires a WHATSAPP_NUDGE / EMAIL_NUDGE it calls
MessageWriter.write_nudge(); that picks the right model from the
provider chain (gemini -> groq -> openrouter -> sarvam) and returns
the personalized body. Every LLM call:
- gets a JSON response: {"subject": str|null, "body": str}
- caps WhatsApp body at 480 chars (the spec limit; we truncate + ellipsis)
- has a hard fallback to the static templates in
  cadence.executors.channels if the LLM fails (no key, budget exhausted,
  5xx, bad output, or budget still over daily cap)
- logs an "agent.thinking" event to the audit chain with prompt,
  response, provider, tokens used, and source ("llm" | "template")
- never blocks the send path on a failed LLM

summarize_journey() is a 3-sentence merchant-facing summary. Same
fallback policy.

Design: the writer is a single-purpose stateless function so the
dispatcher can call it inline. It does NOT use streaming; the
typical response is <200 tokens and streaming overhead is not
worth the demo.
"""

from __future__ import annotations

import uuid
from typing import Any

from cadence.agents.llm_client import LLMClient
from cadence.clock import Clock
from cadence.events import E_LLM_THINKING
from cadence.executors.channels import email_nudge_text, whatsapp_nudge_text
from cadence.logging_setup import get_logger
from cadence.store.event_store import EventStore

log = get_logger("cadence.agents.message_writer")

_NUDGE_SYSTEM = (
    "You write recovery-payment nudge messages for an Indian subscription "
    "business. The brand is Cadence. The customer had a failed auto-debit "
    "and the system is about to send a one-line WhatsApp or email reminder. "
    "Return STRICT JSON: {\"subject\": <email subject or null>, "
    "\"body\": <one short message 1-3 sentences, warm not pushy, "
    "Hindi + English mix is fine>}. Never promise anything that isn't true. "
    "Never add emojis. Always include the recovery amount in INR. "
    "Don't mention 'AI' or 'system'."
)

_SUMMARY_SYSTEM = (
    "You write a 3-sentence plain-English summary for a merchant support "
    "team. Cover: what failed, what the agent did, and what the customer "
    "should expect next. Be specific (include the recovery amount, the "
    "intervention type, the attempt number, and whether the journey is "
    "still open or closed). Return STRICT JSON: {\"summary\": str}. "
    "Never mention 'AI' or 'system'."
)

_WHATSAPP_MAX = 480


def _build_nudge_prompt(
    *,
    amount_minor: int,
    attempt_no: int,
    link_url: str | None,
    language: str = "hinglish",
) -> str:
    rupees = amount_minor / 100.0
    return (
        f"customer locale: {language}\n"
        f"outstanding amount: Rs.{rupees:.2f}\n"
        f"recovery attempt: #{attempt_no}\n"
        f"payment link: {link_url or 'use the self-service page'}\n"
        f"channel: whatsapp or email (the body field you fill in)\n\n"
        "Return JSON with subject (email) and body."
    )


def _build_summary_prompt(
    *,
    journey_id: str,
    cause: str,
    amount_minor: int,
    last_intervention: str,
    last_outcome: str,
    state: str,
) -> str:
    return (
        f"journey id: {journey_id}\n"
        f"state: {state}\n"
        f"root cause: {cause}\n"
        f"outstanding amount: Rs.{amount_minor / 100:.2f}\n"
        f"last intervention: {last_intervention}\n"
        f"last outcome: {last_outcome}\n\n"
        "Return JSON with a 3-sentence summary field."
    )


def _fallback_text(
    *, channel: str, amount_minor: int, link_url: str | None,
) -> tuple[str, str | None]:
    if channel == "whatsapp":
        return whatsapp_nudge_text(amount_minor, link_url=link_url), None
    body = email_nudge_text(amount_minor, link_url=link_url)
    return body, "Action needed: your Cadence subscription payment"


def _record_thinking(
    *,
    store: EventStore | None,
    clock: Clock,
    agent: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> None:
    if store is None:
        return
    now_iso = clock.now().astimezone().isoformat()
    try:
        store.append(
            event_type=E_LLM_THINKING,
            aggregate_type="journey",
            aggregate_id=aggregate_id,
            payload=payload,
            occurred_at=now_iso,
            recorded_at=now_iso,
            event_id=f"llm_{uuid.uuid4().hex[:12]}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not append agent.thinking event: %r", exc)


def _has_any_provider(llm: LLMClient | None) -> bool:
    if llm is None:
        return False
    if not llm._cfg.provider_order:
        return False
    return any(llm._cfg.key_for(p) for p in llm._cfg.provider_order)


def write_nudge(
    *,
    store: EventStore | None,
    llm: LLMClient | None,
    clock: Clock,
    journey_id: str,
    channel: str,
    amount_minor: int,
    attempt_no: int,
    link_url: str | None = None,
    language: str = "hinglish",
) -> tuple[str, str | None]:
    """Personalize the nudge body. Falls back to the static template if no
    LLM is configured, the LLM raises, the budget is exhausted, or the
    response shape is invalid. Always records the call in the audit chain
    as agent.thinking (or a no-op if store is None).

    Returns (body, subject-or-None).
    """
    fallback_body, fallback_subject = _fallback_text(
        channel=channel, amount_minor=amount_minor, link_url=link_url,
    )
    if not _has_any_provider(llm):
        _record_thinking(
            store=store, clock=clock, agent="nudge_writer",
            aggregate_id=journey_id,
            payload={
                "agent": "nudge_writer",
                "channel": channel, "provider": None,
                "system": _NUDGE_SYSTEM,
                "prompt": "(no LLM configured; using static template)",
                "response": None,
                "subject": fallback_subject, "body": fallback_body,
                "source": "template", "tokens_in": 0, "tokens_out": 0,
            },
        )
        return fallback_body, fallback_subject

    prompt = _build_nudge_prompt(
        amount_minor=amount_minor, attempt_no=attempt_no,
        link_url=link_url, language=language,
    )
    try:
        obj, provider = llm.complete_json(
            system=_NUDGE_SYSTEM, prompt=prompt, max_tokens=220,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("llm nudge write failed: %r; falling back to template", exc)
        _record_thinking(
            store=store, clock=clock, agent="nudge_writer",
            aggregate_id=journey_id,
            payload={
                "channel": channel, "provider": None,
                "system": _NUDGE_SYSTEM, "prompt": prompt,
                "response": {"error": repr(exc)},
                "subject": fallback_subject, "body": fallback_body,
                "source": "template_fallback", "tokens_in": 0, "tokens_out": 0,
            },
        )
        return fallback_body, fallback_subject

    if not isinstance(obj, dict):
        _record_thinking(
            store=store, clock=clock, agent="nudge_writer",
            aggregate_id=journey_id,
            payload={
                "channel": channel, "provider": provider,
                "system": _NUDGE_SYSTEM, "prompt": prompt, "response": obj,
                "subject": fallback_subject, "body": fallback_body,
                "source": "template_fallback", "tokens_in": 0, "tokens_out": 0,
            },
        )
        return fallback_body, fallback_subject

    body = str(obj.get("body") or "").strip()
    subject = obj.get("subject")
    subject_str = str(subject) if subject else fallback_subject
    if not body:
        _record_thinking(
            store=store, clock=clock, agent="nudge_writer",
            aggregate_id=journey_id,
            payload={
                "channel": channel, "provider": provider,
                "system": _NUDGE_SYSTEM, "prompt": prompt, "response": obj,
                "subject": fallback_subject, "body": fallback_body,
                "source": "template_fallback", "tokens_in": 0, "tokens_out": 0,
            },
        )
        return fallback_body, fallback_subject

    if channel == "whatsapp" and len(body) > _WHATSAPP_MAX:
        body = body[: _WHATSAPP_MAX - 3] + "..."
    if subject_str and len(subject_str) > 78:
        subject_str = subject_str[:75] + "..."

    _record_thinking(
        store=store, clock=clock, agent="nudge_writer",
        aggregate_id=journey_id,
        payload={
            "channel": channel, "provider": provider,
            "system": _NUDGE_SYSTEM, "prompt": prompt, "response": obj,
            "subject": subject_str, "body": body,
            "source": "llm", "tokens_in": len(prompt) // 4,
            "tokens_out": len(body) // 4,
        },
    )
    return body, subject_str


def summarize_journey(
    *,
    store: EventStore | None,
    llm: LLMClient | None,
    clock: Clock,
    journey_id: str,
    cause: str,
    amount_minor: int,
    last_intervention: str,
    last_outcome: str,
    state: str,
) -> str:
    """3-sentence merchant support summary. Deterministic fallback when
    no LLM is configured or the LLM call fails."""
    fallback = (
        f"Customer's Rs.{amount_minor / 100:.2f} payment failed ({cause}). "
        f"The agent attempted {last_intervention}, which {last_outcome}. "
        f"Journey is currently {state}; no further action pending."
    )
    if not _has_any_provider(llm):
        if store is not None:
            _record_thinking(
                store=store, clock=clock, agent="summary_writer",
                aggregate_id=journey_id,
                payload={"source": "deterministic", "summary": fallback},
            )
        return fallback

    prompt = _build_summary_prompt(
        journey_id=journey_id, cause=cause, amount_minor=amount_minor,
        last_intervention=last_intervention, last_outcome=last_outcome, state=state,
    )
    try:
        obj, provider = llm.complete_json(
            system=_SUMMARY_SYSTEM, prompt=prompt, max_tokens=240,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("llm summary failed: %r; falling back", exc)
        return fallback

    if not isinstance(obj, dict):
        return fallback
    summary = str(obj.get("summary") or "").strip()
    if not summary:
        return fallback

    _record_thinking(
        store=store, clock=clock, agent="summary_writer",
        aggregate_id=journey_id,
        payload={"provider": provider, "source": "llm", "summary": summary},
    )
    return summary
