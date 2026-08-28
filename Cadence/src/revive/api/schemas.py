"""Control-room API schemas (Phase E).

Response models are intentionally narrow projections of the read models: the
console never sees hashes, dedupe keys, or queue internals.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JourneyOut(BaseModel):
    journey_id: str
    subscription_id: str
    customer_id: str
    state: str
    root_cause: str | None = None
    amount_minor: int | None = None
    attempts_used: int
    touches_used: int
    score: int | None = None
    opened_at: str
    updated_at: str


class EventOut(BaseModel):
    seq: int
    occurred_at: str
    type: str
    payload: dict[str, Any]


class MetricsOut(BaseModel):
    recovered_inr_major: float
    journeys_by_state: dict[str, int]
    llm_requests_today: int
    violations: int


class StatusOut(BaseModel):
    """DEMO/LIVE mode and which keys are present.

    DEMO = no Razorpay/Resend/Supabase/LLM keys configured -> every external
    dependency uses a deterministic simulator. LIVE = at least one key is set
    and the live code path is active for that dependency.
    """
    mode: str  # "DEMO" or "LIVE"
    razorpay_keys_present: bool
    resend_key_present: bool
    supabase_keys_present: bool
    llm_keys_present: bool
    phoenix_enabled: bool
    db_event_count: int
    db_path: str


class AttentionOut(BaseModel):
    """Items the human should look at: human-review, high-value, paused-by-outage."""
    journey_id: str
    subscription_id: str
    customer_id: str
    amount_minor: int
    state: str
    root_cause: str | None
    reason: str  # "human_review" | "high_value" | "bank_outage"
    updated_at: str


class BanksOut(BaseModel):
    """Per-bank outage status derived from the last 24h of events."""
    bank_name: str
    failure_count: int
    threshold: int
    is_holding: bool


class AuditVerifyOut(BaseModel):
    chain_ok: bool
    event_count: int
    last_hash: str
    verified_at: str
    first_bad_seq: int | None = None


class LlmSpendOut(BaseModel):
    """Per-provider daily spend."""
    providers: list[dict[str, Any]]  # [{provider, requests, tokens_in, tokens_out, cap}]


class GuardianStatsOut(BaseModel):
    total_vetoes: int
    by_reason: dict[str, int]


class EvalSummaryOut(BaseModel):
    n: int
    seed: int
    naive_recovered_inr: float
    naive_recovery_pct: float
    revive_recovered_inr: float
    revive_recovery_pct: float
    uplift_pct: float
    contacts_naive: int
    contacts_recovery_naive: float
    contacts_recovery_revive: float
    fast_path_pct: float
    source: str  # "live" (re-ran) or "cached" (read eval-metrics.json)


class ChaosResultOut(BaseModel):
    drill: str
    passed: bool
    detail: str


class InjectIn(BaseModel):
    """Body for /api/test/inject. Backend signs with RZP_WEBHOOK_SECRET and
    posts the same webhook Razorpay would send. Works in DEMO mode (default
    dev secret) and in LIVE mode (configured secret)."""
    subscription_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(min_length=1, max_length=128)
    failure_code: str = Field(min_length=1, max_length=64)
    error_description: str | None = None
    amount_minor: int = Field(ge=0, le=1_000_000_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)


class InjectOut(BaseModel):
    http_status: int
    body: dict[str, Any]
    signature_prefix: str  # first 8 chars of the HMAC for proof-of-receipt


class PaySimulateIn(BaseModel):
    """Body for /api/pay/{id}/simulate-paid: only valid in DEMO mode."""
    note: str | None = None


class PayLinkOut(BaseModel):
    short_url: str
    mode: str  # "DEMO" or "LIVE"
    simulated: bool


class CloudStatusOut(BaseModel):
    """Cloud-mirror connection state for /api/cloud/status.

    Reports whether the mirror is configured, when it last synced, how many
    rows were pushed, and the last error if any. The local SQLite DB is
    always the source of truth; this only describes the read-side dashboard
    mirror.
    """
    enabled: bool            # CLOUD_SYNC_ENABLED=true AND keys present
    sync_state: str          # "offline" | "online" | "error"
    last_journeys_sync_at: str | None
    last_metrics_sync_at: str | None
    last_journeys_pushed: int
    last_metrics_pushed: int
    last_journeys_error: str | None
    last_metrics_error: str | None
    supabase_url_configured: bool
    service_key_configured: bool


class CircularOut(BaseModel):
    """One ingested regulatory document."""
    id: int
    source: str
    title: str
    issued_on: str | None
    reference: str | None
    path: str
    summary: str
    rules: list[dict]
    ingested_at: str


class CircularDetailOut(CircularOut):
    text: str  # full plain-text body


class CircularIngestResultOut(BaseModel):
    """Result of a directory scan + ingest."""
    scanned: int
    ingested: int
    circulars: list[CircularOut]


class KillSwitchIn(BaseModel):
    enabled: bool


class PreferencesIn(BaseModel):
    allowed_channels: list[str] = Field(min_length=1)
    window_start: int = Field(ge=0, le=24)
    window_end: int = Field(ge=0, le=24)


class PreferencesOut(BaseModel):
    customer_id: str
    allowed_channels: list[str]
    window_start: int
    window_end: int
