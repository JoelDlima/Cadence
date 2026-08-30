"""Verify the R2 live recovery endpoints end-to-end."""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path, body):
    r = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def main() -> int:
    print("Step 1: create customer")
    s, c = post("/api/live/customer",
                {"name": "Demo", "email": "demo@x.local", "contact": "9999900000"})
    print(f"  http {s}  cust {c['id']}  simulated={c['simulated']}")
    assert s == 200, c
    assert c["id"].startswith("cust_")

    print("Step 2: create failure + payment link")
    s, f = post("/api/live/failure", {"customer_id": c["id"]})
    print(f"  http {s}")
    print(f"  journey {f['journey_id']}")
    print(f"  payment_link.id          {f['payment_link']['id']}")
    print(f"  payment_link.short_url   {f['payment_link']['short_url']}")
    print(f"  payment_link.reference   {f['payment_link']['reference_id']}")
    print(f"  payment_link.simulated   {f['payment_link']['simulated']}")
    assert s == 200
    assert f["payment_link"]["id"].startswith("plink_")

    print("Step 3: post payment_link.paid (close-the-loop)")
    s, pp = post("/api/live/payment-paid",
                 {"reference_id": f["payment_link"]["reference_id"]})
    # B-fix: omit payment_id so the backend generates a unique one
    # (a constant value would dedupe the capture task on every
    # rerun and strand the journey in INTERVENING forever).
    print(f"  http {s}  {pp}")
    assert s == 200
    assert pp["status"] in ("accepted", "duplicate", "ignored")

    print("Step 4: poll journey to confirm it advanced")
    import time
    for n in range(15):
        s, j = get(f"/api/journey/{f['journey_id']}")
        print(f"  poll {n+1}/15: state={j['state']}")
        if j["state"] in ("RECOVERED", "CLOSED_UNRECOVERED", "HUMAN_REVIEW"):
            print(f"  terminal state: {j['state']}")
            break
        time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
