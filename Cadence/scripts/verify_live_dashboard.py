"""Live end-to-end smoke against an ALREADY RUNNING engine (real Razorpay).

    .venv\\Scripts\\python.exe scripts\\verify_live_dashboard.py [base_url]

Proves the Phase 2 claim: a payment link created by the live flow shows up on
GET /api/dashboard/payment-links within seconds, and force-paid flips both the
row status and the journey state. Creates ONE real Razorpay test-mode link per
run (Razorpay rate-limits payment_link creation, so do not loop this).
"""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
failures: list[str] = []


def show(label: str, payload: object, cap: int = 700) -> None:
    print(f"\n--- {label}")
    print(json.dumps(payload, indent=2, default=str)[:cap])


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=45.0) as c:
        status = c.get("/api/status").json()
        print(f"engine: mode={status['mode']} events={status['db_event_count']} db={status['db_path']}")

        before = c.get("/api/dashboard/payment-links?limit=200").json()
        print(f"payment-link rows before: {len(before)}")

        cust = c.post("/api/live/customer", json={
            "name": "Dashboard Smoke", "email": "smoke@x.local", "contact": "+919999900001",
        }).json()
        print(f"customer: {cust['id']} simulated={cust['simulated']}")

        r = c.post("/api/live/failure", json={"customer_id": cust["id"]})
        if r.status_code != 200:
            print(f"FAIL /api/live/failure -> HTTP {r.status_code}: {r.text[:300]}")
            return 1
        failure = r.json()
        plink = failure["payment_link"]
        show("live failure", failure)

        # Phase 2 claim: the row appears on the dashboard within seconds.
        deadline = time.time() + 10
        row = None
        while time.time() < deadline:
            rows = c.get("/api/dashboard/payment-links?limit=200").json()
            row = next((x for x in rows if x["plink_id"] == plink["id"]), None)
            if row:
                break
            time.sleep(0.5)
        if row is None:
            failures.append("new plink never appeared on /api/dashboard/payment-links")
            print("FAIL: row not found")
        else:
            print(f"\nrow appeared: status={row['status']} journey_state={row['journey_state']} "
                  f"amount={row['amount_inr']} ref={row['reference_id']}")
            if row["status"] != "created":
                failures.append(f"fresh link status should be 'created', got {row['status']!r}")

        # force-paid via the lifecycle drill
        forced = c.post("/api/live/lifecycle/force-paid",
                        json={"reference_id": plink["reference_id"]})
        if forced.status_code != 200:
            failures.append(f"force-paid HTTP {forced.status_code}: {forced.text[:200]}")
        else:
            show("force-paid", forced.json())
            body = forced.json()
            if body.get("cadence_state") != "RECOVERED":
                failures.append(f"cadence_state {body.get('cadence_state')!r} != 'RECOVERED'")

        rows = c.get("/api/dashboard/payment-links?limit=200").json()
        row = next((x for x in rows if x["plink_id"] == plink["id"]), None)
        if row is None or row["status"] != "paid":
            failures.append(f"row status after force-paid: {row and row['status']!r} != 'paid'")
        else:
            print(f"\nrow after force-paid: status={row['status']} "
                  f"journey_state={row['journey_state']} lifecycle={len(row['lifecycle'])} entries")

        show("stats", c.get("/api/dashboard/stats").json())
        show("cloud mirror", c.get("/api/cloud/plinks?limit=5").json(), cap=900)

        chain = c.get("/api/audit/verify").json()
        print(f"\naudit chain: chain_ok={chain['chain_ok']} events={chain['event_count']}")
        if not chain["chain_ok"]:
            failures.append("audit chain broken")

    print("\n" + "=" * 70)
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("live dashboard smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
