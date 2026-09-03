"""Unit tests for Razorpay webhook HMAC signature verification (plan item B1)."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from cadence.ingest.signature import verify_signature

SECRET = "whsec_test_123"
BODY = b'{"event":"payment.failed","payload":{}}'


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


pytestmark = [pytest.mark.unit]


def test_valid_signature_passes() -> None:
    signature = _sign(BODY, SECRET)

    result = verify_signature(raw_body=BODY, signature_header=signature, secret=SECRET)

    assert result is True


def test_tampered_body_fails() -> None:
    tampered = BODY.replace(b"failed", b"faiLed")
    original_signature = _sign(BODY, SECRET)

    result = verify_signature(raw_body=tampered, signature_header=original_signature, secret=SECRET)

    assert result is False


def test_missing_header_fails() -> None:
    assert verify_signature(raw_body=BODY, signature_header=None, secret=SECRET) is False


def test_empty_header_fails() -> None:
    assert verify_signature(raw_body=BODY, signature_header="", secret=SECRET) is False


def test_different_secret_fails() -> None:
    attacker_signature = _sign(BODY, "whsec_attacker")

    result = verify_signature(raw_body=BODY, signature_header=attacker_signature, secret=SECRET)

    assert result is False
