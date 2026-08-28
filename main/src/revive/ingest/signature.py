"""Razorpay webhook signature verification.

Razorpay sends ``X-Razorpay-Signature: hex(HMAC_SHA256(webhook_secret, raw_body))``.
Verification must run over the exact raw request bytes and use a constant-time
comparison so timing cannot leak the expected digest.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(*, raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Return True iff ``signature_header`` matches HMAC-SHA256(secret, raw_body).

    A missing/empty header (or empty secret) fails closed. The digest comparison
    is constant-time (``hmac.compare_digest``).
    """
    if not signature_header or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
