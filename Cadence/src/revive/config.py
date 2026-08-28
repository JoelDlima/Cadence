"""Revive application configuration.

All values come from environment variables (see .env.example). Secrets are never
hardcoded. The config object is frozen after load.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else default


@dataclass(frozen=True)
class RazorpayConfig:
    key_id: str
    key_secret: str
    webhook_secret: str

    @property
    def is_live(self) -> bool:
        return bool(self.key_id and self.key_secret)


@dataclass(frozen=True)
class LLMConfig:
    provider_order: list[str]
    gemini_api_key: str
    groq_api_key: str
    openrouter_api_key: str
    model_gemini: str
    model_groq: str
    model_openrouter: str
    daily_request_cap: int
    ollama_base_url: str = "http://localhost:11434/v1"
    model_ollama: str = "llama3.1:8b"
    timeout_seconds: float = 20.0
    # Phase 9c: Sarvam AI (Indian-first, free tier, OpenAI-compatible).
    # The dataclass has these fields without defaults so existing test
    # constructors that pass them positionally keep working. We use
    # ``field(default=...)`` to keep them keyword-friendly.
    from dataclasses import field  # local import to keep top tidy
    sarvam_api_key: str = field(default="")
    model_sarvam: str = field(default="sarvam-m")

    def key_for(self, provider: str) -> str:
        return {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "openrouter": self.openrouter_api_key,
            "sarvam": self.sarvam_api_key,
            "ollama": "ollama",  # local server needs no API key
        }.get(provider, "")


@dataclass(frozen=True)
class ChannelConfig:
    resend_api_key: str
    email_from: str
    page_base_url: str = "http://localhost:8000"

    @property
    def email_is_live(self) -> bool:
        return bool(self.resend_api_key)


@dataclass(frozen=True)
class PolicyConfig:
    touch_cap_per_window: int
    touch_window_days: int
    max_retry_attempts: int
    quiet_hours_start: int
    quiet_hours_end: int
    timezone: str
    auto_approve_below_minor: int = 500_000
    require_human_above_minor: int = 5_000_000
    min_recovery_worth_minor: int = 10_000


@dataclass(frozen=True)
class CloudConfig:
    """Optional cloud mirror (Supabase). Server-side only; never client-exposed."""

    supabase_url: str
    supabase_service_key: str
    sync_enabled: bool

    @property
    def is_live(self) -> bool:
        return bool(self.sync_enabled and self.supabase_url and self.supabase_service_key)


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    db_path: Path
    log_level: str
    razorpay: RazorpayConfig
    llm: LLMConfig
    channels: ChannelConfig
    policy: PolicyConfig
    cloud: CloudConfig

    @property
    def llm_available(self) -> bool:
        return any(self.llm.key_for(p) for p in self.llm.provider_order)


def load_config() -> AppConfig:
    """Load config from environment. `.env` is loaded if present at CWD or Cadence/."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            break

    return AppConfig(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=_env_int("PORT", 8000),
        db_path=Path(os.environ.get("DB_PATH", "data/revive.db")),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        razorpay=RazorpayConfig(
            key_id=os.environ.get("RZP_KEY_ID", ""),
            key_secret=os.environ.get("RZP_KEY_SECRET", ""),
            webhook_secret=os.environ.get("RZP_WEBHOOK_SECRET", "revive_dev_webhook_secret"),
        ),
        llm=LLMConfig(
            provider_order=_env_list("LLM_PROVIDER_ORDER", ["gemini", "groq", "openrouter"]),  # noqa: E501
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            sarvam_api_key=os.environ.get("SARVAM_API_KEY", ""),
            model_gemini=os.environ.get("LLM_MODEL_GEMINI", "gemini-2.0-flash"),
            model_groq=os.environ.get("LLM_MODEL_GROQ", "llama-3.3-70b-versatile"),
            model_openrouter=os.environ.get(
                "LLM_MODEL_OPENROUTER", "meta-llama/llama-3.3-70b-instruct:free"
            ),
            model_sarvam=os.environ.get("LLM_MODEL_SARVAM", "sarvam-m"),
            daily_request_cap=_env_int("LLM_DAILY_REQUEST_CAP", 400),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            model_ollama=os.environ.get("LLM_MODEL_OLLAMA", "llama3.1:8b"),
        ),
        channels=ChannelConfig(
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            email_from=os.environ.get("EMAIL_FROM", "revive@example.com"),
            page_base_url=os.environ.get("PAGE_BASE_URL", "http://localhost:8000").rstrip("/"),
        ),
        policy=PolicyConfig(
            touch_cap_per_window=_env_int("TOUCH_CAP_PER_WINDOW", 3),
            touch_window_days=_env_int("TOUCH_WINDOW_DAYS", 14),
            max_retry_attempts=_env_int("MAX_RETRY_ATTEMPTS", 3),
            quiet_hours_start=_env_int("QUIET_HOURS_START", 21),
            quiet_hours_end=_env_int("QUIET_HOURS_END", 9),
            timezone=os.environ.get("TIMEZONE", "Asia/Kolkata"),
            auto_approve_below_minor=_env_int("AUTO_APPROVE_BELOW_MINOR", 500_000),
            require_human_above_minor=_env_int("REQUIRE_HUMAN_ABOVE_MINOR", 5_000_000),
            min_recovery_worth_minor=_env_int("MIN_RECOVERY_WORTH_MINOR", 10_000),
        ),
        cloud=CloudConfig(
            supabase_url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
            supabase_service_key=os.environ.get("SUPABASE_SERVICE_KEY", ""),
            sync_enabled=os.environ.get("CLOUD_SYNC_ENABLED", "false").lower() == "true",
        ),
    )

