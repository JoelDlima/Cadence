"""Smoke-verify the 5 lifecycle drills + the 3 dashboard endpoints.

Default run is offline and keyless against a throwaway SQLite file, so it is
safe to run in a loop (no real Razorpay links created, no Razorpay rate limit).

    .venv\\Scripts\\python.exe scripts\\verify_5_drills.py
    .venv\\Scripts\\python.exe scripts\\verify_5_drills.py --live   # uses .env keys

`--live` hits the real Razorpay test-mode API (real plink ids, a real
POST /payment_links/{id}/cancel) and the real LLM. Razorpay rate-limits
payment_link creation, so use it sparingly.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from cadence.api.app import create_app
from cadence.config import CloudConfig, LLMConfig, RazorpayConfig, load_config

LIVE = "--live" in sys.argv


def build_config():
    cfg = load_config()
    db_path = Path(tempfile.mkdtemp(prefix="cadence_drills_")) / "drills.sqlite3"
    overrides: dict = {"db_path": db_path}
    if not LIVE:
        overrides["razorpay"] = RazorpayConfig(
            key_id="", key_secret="", webhook_secret="drill-secret",
        )
        overrides["llm"] = dataclasses.replace(
            cfg.llm, gemini_api_key="", groq_api_key="",
            openrouter_api_key="", sarvam_api_key="", provider_order=[],
        )
        overrides["cloud"] = CloudConfig(
            supabase_url="", supabase_service_key="", sync_enabled=False,
        )
    return dataclasses.replace(cfg, **overrides), db_path


def main() -> int:
    cfg, db_path = build_config()
    print("=" * 72)
    print(f"mode: {'LIVE (real Razorpay + LLM)' if LIVE else 'OFFLINE (keyless simulator)'}")
    print(f"db:   {db_path}")
    client = TestClient(create_app(cfg=cfg))
    failures: list[str] = []

    def show(label: str, resp, cap: int = 900) -> dict | list:
        body = resp.json()
        ok = resp.status_code == 200
        print(f"\n[{'OK  ' if ok else 'FAIL'}] {label} -> HTTP {resp.status_code}")
        print(json.dumps(body, indent=2, default=str)[:cap])
        if not ok:
            failures.append(f"{label}: HTTP {resp.status_code}")
        return body

    r = client.get("/api/journeys")
    print(f"\nsanity: GET /api/journeys -> HTTP {r.status_code}, {len(r.json())} journeys")
    if r.status_code != 200:
        failures.append("GET /api/journeys")

    def fresh_reference() -> str:
        cust = client.post("/api/live/customer", json={
            "name": "Drill", "email": "drill@x.local", "contact": "+919999900000",
        }).json()
        fail = client.post("/api/live/failure", json={"customer_id": cust["id"]})
        if fail.status_code != 200:
            failures.append(f"/api/live/failure: HTTP {fail.status_code} {fail.text[:160]}")
            return ""
        return fail.json()["payment_link"]["reference_id"]

    drills = [
        ("force-paid", {"expect_state": "RECOVERED"}),
        ("force-failed", {"expect_state": "INTERVENING"}),
        ("force-expired", {"expect_state": "CLOSED_UNRECOVERED"}),
        ("complete-journey", {"expect_state": "RECOVERED"}),
    ]
    for name, spec in drills:
        ref = fresh_reference()
        if not ref:
            continue
        body = show(f"POST /api/live/lifecycle/{name}", client.post(
            f"/api/live/lifecycle/{name}", json={"reference_id": ref}))
        got = body.get("cadence_state") if isinstance(body, dict) else None
        if got != spec["expect_state"]:
            failures.append(f"{name}: cadence_state {got!r} != {spec['expect_state']!r}")

    ref = fresh_reference()
    if ref:
        show("POST /api/live/lifecycle/smart", client.post(
            "/api/live/lifecycle/smart",
            json={"reference_id": ref, "customer_hint": "pays after every nudge"}))

    rows = show("GET /api/dashboard/payment-links", client.get(
        "/api/dashboard/payment-links?limit=50"), cap=1200)
    if isinstance(rows, list):
        print(f"  -> {len(rows)} payment-link rows; "
              f"statuses={sorted({r['status'] for r in rows})}")
        if not rows:
            failures.append("dashboard/payment-links returned 0 rows")
    show("GET /api/dashboard/stats", client.get("/api/dashboard/stats"))
    show("GET /api/cloud/plinks", client.get("/api/cloud/plinks?limit=10"), cap=500)

    chain = client.get("/api/audit/verify").json()
    ok = bool(chain.get("chain_ok"))
    print(f"\n[{'OK  ' if ok else 'FAIL'}] audit chain: {chain}")
    if not ok:
        failures.append("audit chain broken")

    print("\n" + "=" * 72)
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("all drills + dashboard endpoints OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
