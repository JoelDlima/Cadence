"""Check the configured Razorpay keys can actually talk to the API.

Prints the key id (public) and the HTTP result. Never prints the secret.

    .venv\\Scripts\\python.exe scripts\\check_razorpay_keys.py
"""
from __future__ import annotations

import base64

import httpx

from cadence.config import load_config

cfg = load_config().razorpay
print(f"key_id      = {cfg.key_id or '(not set)'}")
print(f"key_secret  = {'set (' + str(len(cfg.key_secret)) + ' chars)' if cfg.key_secret else '(not set)'}")
print(f"is_live     = {cfg.is_live}")
if not cfg.is_live:
    raise SystemExit(0)

token = base64.b64encode(f"{cfg.key_id}:{cfg.key_secret}".encode()).decode()
# A read-only call: list one payment link. Proves auth without creating anything
# (Razorpay rate-limits link creation, so never POST just to test keys).
r = httpx.get(
    "https://api.razorpay.com/v1/payment_links",
    params={"count": 1},
    headers={"Authorization": f"Basic {token}"},
    timeout=20.0,
)
print(f"GET /v1/payment_links -> HTTP {r.status_code}")
if r.status_code == 200:
    items = r.json().get("items", [])
    print(f"AUTH OK. links visible on this account: {len(items)}")
    for item in items:
        print(f"  {item.get('id')}  {item.get('status')}  ref={item.get('reference_id')}")
else:
    print(f"AUTH FAILED: {r.text[:300]}")
    raise SystemExit(2)
