"""Outbound customer channels: WhatsApp mock + Resend-backed email.

Deterministic by default so demos and tests run offline with zero keys;
``EmailChannel`` speaks the real Resend API only when a key is configured.
Transports are injectable (``httpx.Client(transport=httpx.MockTransport(...))``)
so tests pin exact request shapes. Message templates carry no personal data
beyond the amount: customer identity stays inside the send envelope.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import httpx

from cadence.config import AppConfig, ChannelConfig
from cadence.policy.preferences import Preferences

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 15.0
_EMAIL_SUBJECT = "Action needed: your payment"
_WHATSAPP_SCORE_FLOOR = 60  # score semantics from cadence.policy.score


def _sha1_hex(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


class Channel(Protocol):
    """Minimal outbound surface the dispatcher depends on."""

    def send(self, *, to_customer_id: str, message: str, ref: str) -> dict:
        """Deliver ``message``; return {"status": "sent", "ref": <provider ref>}."""
        ...


# --- message templates (amount is the ONLY personal datum) --------------------


def _rupees(amount_minor: int) -> str:
    return f"\u20b9{amount_minor // 100}"


def _with_page_line(text: str, page_url: str | None) -> str:
    """Append the self-service recovery page line when a page base is wired."""
    if page_url:
        return f"{text} Fix in one tap: {page_url}"
    return text


def whatsapp_nudge_text(
    amount_minor: int, link_url: str | None = None, page_url: str | None = None
) -> str:
    """Warm Hinglish WhatsApp reminder; optional Razorpay and self-service links."""
    amount = _rupees(amount_minor)
    if link_url:
        text = f"Hi! Aapka {amount} ka payment pending hai. Pay karne ke liye: {link_url} - Cadence"
    else:
        text = (
            f"Hi! Aapka {amount} ka payment pending hai. "
            "Jab convenient ho pay kar dijiye, hum help ke liye ready hain. - Cadence"
        )
    return _with_page_line(text, page_url)


def email_nudge_text(
    amount_minor: int, link_url: str | None = None, page_url: str | None = None
) -> str:
    """Plain-text email body: polite, warm, opt-out honored via DND upstream."""
    amount = _rupees(amount_minor)
    lines = [
        "Hi,",
        "",
        f"Aapka {amount} ka subscription payment pending hai. Koi baat nahi -",
    ]
    if link_url:
        lines.append(f"jab convenient ho, yahan pay kar dijiye: {link_url}")
    else:
        lines.append("jab convenient ho, payment complete kar dijiye.")
    if page_url:
        lines.append(f"Fix in one tap: {page_url}")
    lines += [
        "",
        "Agar koi dikkat ho toh bas reply kijiye, hum dekh lenge.",
        "",
        "- Team Cadence",
    ]
    return "\n".join(lines)


# --- channel implementations --------------------------------------------------


@dataclass(frozen=True)
class MockWhatsApp:
    """Deterministic offline WhatsApp stand-in; records nothing external."""

    def send(self, *, to_customer_id: str, message: str, ref: str) -> dict:
        return {"status": "sent", "ref": f"wa_{_sha1_hex(ref)[:10]}"}


@dataclass(frozen=True)
class TwilioWhatsAppChannel:
    """Twilio REST client for WhatsApp with template fallback for sandbox/trial."""

    cfg: ChannelConfig
    transport: httpx.Client | None = None

    def send(self, *, to_customer_id: str, message: str, ref: str) -> dict:
        if not self.cfg.whatsapp_is_live:
            return {"status": "sent", "ref": f"wa_{_sha1_hex(ref)[:10]}", "simulated": True}

        raw_to = to_customer_id
        if not raw_to.startswith("+") and not raw_to.startswith("whatsapp:+"):
            raw_to = self.cfg.user_phone or "+919876543210"

        to_num = raw_to if raw_to.startswith("whatsapp:") else f"whatsapp:{raw_to}"
        from_num = self.cfg.twilio_whatsapp_from or "whatsapp:+17372508034"
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.cfg.twilio_account_sid}/Messages.json"
        import base64 as _b64
        auth_header = f"Basic {_b64.b64encode(f'{self.cfg.twilio_api_key}:{self.cfg.twilio_api_secret}'.encode()).decode()}"
        headers = {"Authorization": auth_header}

        def _exec(post_data: dict) -> httpx.Response:
            if self.transport is not None:
                req = httpx.Request("POST", url, data=post_data, headers=headers)
                return self.transport.send(req)
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                return client.post(url, data=post_data, headers=headers)

        # 1. First attempt sending the freeform message body
        data = {
            "From": from_num,
            "To": to_num,
            "Body": message,
        }
        resp = _exec(data)
        if resp.status_code in (200, 201):
            sid = str(dict(resp.json()).get("sid", ref))
            return {"status": "sent", "ref": sid, "delivered_to": to_num, "method": "freeform"}

        # If trial/sandbox requires ContentSid (error 21654)
        err_body = {}
        try:
            err_body = resp.json()
        except Exception:
            pass

        if err_body.get("code") == 21654 or "ContentSid" in str(err_body.get("message", "")):
            content_sid = self.cfg.twilio_content_sid or "HXfe5ab5f00277942d4d4200328b4d403c"
            fb_data = {
                "From": from_num,
                "To": to_num,
                "ContentSid": content_sid,
            }
            fb_resp = _exec(fb_data)
            if fb_resp.status_code in (200, 201):
                sid = str(dict(fb_resp.json()).get("sid", ref))
                return {"status": "sent", "ref": sid, "delivered_to": to_num, "method": "template"}
            fb_resp.raise_for_status()

        resp.raise_for_status()
        return {"status": "sent", "ref": f"wa_{_sha1_hex(ref)[:10]}"}


@dataclass(frozen=True)
class EmailChannel:
    """Resend REST client when configured; deterministic simulated mock otherwise."""

    cfg: ChannelConfig
    transport: httpx.Client | None = None

    def send(self, *, to_customer_id: str, message: str, ref: str) -> dict:
        if not self.cfg.email_is_live:
            return {"status": "sent", "ref": f"em_{_sha1_hex(ref)[:10]}", "simulated": True}
        body = {
            "from": self.cfg.email_from,
            "to": [f"{to_customer_id}@example.test"],
            "subject": _EMAIL_SUBJECT,
            "text": message,
        }
        request = httpx.Request("POST", _RESEND_URL, json=body)
        response = self._send(request)
        response.raise_for_status()
        provider_ref = str(dict(response.json()).get("id", ref))
        return {"status": "sent", "ref": provider_ref}

    def _send(self, request: httpx.Request) -> httpx.Response:
        request.headers["Authorization"] = f"Bearer {self.cfg.resend_api_key}"
        if self.transport is not None:
            return self.transport.send(request)
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            return client.send(request)


def build_channels(
    cfg: AppConfig, transport: httpx.Client | None = None
) -> dict[str, Channel]:
    """Wire the channel set: WhatsApp live when Twilio keys present, email live iff key present."""
    wa: Channel = (
        TwilioWhatsAppChannel(cfg=cfg.channels, transport=transport)
        if cfg.channels.whatsapp_is_live
        else MockWhatsApp()
    )
    return {
        "whatsapp": wa,
        "email": EmailChannel(cfg=cfg.channels, transport=transport),
    }


def select_channel(*, score: int, prefs: Preferences | None) -> str:
    """Preference-aware channel triage (backlog item 9): a stored preference wins,
    otherwise the recovery score picks the channel (high -> whatsapp, low -> email)."""
    if prefs is not None and prefs.allowed_channels:
        return prefs.allowed_channels[0]
    return "whatsapp" if score >= _WHATSAPP_SCORE_FLOOR else "email"


__all__ = [
    "Channel",
    "EmailChannel",
    "MockWhatsApp",
    "TwilioWhatsAppChannel",
    "build_channels",
    "email_nudge_text",
    "select_channel",
    "whatsapp_nudge_text",
]
