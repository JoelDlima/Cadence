"""PHASE 4: LLM-powered Hinglish message writer.

Called by the dispatcher when emitting a `WHATSAPP_NUDGE` or
`EMAIL_NUDGE` action. The LLM personalizes the message from a small
amount of customer context (subscription id, amount, last attempts,
preferred channel). The prompt, response, and token usage are
appended to the audit log as ``agent.thinking`` events so the SPA's
"Show me the agent thinking" button can render them in a chat-style
thread.

If the LLM fails (no key, rate limit, bad output) the writer falls
back to the static template at ``revive.executors.channels`` so
the demo never breaks.
"""

from __future__ import annotations

from typing import Any

from revive.agents.llm_client import LLMClient
from revive.events import E_LLM_THINKING, Event
from revive.executors.channels import email_nudge_text, whatsapp_nudge_text
from revive.logging_setup import get_logger
from revive.store.event_store import EventStore

log = get_logger("revive.agents.message_writer")


_SYSTEM = (
    "You write recovery-payment nudge messages for an Indian subscription "
    "business. The brand is Cadence. The customer has had a failed auto-debit "
    "and the system is about to send a one-line WhatsApp or email reminder. "
    "Return STRICT JSON: {\"subject\": <email subject or null>, "
    "\"body\": <one short message 1-3 sentences, warm not pushy, "
    "Hindi + English mix is fine>}. Never promise anything that isn't true. "
    "Never add emojis. Always include the recovery amount in INR. "
    "Don't mention 'AI' or 'system'."
)


def _build_prompt(
    *,
    amount_minor: int,
    attempt_no: int,
    link_url: str | None,
    locale_hint: str = "in",
) -> str:
    rupees = amount_minor / 100.0
    return (
        f"customer locale: {locale_hint}\n"
        f"outstanding amount: Rs.{rupees:.2f}\n"
        f"recovery attempt: #{attempt_no}\n"
        f"payment link: {link_url or 'use a self-service page'}\n"
        f"channel: whatsapp or email (see the body field you fill in)\n\n"
        "Return JSON with subject (email) and body."
    )


def write_nudge(
    *,
    store: EventStore,
    journey_id: str,
    channel: str,
    amount_minor: int,
    attempt_no: int,
    link_url: str | None,
    page_url: str | None,
    llm: LLMClient | None = None,
    locale_hint: str = "in",
) -> tuple[str, str | None]:
    """Personalize the nudge body for the given channel.

    Returns (body, subject-or-None). The body is either LLM-personalized
    or the static template. The prompt, response, and token usage are
    recorded as ``agent.thinking`` events on the journey.

    The function is deliberately a single-purpose (one nudge at a time)
    so the dispatcher's call site stays small. We do NOT use streaming;
    the LLM response is typically <200 tokens and the overhead of
    streaming is not worth it for a 5-min pitch video.
    """
    fallback_body, fallback_subject = _fallback(
        channel=channel, amount_minor=amount_minor,
        link_url=link_url, page_url=page_url,
    )
    if llm is None or not llm._cfg.provider_order or not any(
        llm._cfg.key_for(p) for p in llm._cfg.provider_order
    ):
        return fallback_body, fallback_subject

    prompt = _build_prompt(
        amount_minor=amount_minor, attempt_no=attempt_no,
        link_url=link_url, locale_hint=locale_hint,
    )
    now_iso = llm._clock.now().astimezone().isoformat() if hasattr(llm._clock, "now") else None
    try:
        obj, provider = llm.complete_json(
            system=_SYSTEM, prompt=prompt, max_tokens=220,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("llm nudge write failed: %r; falling back to template", exc)
        return fallback_body, fallback_subject

    if not isinstance(obj, dict):
        return fallback_body, fallback_subject
    body = str(obj.get("body") or "").strip()
    subject = obj.get("subject")
    if not body:
        return fallback_body, fallback_subject
    if len(body) > 800:  # noqa: PLR2004
        body = body[:797] + "..."

    # Record the agent thinking event
    try:
        store.append(
            event_type=E_LLM_THINKING,
            aggregate_type="journey",
            aggregate_id=journey_id,
            payload={
                "agent": "nudge_writer",
                "channel": channel,
                "provider": provider,
                "system": _SYSTEM,
                "prompt": prompt,
                "response": obj,
                "subject": subject,
                "body": body,
            },
            occurred_at=now_iso,
            recorded_at=now_iso,
            event_id=f"llm_nudge_{journey_id}_{attempt_no}_{channel}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not append agent.thinking event: %r", exc)

    return body, (str(subject) if subject else None)


def _fallback(
    *,
    channel: str,
    amount_minor: int,
    link_url: str | None,
    page_url: str | None,
) -> tuple[str, str | None]:
    if channel == "whatsapp":
        return whatsapp_nudge_text(
            amount_minor=amount_minor, link_url=link_url, page_url=page_url
        ), None
    if channel == "email":
        body = email_nudge_text(
            amount_minor=amount_minor, link_url=link_url, page_url=page_url
        )
        return body, "Action needed: your Cadence subscription payment"
    return whatsapp_nudge_text(
        amount_minor=amount_minor, link_url=link_url, page_url=page_url
    ), None
