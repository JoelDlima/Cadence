"""Comprehensive smoke test for the live Cadence stack.

Per the user's request: research the docs first, then test.

Docs consulted (Aug 2026):
  - Razorpay llms.txt (30 April 2026, v1.0)
  - https://razorpay.com/docs/build/llm-docs/api/payments/payment-links/create-standard.md
    -> error "Recurring digits in customer contact are disallowed" is the
       anti-fraud rule: Razorpay rejects 6+ identical digits in a row.
       Valid contact: 8-14 chars, including country code.
  - https://razorpay.com/docs/build/llm-docs/webhooks/payments.md
    -> payment.failed payload includes error_code, error_description,
       error_source (bank/issuer/customer/gateway), error_step,
       error_reason, and method (card/upi/netbanking/wallet/emi/bank_transfer).
  - https://razorpay.com/docs/build/llm-docs/webhooks/validate-test.md
    -> signature is HMAC-SHA256(secret, raw_body), sent in
       X-Razorpay-Signature. Idempotency via X-Razorpay-Event-Id.
       payment.failed -> payment.captured is NORMAL for UPI retries.
  - https://console.groq.com/docs/api-reference
    -> openai/gpt-oss-120b is a real model on free tier.
       The 1010 error is from Resend (not Groq).
  - https://resend.com/docs/knowledge-base/403-error-1010
    -> 1010 = missing User-Agent. SDK/curl set it automatically;
       direct HTTPS calls must set it manually.
    -> sending_access keys cannot list domains; they can only send.
    -> onboarding@resend.dev is the universal test sender.
  - https://supabase.com/docs/guides/api/api-keys
    -> eyJ... service_role JWT bypasses RLS for data API (PostgREST).
       sb_secret_* is blocked from PostgREST (browser-like UA check).
       sb_secret_* is NOT authorized for Management API either.
       For DDL via Management API, need sbp_... Personal Access Token.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _request(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: int = 15) -> tuple[int, str]:
    h = dict(headers or {})
    h.setdefault("User-Agent", UA)
    h.setdefault("Accept", "application/json")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "FAIL"
    print(f"  [{mark}] {name}: {detail}")
    return ok


def main() -> int:
    overall = True
    print("Cadence LIVE smoke test (research-driven)")
    print("=" * 60)

    # 1. Razorpay
    print("\n[1] Razorpay (payment_link create + payment.failed webhook shape)")
    rzp_id = os.environ.get("RZP_KEY_ID")
    rzp_secret = os.environ.get("RZP_KEY_SECRET")
    if not rzp_id or not rzp_secret:
        print("  SKIP: RZP_KEY_ID / RZP_KEY_SECRET not set in env. "
              "Copy Cadence/.env into your shell and re-run.")
        return 0
    auth = base64.b64encode(f"{rzp_id}:{rzp_secret}".encode()).decode()

    # 1a. list payments
    status, body = _request(
        "https://api.razorpay.com/v1/payments?count=1",
        headers={"Authorization": f"Basic {auth}"},
    )
    overall &= _check("list payments", status == 200, f"status={status}")
    if status == 200:
        d = json.loads(body)
        overall &= _check("auth OK", d.get("count") is not None, f"count={d.get('count')}")

    # 1b. create a payment_link with a valid contact
    # (per docs: 8-14 chars, no 6+ identical digits in a row)
    pl_body = {
        "amount": 49900,           # Rs 499 in paise
        "currency": "INR",
        "description": "Cadence LIVE smoke test",
        "customer": {
            "name": "Cadence Demo Customer",
            "email": os.environ.get("BUILDATHON_TEST_EMAIL", "demo@cadence.local"),
            "contact": "+919876543210",  # the docs' canonical example
        },
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "callback_url": "https://pay.cadence.in/pay/smoke-001",
        "callback_method": "get",
    }
    status, body = _request(
        "https://api.razorpay.com/v1/payment_links",
        method="POST",
        body=pl_body,
        headers={"Authorization": f"Basic {auth}"},
    )
    overall &= _check("create payment_link", status == 200, f"status={status}")
    if status == 200:
        d = json.loads(body)
        overall &= _check("link id", d.get("id", "").startswith("plink_"), f"id={d.get('id')}")
        overall &= _check("short_url", bool(d.get("short_url")), f"short_url={d.get('short_url')}")

    # 1c. send a payment.failed webhook TO the engine (real shape) and verify HMAC
    webhook_secret = "cadence_webhook_secret_dev"
    failed_payload = {
        "entity": "event",
        "account_id": "acc_TEST",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_SMOKE_LIVE_001",
                    "entity": "payment",
                    "amount": 49900,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": None,
                    "invoice_id": None,
                    "international": False,
                    "method": "upi",
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": False,
                    "description": "Cadence smoke test",
                    "card_id": None,
                    "bank": None,
                    "wallet": None,
                    "vpa": "cadence@upi",
                    "email": os.environ.get("BUILDATHON_TEST_EMAIL", "demo@cadence.local"),
                    "contact": "+919876543210",
                    "customer_id": "cust_TVEAT6U0W8Pgas",
                    "fee": None,
                    "tax": None,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed (smoke test)",
                    "error_source": "bank",
                    "error_step": "payment_authorization",
                    "error_reason": "payment_failed",
                    "acquirer_data": {"rrn": None},
                    "created_at": int(time.time()),
                }
            }
        },
        "created_at": int(time.time()),
    }
    raw_body = json.dumps(failed_payload).encode()
    sig = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    status, body = _request(
        "http://127.0.0.1:8000/webhooks/razorpay",
        method="POST",
        body=failed_payload,
        headers={
            "X-Razorpay-Event-Id": failed_payload["payload"]["payment"]["entity"]["id"],
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event": "payment.failed",
        },
    )
    overall &= _check("HMAC-signed payment.failed webhook", status == 200, f"status={status}, body={body[:80]}")

    # 2. Groq
    print("\n[2] Groq (chat completions with User-Agent)")
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        print("  SKIP: GROQ_API_KEY not set in env.")
        return 0
    model = os.environ.get("LLM_MODEL_GROQ", "openai/gpt-oss-120b")
    status, body = _request(
        "https://api.groq.com/openai/v1/chat/completions",
        method="POST",
        body={"model": model, "messages": [{"role": "user", "content": "Reply with exactly: pong"}], "max_completion_tokens": 10},
        headers={"Authorization": f"Bearer {groq_key}"},
    )
    overall &= _check("chat completion", status == 200, f"status={status}")
    if status == 200:
        d = json.loads(body)
        overall &= _check("model responds", bool(d.get("choices")), f"reply={d['choices'][0]['message']['content']!r}")

    # 3. Resend
    print("\n[3] Resend (send email with User-Agent + onboarding sender)")
    resend_key = os.environ.get("RESEND_API_KEY")
    if not resend_key:
        print("  SKIP: RESEND_API_KEY not set in env.")
        return 0
    status, body = _request(
        "https://api.resend.com/emails",
        method="POST",
        body={
            "from": "Cadence Smoke <onboarding@resend.dev>",
            "to": ["joelinternshipaitd@gmail.com"],
            "subject": f"Cadence LIVE smoke @ {time.strftime('%H:%M:%S')}",
            "text": "All systems green. - Cadence",
        },
        headers={"Authorization": f"Bearer {resend_key}"},
    )
    overall &= _check("send email", status in (200, 201), f"status={status}")
    if status in (200, 201):
        d = json.loads(body)
        overall &= _check("email accepted", bool(d.get("id")), f"id={d.get('id')}")

    # 4. Supabase
    print("\n[4] Supabase (service_role JWT, table listing only)")
    sb_url = os.environ.get("SUPABASE_URL", "https://vzrasadomyrycafbzdwg.supabase.co")
    sr = os.environ.get(
        "SUPABASE_SERVICE_KEY",
        "placeholder_supabase_service_key",
    )
    status, body = _request(f"{sb_url}/rest/v1/?select=*", headers={"apikey": sr, "Authorization": f"Bearer {sr}"})
    overall &= _check("service_role JWT", status == 200, f"status={status}")
    if status == 200:
        paths = list(json.loads(body).get("definitions", {}).keys())
        for t in ("webhook_inbox", "journeys_mirror", "metrics_daily"):
            present = any(t in p for p in paths)
            note = "exists" if present else "NOT YET (paste schema.sql in dashboard)"
            overall &= _check(f"table {t}", present, note)

    # 5. Local engine
    print("\n[5] Local engine (state + mirror)")
    status, body = _request("http://127.0.0.1:8000/api/status")
    overall &= _check("backend up", status == 200, f"status={status}")
    if status == 200:
        d = json.loads(body)
        overall &= _check("mode=LIVE", d.get("mode") == "LIVE", f"mode={d.get('mode')}")
        overall &= _check("Razorpay key in engine", d.get("razorpay_keys_present"))
        overall &= _check("LLM key in engine", d.get("llm_keys_present"))
        overall &= _check("Resend key in engine", d.get("resend_key_present"))
        overall &= _check("Supabase key in engine", d.get("supabase_keys_present"))

    # 6. SPA
    status, body = _request("http://127.0.0.1:3000", timeout=5)
    overall &= _check("frontend up", status == 200, f"status={status}")

    # 7. Audit chain still OK after the webhook injection
    status, body = _request("http://127.0.0.1:8000/api/audit/verify")
    if status == 200:
        d = json.loads(body)
        overall &= _check("audit chain OK", d.get("chain_ok") is True, f"events={d.get('event_count')}, first_bad={d.get('first_bad_seq')}")

    print()
    print("=" * 60)
    print("ALL GREEN" if overall else "ONE OR MORE CHECKS FAILED")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
