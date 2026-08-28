"""Razorpay client boundary: live HTTP client + deterministic keyless simulator.

The simulator keeps demos and tests offline-deterministic (no keys required);
`LiveRazorpayClient` speaks real test-mode API when keys are configured. Mandate
retries on the live side are NOT an HTTP call we can make: debit retries happen
on NPCI rails from Razorpay's dashboard/route logic. Our live recovery
instrument is therefore the Payment Link API; calling `simulate_mandate_retry`
on the live client fails fast with a RuntimeError so a mis-wired dispatcher
cannot silently pretend to retry.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Protocol

import httpx

from revive.config import RazorpayConfig

_BASE_URL = "https://api.razorpay.com/v1"
_TIMEOUT_SECONDS = 15.0


def _sha1_hex(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


class RazorpayLike(Protocol):
    """Minimal surface the dispatcher depends on (swap sim/live freely)."""

    mode: str

    def create_payment_link(
        self,
        *,
        amount_minor: int,
        currency: str,
        customer_id: str,
        description: str,
        reference_id: str,
    ) -> dict: ...

    def simulate_mandate_retry(
        self, *, subscription_id: str, amount_minor: int, seed: str
    ) -> dict: ...


@dataclass(frozen=True)
class SimulatedRazorpayClient:
    """Deterministic stand-in derived purely from input strings (keyless)."""

    mode: str = "simulated"

    def create_payment_link(
        self,
        *,
        amount_minor: int,
        currency: str,
        customer_id: str,
        description: str,
        reference_id: str,
    ) -> dict:
        return {
            "id": f"plink_sim_{_sha1_hex(reference_id)[:12]}",
            "short_url": f"https://rzp.io/i/sim_{_sha1_hex(reference_id)[:8]}",
            "status": "created",
            "simulated": True,
        }

    def simulate_mandate_retry(
        self, *, subscription_id: str, amount_minor: int, seed: str
    ) -> dict:
        return {
            "id": f"pay_sim_{_sha1_hex(seed)[:12]}",
            "status": "simulated",
            "simulated": True,
        }


@dataclass(frozen=True)
class LiveRazorpayClient:
    """Real Razorpay REST client (test mode when test keys are configured).

    `transport` accepts a pre-built ``httpx.Client`` (tests inject
    ``httpx.Client(transport=httpx.MockTransport(...))``); when omitted a fresh
    15s-timeout client is created per call.
    """

    cfg: RazorpayConfig
    transport: httpx.Client | None = None
    mode: str = "live"

    def create_payment_link(
        self,
        *,
        amount_minor: int,
        currency: str,
        customer_id: str,
        description: str,
        reference_id: str,
    ) -> dict:
        body = {
            "amount": amount_minor,
            "currency": currency,
            "reference_id": reference_id,
            "description": description,
            "notes": {"journey_ref": reference_id},
        }
        request = httpx.Request("POST", f"{_BASE_URL}/payment_links", json=body)
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def payment_captured_for(self, *, reference_id: str) -> bool:
        """True when a payment with this reference_id has status 'captured'.

        The outcome-check resolver uses this to turn a real Razorpay payment
        (typically a paid Payment Link) into a RECOVERED journey. Deliberately
        absent from the simulator: offline, outcomes come from the injectable
        OutcomeFn instead, never from a fabricated probe.
        """
        request = httpx.Request(
            "GET",
            f"{_BASE_URL}/payments",
            params={"reference_id": reference_id, "count": 10},
        )
        response = self._send(request)
        response.raise_for_status()
        items = response.json().get("items", [])
        return any(item.get("status") == "captured" for item in items if isinstance(item, dict))

    def simulate_mandate_retry(
        self, *, subscription_id: str, amount_minor: int, seed: str
    ) -> dict:
        """Never callable against the live API.

        Mandate debit retries execute on NPCI rails (Razorpay-side), not via any
        REST endpoint we control. The live recovery instrument is Payment Links;
        reaching this method with a live client means misconfiguration, so we
        raise instead of fabricating a result.
        """
        raise RuntimeError(
            "live mandate retries occur on NPCI rails; recovery instrument is Payment Links"
        )

    def _send(self, request: httpx.Request) -> httpx.Response:
        token = base64.b64encode(
            f"{self.cfg.key_id}:{self.cfg.key_secret}".encode()
        ).decode("ascii")
        request.headers["Authorization"] = f"Basic {token}"
        if self.transport is not None:
            return self.transport.send(request)
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            return client.send(request)


def build_client(cfg: RazorpayConfig, transport: httpx.Client | None = None) -> RazorpayLike:
    """Live client iff both key halves are present, else deterministic simulator."""
    if cfg.is_live:
        return LiveRazorpayClient(cfg=cfg, transport=transport)
    return SimulatedRazorpayClient()
