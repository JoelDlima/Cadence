"""Channel tests: deterministic mocks, Resend live request shape, fallbacks, templates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from cadence.config import (
    AppConfig,
    ChannelConfig,
    CloudConfig,
    LLMConfig,
    PolicyConfig,
    RazorpayConfig,
)
from cadence.executors.channels import (
    EmailChannel,
    MockWhatsApp,
    build_channels,
    email_nudge_text,
    select_channel,
    whatsapp_nudge_text,
)
from cadence.policy.preferences import Preferences

pytestmark = [pytest.mark.unit]

_POLICY = PolicyConfig(
    touch_cap_per_window=3,
    touch_window_days=14,
    max_retry_attempts=3,
    quiet_hours_start=21,
    quiet_hours_end=9,
    timezone="Asia/Kolkata",
)

_LLM = LLMConfig(
    provider_order=["gemini"],
    gemini_api_key="",
    groq_api_key="",
    openrouter_api_key="",
    model_gemini="gemini-2.0-flash",
    model_groq="groq-model",
    model_openrouter="openrouter-model",
    daily_request_cap=10,
)


def _app_config(resend_api_key: str = "") -> AppConfig:
    return AppConfig(
        host="127.0.0.1",
        port=8000,
        db_path=Path("data/test.db"),
        log_level="INFO",
        razorpay=RazorpayConfig("", "", "whsec"),
        llm=_LLM,
        channels=ChannelConfig(resend_api_key=resend_api_key, email_from="cadence@example.com"),
        policy=_POLICY,
        cloud=CloudConfig("", "", False),
    )


def _expected_mock_ref(prefix: str, ref: str) -> str:
    digest = hashlib.sha1(ref.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:10]}"


def test_mock_whatsapp_is_deterministic_and_records_nothing() -> None:
    # Act
    first = MockWhatsApp().send(to_customer_id="cust-1", message="hi", ref="j-1:1:whatsapp")
    second = MockWhatsApp().send(to_customer_id="cust-2", message="different", ref="j-1:1:whatsapp")

    # Assert
    assert first == {"status": "sent", "ref": _expected_mock_ref("wa", "j-1:1:whatsapp")}
    assert first == second  # keyed by ref only; nothing external is recorded


def test_email_falls_back_to_deterministic_mock_without_api_key() -> None:
    # Arrange
    channel = EmailChannel(cfg=_app_config().channels)

    # Act
    result = channel.send(to_customer_id="cust-1", message="hello", ref="j-1:1:email")

    # Assert
    assert result["status"] == "sent"
    assert result["simulated"] is True
    assert result["ref"] == _expected_mock_ref("em", "j-1:1:email")


def test_live_email_posts_resend_shape_via_injected_transport() -> None:
    # Arrange
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"id": "email_abc123"})

    channel = EmailChannel(
        cfg=_app_config("re_test_key").channels,
        transport=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    # Act
    result = channel.send(to_customer_id="cust-9", message="please pay", ref="j-1:1:email")

    # Assert
    assert result == {"status": "sent", "ref": "email_abc123"}
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["authorization"] == "Bearer re_test_key"
    assert captured["body"]["from"] == "cadence@example.com"
    assert captured["body"]["to"] == ["cust-9@example.test"]
    assert captured["body"]["subject"] == "Action needed: your payment"
    assert captured["body"]["text"] == "please pay"


def test_build_channels_wires_whatsapp_and_simulated_email_by_default() -> None:
    # Act
    channels = build_channels(_app_config())

    # Assert
    assert isinstance(channels["whatsapp"], MockWhatsApp)
    result = channels["email"].send(to_customer_id="c", message="m", ref="r")
    assert result["simulated"] is True


def test_build_channels_email_is_live_with_key() -> None:
    # Act
    channels = build_channels(_app_config("re_live"))

    # Assert
    assert isinstance(channels["email"], EmailChannel)
    assert channels["email"].cfg.email_is_live is True


def test_whatsapp_template_stays_under_160_chars_and_carries_amount_only() -> None:
    # Act / Assert
    plain = whatsapp_nudge_text(49900)
    linked = whatsapp_nudge_text(49900, link_url="https://rzp.io/i/sim_abcd1234")
    assert len(plain) <= 160
    assert len(linked) <= 160
    assert "499" in plain and "499" in linked
    assert "https://rzp.io/i/sim_abcd1234" in linked


def test_email_template_mentions_amount_and_link_without_personal_data() -> None:
    # Act
    text = email_nudge_text(129900, link_url="https://rzp.io/i/sim_x")

    # Assert
    assert "1299" in text
    assert "https://rzp.io/i/sim_x" in text


def test_whatsapp_template_appends_self_service_page_link_when_wired() -> None:
    page_url = "http://localhost:8000/pay/j_abc123"

    text = whatsapp_nudge_text(49900, page_url=page_url)

    assert f"Fix in one tap: {page_url}" in text
    assert "499" in text
    assert whatsapp_nudge_text(49900).find("Fix in one tap") == -1


def test_email_template_appends_self_service_page_line_when_wired() -> None:
    page_url = "https://cadence.example.com/pay/j_xyz"

    text = email_nudge_text(129900, page_url=page_url)

    assert f"Fix in one tap: {page_url}" in text
    assert email_nudge_text(129900).find("Fix in one tap") == -1


def test_select_channel_honors_customer_preference_over_score() -> None:
    # Arrange
    prefs = Preferences(
        customer_id="cust_1",
        allowed_channels=("email", "whatsapp"),
        preferred_window_start=0,
        preferred_window_end=24,
    )

    # Act
    channel = select_channel(score=95, prefs=prefs)

    # Assert
    assert channel == "email"


def test_select_channel_falls_back_to_score_triage_without_preferences() -> None:
    # Act / Assert
    assert select_channel(score=60, prefs=None) == "whatsapp"
    assert select_channel(score=59, prefs=None) == "email"
