"""Pre-flight check: which integrations are LIVE, which are SIMULATED?

Run from Cadence/:  python scripts/live_check.py

Reads Cadence/.env (via load_config) and probes each integration with the
cheapest possible real call where safe. Prints a table you can paste into a
demo README or judge notes; exit code is always 0. No keys configured is a
valid outcome - the whole product runs simulated (see the README honesty
table); this script just tells you which world you are in.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from cadence.agents.llm_client import LLMClient
from cadence.clock import SystemClock
from cadence.config import load_config
from cadence.store.db import Database

_WIDTH = 62


def _row(name: str, state: str, detail: str) -> None:
    print(f"  {name:<20} {state:<12} {detail}")


def _header() -> None:
    print("=" * _WIDTH)
    print("Cadence live-check")
    print("=" * _WIDTH)


def check_razorpay(cfg) -> None:
    if not cfg.razorpay.is_live:
        _row("Razorpay API", "SIMULATED", "no RZP_KEY_ID/SECRET - deterministic client")
        return
    try:
        token = httpx.BasicAuth(cfg.razorpay.key_id, cfg.razorpay.key_secret)
        resp = httpx.get(
            "https://api.razorpay.com/v1/payments", params={"count": 1}, auth=token, timeout=15
        )
        if resp.status_code == 200:
            _row("Razorpay API", "LIVE", "auth OK, test-mode REST reachable")
        elif resp.status_code == 401:
            _row("Razorpay API", "BROKEN", "keys rejected (HTTP 401) - check id/secret")
        else:
            _row("Razorpay API", "LIVE?", f"auth reached Razorpay (HTTP {resp.status_code})")
    except httpx.HTTPError as exc:
        _row("Razorpay API", "LIVE?", f"network error probing: {exc}")
    secret = cfg.razorpay.webhook_secret
    if secret == "cadence_dev_webhook_secret":
        _row("Webhook secret", "DEV DEFAULT", "set RZP_WEBHOOK_SECRET before real webhooks")
    else:
        _row("Webhook secret", "SET", f"{len(secret)} chars; must equal Supabase secret")


def check_llm(cfg, db, clock) -> None:
    if not cfg.llm_available:
        _row("LLM planner", "SIMULATED", "no keys - deterministic fast path only")
        return
    client = LLMClient(cfg=cfg.llm, db=db, clock=clock)
    obj, provider = client.complete_json(
        system='Reply with JSON only: {"ok": true}', prompt="ping"
    )
    if obj is None:
        _row("LLM planner", "BROKEN", f"chain {cfg.llm.provider_order} answered nothing")
        return
    model = {
        "gemini": cfg.llm.model_gemini,
        "groq": cfg.llm.model_groq,
        "openrouter": cfg.llm.model_openrouter,
        "ollama": cfg.llm.model_ollama,
    }.get(provider, "?")
    _row("LLM planner", "LIVE", f"{provider} ({model}) answered; cap {cfg.llm.daily_request_cap}/day")


def check_email(cfg) -> None:
    if cfg.channels.email_is_live:
        _row("Email (Resend)", "LIVE", f"from {cfg.channels.email_from}; real sends on")
    else:
        _row("Email (Resend)", "SIMULATED", "no RESEND_API_KEY - mocked send refs")
    _row("WhatsApp", "SIMULATED", "always mocked (see honesty table)")


def check_cloud(cfg) -> None:
    if not cfg.cloud.is_live:
        _row("Supabase", "OFFLINE", "not configured - local SQLite only")
        return
    try:
        resp = httpx.get(
            f"{cfg.cloud.supabase_url}/rest/v1/webhook_inbox",
            params={"select": "id", "limit": 1},
            headers={"apikey": cfg.cloud.supabase_service_key},
            timeout=15,
        )
        if resp.status_code == 200:
            _row("Supabase", "LIVE", f"inbox reachable at {cfg.cloud.supabase_url}")
        else:
            _row("Supabase", "BROKEN", f"HTTP {resp.status_code} - check schema/keys")
    except httpx.HTTPError as exc:
        _row("Supabase", "BROKEN", f"network error: {exc}")


def main() -> None:
    cfg = load_config()
    _header()
    check_razorpay(cfg)
    db = Database(cfg.db_path)
    check_llm(cfg, db, SystemClock())
    check_email(cfg)
    check_cloud(cfg)
    db.close()
    print("=" * _WIDTH)
    print("Simulated pieces are honest stand-ins, not missing features:")
    print("see README 'What is real vs simulated'.")
    print("LIVE wiring: paste keys into Cadence/.env (copy .env.example), rerun.")


if __name__ == "__main__":
    main()


