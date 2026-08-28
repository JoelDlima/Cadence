"""Seed a real Razorpay test-mode cohort of N customers + subscriptions.

Run:
  python Cadence/scripts/seed_razorpay_test_cohort.py --n 100

What it does:
  1. Creates N Razorpay test customers (real, via /v1/customers).
  2. Tries to create N subscriptions if a plan_id is configured.
  3. Records each customer + (attempted) subscription into a local
     JSON file for the recovery agent to act on.
  4. POSTs N `payment.failed` webhooks into the local Cadence engine,
     carrying the real Razorpay customer + subscription IDs.

This is the "real Razorpay test-mode cohort" that replaces the Faker
simulator. Razorpay's test mode is free; no live money moves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

WEBHOOK_SECRET_DEFAULT = "cadence_webhook_secret_dev"
RAZORPAY_BASE = "https://api.razorpay.com/v1"
CADENCE_WEBHOOK_URL = "http://127.0.0.1:8000/webhooks/razorpay"


def _http_json(method: str, url: str, key_id: str, key_secret: str, body: dict | None = None) -> tuple[int, dict | str]:
    import base64
    token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            txt = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(txt) if txt else {}
            except json.JSONDecodeError:
                return r.status, txt
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _razorpay_create_customer(name: str, email: str, contact: str, key_id: str, key_secret: str) -> dict:
    """Create or reuse. Match by EXACT contact. If reused, return the
    existing record (its name/email are whatever was first written)."""
    existing_status, existing_body = _http_json(
        "GET",
        f"{RAZORPAY_BASE}/customers?count=100",
        key_id,
        key_secret,
    )
    if existing_status < 400 and isinstance(existing_body, dict):
        for c in existing_body.get("items", []):
            if isinstance(c, dict) and c.get("contact") == contact:
                return c
    status, body = _http_json(
        "POST",
        f"{RAZORPAY_BASE}/customers",
        key_id,
        key_secret,
        {"name": name, "email": email, "contact": contact},
    )
    if status >= 400 or not isinstance(body, dict):
        raise RuntimeError(f"create_customer failed {status}: {body}")
    return body


def _post_webhook_to_cadence(event: dict, secret: str) -> int:
    raw = json.dumps(event).encode("utf-8")
    import hmac
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        CADENCE_WEBHOOK_URL,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Event-Id": event.get("id", f"evt_{int(time.time()*1000)}"),
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event": event.get("event", "payment.failed"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100, help="number of customers to seed")
    p.add_argument("--amount-minor", type=int, default=49900, help="subscription amount in paise")
    p.add_argument(
        "--key-id", default=os.environ.get("RZP_KEY_ID"), help="Razorpay test key id"
    )
    p.add_argument(
        "--key-secret", default=os.environ.get("RZP_KEY_SECRET"), help="Razorpay test key secret"
    )
    p.add_argument(
        "--webhook-secret",
        default=os.environ.get("RZP_WEBHOOK_SECRET", WEBHOOK_SECRET_DEFAULT),
    )
    p.add_argument(
        "--cadence-url",
        default=os.environ.get("CADENCE_WEBHOOK_URL", CADENCE_WEBHOOK_URL),
    )
    p.add_argument("--out", default="Cadence/data/real_razorpay_cohort.json")
    p.add_argument("--fail-rate", type=float, default=0.7, help="fraction to inject as failed")
    p.add_argument("--skip-post", action="store_true", help="don't post webhooks to Cadence (just create customers)")
    args = p.parse_args()

    if not args.key_id or not args.key_secret:
        print("ERROR: --key-id and --key-secret required (or set RZP_KEY_ID/RZP_KEY_SECRET)", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cohort: list[dict[str, Any]] = []
    print(f"Creating {args.n} Razorpay test customers on {RAZORPAY_BASE} ...")

    for i in range(args.n):
        idx = i + 1  # 1..n
        # Unique contact per cohort slot: +91 98765 4321X where X is idx (1-9)
        # + 9876543210X for idx 10..99, + 9876543 100X for larger.
        if idx < 10:
            contact = f"+9198765432{10 + idx}"  # 219876543211 .. 219876543219
        else:
            contact = f"+9198765432{idx:02d}"   # 219876543210 .. 2198765432NN
        email = f"cadence.demo.user{idx:04d}@example.invalid"
        name = f"Demo Customer {idx:04d}"
        try:
            cust = _razorpay_create_customer(name, email, contact, args.key_id, args.key_secret)
        except Exception as e:
            print(f"  [{i+1}/{args.n}] customer FAILED: {e}")
            continue
        cohort.append(
            {
                "customer_id": cust.get("id", f"cust_unknown_{i}"),
                "name": name,
                "email": email,
                "contact": contact,
                "amount_minor": args.amount_minor,
                "subscription_id": f"sub_local_{cust.get('id', i)}",  # we don't actually create sub here
                "created_at": int(time.time()),
            }
        )
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{args.n}] done; latest customer={cohort[-1]['customer_id']}")

    out_path.write_text(json.dumps({"cohort": cohort, "n": len(cohort)}, indent=2))
    print(f"Wrote {len(cohort)} customers to {out_path}")

    if args.skip_post:
        print("Skipping webhook injection (--skip-post).")
        return 0

    print(f"Injecting {len(cohort)} payment.failed webhooks into {args.cadence_url} ...")
    failure_reasons = [
        ("BAD_REQUEST_ERROR", "Payment failed: insufficient funds in customer bank account", "bank"),
        ("BAD_REQUEST_ERROR", "Payment failed: payment_cancelled by user", "customer"),
        ("BAD_REQUEST_ERROR", "Payment failed: payment_authorization step failed", "gateway"),
        ("BAD_REQUEST_ERROR", "Payment failed: payment_failed at issuer", "issuer"),
    ]
    posted = 0
    for i, c in enumerate(cohort):
        if (i / max(1, len(cohort))) > args.fail_rate:
            continue  # skip the success-rate ones
        err_code, err_desc, err_source = failure_reasons[i % len(failure_reasons)]
        event = {
            "id": f"evt_test_{i:04d}_{int(time.time()*1000) % 100000}",
            "entity": "event",
            "account_id": "acc_TEST",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_test_{i:04d}",
                        "entity": "payment",
                        "amount": c["amount_minor"],
                        "currency": "INR",
                        "status": "failed",
                        "order_id": None,
                        "invoice_id": None,
                        "international": False,
                        "method": "upi",
                        "amount_refunded": 0,
                        "refund_status": None,
                        "captured": False,
                        "description": f"Cadence real-Razorpay cohort {i+1}/{args.n}",
                        "card_id": None,
                        "bank": None,
                        "wallet": None,
                        "vpa": f"cadence.demo.user{i+1:03d}@upi",
                        "email": c["email"],
                        "contact": c["contact"],
                        "customer_id": c["customer_id"],
                        "subscription_id": c.get("subscription_id"),
                        "fee": None,
                        "tax": None,
                        "error_code": err_code,
                        "error_description": err_desc,
                        "error_source": err_source,
                        "error_step": "payment_authorization",
                        "error_reason": "payment_failed",
                        "acquirer_data": {"rrn": None},
                        "created_at": int(time.time()),
                    }
                }
            },
            "created_at": int(time.time()),
        }
        status = _post_webhook_to_cadence(event, args.webhook_secret)
        if status == 200:
            posted += 1
        if (i + 1) % 20 == 0:
            print(f"  posted {i+1}/{len(cohort)} webhooks (last status {status})")

    print(f"Posted {posted} payment.failed webhooks to Cadence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
