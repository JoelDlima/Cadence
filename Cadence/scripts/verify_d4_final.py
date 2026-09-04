"""D4: final verification pass — print the headline numbers and all
endpoints. Used as the closing block in strict platform verification.
"""
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:8000"


def get(path, timeout=30):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, str(e)


def post(path, body=None, timeout=30):
    try:
        r = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, str(e)


def main() -> int:
    print("=" * 60)
    print("D4 final verification - Cadence / Revenue Recovery")
    print("=" * 60)

    # --- 1) live status ---
    s, status = get("/api/status")
    print(f"\n[1] GET /api/status -> {s}")
    print(f"    mode={status.get('mode')} razorpay={status.get('razorpay_keys_present')}")
    print(f"    llm={status.get('llm_keys_present')} supabase={status.get('supabase_keys_present')}")
    print(f"    resend={status.get('resend_key_present')}")
    print(f"    db_event_count={status.get('db_event_count')}")

    # --- 2) merchant summary ---
    s, m = get("/api/merchant/summary")
    print(f"\n[2] GET /api/merchant/summary -> {s}")
    print(f"    total={m.get('total_journeys')} recovered={m.get('total_recovered')} "
          f"INR={m.get('recovered_amount_inr')} rate={m.get('recovery_rate_pct')}%")

    # --- 3) multi-seed agent compare ---
    print("\n[3] GET /api/eval/agent-compare?seeds=42,7,99,123,2024&n=50")
    s, c = get("/api/eval/agent-compare?seeds=42,7,99,123,2024&n=50", timeout=90)
    print(f"    http {s}")
    print(f"    mean_naive={c.get('mean_naive_recovery_pct')}%  "
          f"mean_cadence={c.get('mean_cadence_recovery_pct')}%  "
          f"mean_uplift={c.get('mean_uplift_pct')}%  "
          f"mean_delta=INR {c.get('mean_recovered_delta_inr')}")
    for r in c.get("per_seed", []):
        print(f"      seed {r['seed']:>5}: naive {r['naive_recovery_pct']:.1f}%  "
              f"cadence {r['cadence_recovery_pct']:.1f}%  "
              f"INR {r['cadence_recovered_inr']:.0f}")

    # --- 4) live recovery end-to-end ---
    print("\n[4] Live Recovery end-to-end (real Razorpay test mode)")
    s, cust = post("/api/live/customer",
                   {"name": "Demo", "email": "demo@x.local", "contact": "9999900000"})
    print(f"    [4a] customer   http {s}  cust {cust.get('id')}  sim={cust.get('simulated')}")
    s, fail = post("/api/live/failure", {"customer_id": cust["id"]})
    print(f"    [4b] failure    http {s}")
    print(f"                 journey {fail.get('journey_id')}")
    print(f"                 plink   {fail['payment_link']['id']}  "
          f"short_url {fail['payment_link']['short_url']}")
    print(f"                 plink.simulated={fail['payment_link']['simulated']}")
    s, pp = post("/api/live/payment-paid",
                 {"reference_id": fail["payment_link"]["reference_id"]})
    print(f"    [4c] paid       http {s}  status={pp.get('status')}  http={pp.get('http')}")
    print(f"                 event_id {pp.get('event_id')}")

    import time
    for n in range(15):
        s, j = get(f"/api/journey/{fail['journey_id']}")
        if j.get("state") == "RECOVERED":
            print(f"    [4d] poll {n+1}: state=RECOVERED (in ~{(n+1)*2}s)")
            break
        time.sleep(2)
    else:
        print(f"    [4d] poll: stuck at {j.get('state')}")

    # --- 5) W1: agent.thinking event persisted ---
    s, reasoning = get(f"/api/journey/{fail['journey_id']}/reasoning")
    print(f"\n[5] GET /api/journey/{fail['journey_id']}/reasoning -> {s}")
    if isinstance(reasoning, dict):
        steps = reasoning.get("steps", [])
        has_thinking = any("thinking" in (step.get("type", "") if isinstance(step, dict) else "").lower()
                           for step in steps)
        print(f"    steps: {len(steps)}  has_llm_thought={reasoning.get('has_llm_thought')}")
        print(f"    agent.thinking present: {has_thinking}")
    else:
        print(f"    (no reasoning data; response: {str(reasoning)[:120]})")

    # --- 6) anomaly endpoint ---
    s, anomalies = get("/api/anomaly")
    print(f"\n[6] GET /api/anomaly -> {s}  count={len(anomalies)}")

    # --- 7) kill switch ---
    s, k = get("/api/flags/kill-switch")
    print(f"\n[7] GET /api/flags/kill-switch -> {s}  {k}")

    # --- 8) audit chain ---
    s, a = get("/api/audit/verify")
    print(f"\n[8] GET /api/audit/verify -> {s}  chain_ok={a.get('chain_ok')}  "
          f"events={a.get('event_count')}")

    # --- 9) bandit ranked ---
    s, b = get("/api/bandit/ranked?limit=3")
    print(f"\n[9] GET /api/bandit/ranked -> {s}  rankings={b.get('count')}")

    # --- 10) cloud status ---
    s, c = get("/api/cloud/status")
    print(f"\n[10] GET /api/cloud/status -> {s}  "
          f"enabled={c.get('enabled')}  sync_state={c.get('sync_state')}")

    print("\n" + "=" * 60)
    print("D4 verification complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
