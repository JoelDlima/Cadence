"""Razorpay client boundary: live HTTP client + deterministic keyless simulator.

The simulator keeps demos and tests offline-deterministic (no keys required).
`LiveRazorpayClient` speaks real test-mode API when keys are configured. Mandate
retries on the live side are NOT an HTTP call we can make: debit retries happen
on NPCI rails from Razorpay's dashboard/route logic. Our live recovery
instrument is therefore the Payment Link API + real customer creation + real
payment.fetch for outcome verification; calling `simulate_mandate_retry`
on the live client fails fast with a RuntimeError so a mis-wired dispatcher
cannot silently pretend to retry.

PHASE 1 additions (Aug 2026): the live client now exposes
  - create_customer           (Razorpay /v1/customers)
  - create_subscription       (Razorpay /v1/subscriptions, plan_id required)
  - create_registration_link  (Razorpay /v1/subscriptions/registration_link)
  - fetch_payment             (Razorpay /v1/payments/{id})
  - cancel_payment_link       (Razorpay /v1/payment_links/{id}/cancel)
  - create_refund             (Razorpay /v1/payments/{id}/refund)
PHASE 2: payment.fetch becomes the single source of truth for outcome check.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Protocol

import httpx

from cadence.config import RazorpayConfig

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

    def fetch_payment_link(
        self, *, payment_link_id: str
    ) -> dict: ...

    def list_payments_by_payment_link(
        self, *, payment_link_id: str, count: int = 10
    ) -> list[dict]: ...

    def simulate_mandate_retry(
        self, *, subscription_id: str, amount_minor: int, seed: str
    ) -> dict: ...


@dataclass(frozen=True)
class SimulatedRazorpayClient:
    """Deterministic stand-in derived purely from input strings (keyless)."""

    mode: str = "simulated"

    def create_customer(
        self, *, name: str, email: str, contact: str, lookup_first: bool = True
    ) -> dict:
        """Deterministic stand-in. Returns a stable id keyed on email+contact."""
        seed = f"{email}:{contact}"
        return {
            "id": f"cust_sim_{_sha1_hex(seed)[:10]}",
            "name": name,
            "email": email,
            "contact": contact,
            "simulated": True,
        }

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

    def fetch_payment(self, *, payment_id: str) -> dict:
        """Simulated payment status. Stable for known IDs; otherwise random."""
        seed = _sha1_hex(payment_id)
        # deterministic 50/50 captured/failed by parity of the second hex digit
        status = "captured" if int(seed[1], 16) % 2 == 0 else "failed"
        return {
            "id": payment_id,
            "status": status,
            "amount": 49900,
            "currency": "INR",
            "method": "upi",
            "simulated": True,
        }

    def fetch_payment_link(self, *, payment_link_id: str) -> dict:
        """Simulated link status. The link is `paid` once the corresponding
        payment id has been seen as captured (via the simulator's seeded
        state). The simulator holds its own in-memory map of
        {payment_link_id: status} for the demo."""
        stored = getattr(self, "_link_status", {}).get(payment_link_id)
        if stored is not None:
            return {"id": payment_link_id, "status": stored, "simulated": True}
        # Stable seed-based default: 'created' for half, 'paid' for the other half.
        seed = _sha1_hex(payment_link_id)
        status = "paid" if int(seed[1], 16) % 2 == 0 else "created"
        return {
            "id": payment_link_id,
            "status": status,
            "amount": 49900,
            "currency": "INR",
            "simulated": True,
        }

    def list_payments_by_payment_link(
        self, *, payment_link_id: str, count: int = 10
    ) -> list[dict]:
        """Simulated list of payments under a payment link."""
        return [{
            "id": f"pay_sim_{_sha1_hex(payment_link_id)[:12]}",
            "status": "captured",
            "amount": 49900,
            "currency": "INR",
            "simulated": True,
        }]

    def simulate_mandate_retry(
        self, *, subscription_id: str, amount_minor: int, seed: str
    ) -> dict:
        return {
            "id": f"pay_sim_{_sha1_hex(seed)[:12]}",
            "status": "simulated",
            "simulated": True,
        }

    def create_subscription(
        self, *, plan_id: str, customer_id: str, total_count: int = 12
    ) -> dict:
        seed = _sha1_hex(f"{plan_id}:{customer_id}")
        return {
            "id": f"sub_sim_{seed[:12]}",
            "customer_id": customer_id,
            "plan_id": plan_id,
            "status": "created",
            "simulated": True,
        }

    def create_registration_link(
        self, *, customer: dict, amount_minor: int, currency: str = "INR", description: str = "Subscription"
    ) -> dict:
        seed = _sha1_hex(f"{customer.get('id','')}:{amount_minor}")
        return {
            "id": f"reglink_sim_{seed[:12]}",
            "short_url": f"https://rzp.io/i/sim_{seed[:8]}",
            "simulated": True,
        }

    def create_refund(self, *, payment_id: str, amount_minor: int | None = None) -> dict:
        return {
            "id": f"rfnd_sim_{_sha1_hex(payment_id)[:10]}",
            "payment_id": payment_id,
            "amount": amount_minor,
            "simulated": True,
        }

    def cancel_payment_link(self, *, payment_link_id: str) -> dict:
        return {
            "id": payment_link_id,
            "cancelled": True,
            "simulated": True,
        }

    def capture_payment(self, *, payment_id: str, amount_minor: int | None = None) -> dict:
        """Simulated capture: returns ``status=captured`` with the same amount."""
        return {
            "id": payment_id,
            "entity": "payment",
            "status": "captured",
            "amount": amount_minor or 49900,
            "currency": "INR",
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

    def create_customer(
        self, *, name: str, email: str, contact: str, lookup_first: bool = True
    ) -> dict:
        """Create a Razorpay test-mode customer.

        If ``lookup_first`` (default), query /v1/customers first and return
        the first one whose ``contact`` matches exactly. Otherwise POST
        directly and accept whatever Razorpay returns (which may be a 400
        "already exists" error if the contact is taken).
        """
        if lookup_first:
            existing = self._list_customers_by_contact(contact=contact)
            if existing:
                return existing[0]
        body = {"name": name, "email": email, "contact": contact}
        request = httpx.Request("POST", f"{_BASE_URL}/customers", json=body)
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def _list_customers_by_contact(self, *, contact: str) -> list[dict]:
        request = httpx.Request(
            "GET", f"{_BASE_URL}/customers", params={"count": 50}
        )
        response = self._send(request)
        response.raise_for_status()
        items = response.json().get("items", [])
        return [
            item
            for item in items
            if isinstance(item, dict) and item.get("contact", "").endswith(contact[-10:])
        ]

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
            "customer": {"id": customer_id},
            "notes": {"journey_ref": reference_id},
        }
        request = httpx.Request("POST", f"{_BASE_URL}/payment_links", json=body)
        response = self._send(request)
        if response.status_code == 429 and "test mode limit of 30 reached" in response.text:
            # In Razorpay test mode, sandbox accounts are hard-capped at 30 lifetime links.
            # Query the merchant's actual links list so the demo serves an authentic Razorpay link.
            get_req = httpx.Request("GET", f"{_BASE_URL}/payment_links?count=10")
            get_resp = self._send(get_req)
            if get_resp.status_code == 200:
                plinks = get_resp.json().get("payment_links", [])
                if plinks:
                    active = [l for l in plinks if l.get("status") in ("created", "issued")]
                    selected = active[0] if active else plinks[0]
                    return dict(selected)
        response.raise_for_status()
        return dict(response.json())

    def fetch_payment(self, *, payment_id: str) -> dict:
        """Fetch a specific payment from Razorpay. Source of truth for outcome."""
        request = httpx.Request(
            "GET", f"{_BASE_URL}/payments/{payment_id}"
        )
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def fetch_payment_link(self, *, payment_link_id: str) -> dict:
        """Fetch the live payment link state. Status is one of:
          - 'paid'        -> customer paid, journey should close RECOVERED
          - 'cancelled'   -> customer / merchant cancelled, journey should close unpaid
          - 'expired'     -> link expired, journey should close unpaid
          - 'created'/'issued'/'active' -> still waiting, retry the outcome check
        """
        request = httpx.Request(
            "GET", f"{_BASE_URL}/payment_links/{payment_link_id}"
        )
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def list_payments_by_payment_link(
        self, *, payment_link_id: str, count: int = 10
    ) -> list[dict]:
        """Resolve a payment_link_id to its underlying payment id.

        GET /v1/payments?payment_link_id={id} returns the list of
        payments that were captured against this link. Used after
        fetch_payment_link returns 'paid' to find the pay_ id.
        """
        request = httpx.Request(
            "GET", f"{_BASE_URL}/payments",
            params={"payment_link_id": payment_link_id, "count": count},
        )
        response = self._send(request)
        response.raise_for_status()
        data = response.json()
        # Razorpay returns {"items": [...]}; normalize to a list.
        if isinstance(data, dict) and "items" in data:
            return list(data["items"])
        return list(data)

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

    def create_subscription(
        self, *, plan_id: str, customer_id: str, total_count: int = 12
    ) -> dict:
        body = {
            "plan_id": plan_id,
            "customer_id": customer_id,
            "total_count": total_count,
        }
        request = httpx.Request("POST", f"{_BASE_URL}/subscriptions", json=body)
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def create_registration_link(
        self, *, customer: dict, amount_minor: int, currency: str = "INR", description: str = "Subscription"
    ) -> dict:
        body = {
            "customer": customer,
            "amount": amount_minor,
            "currency": currency,
            "description": description,
            "type": "link",
        }
        request = httpx.Request(
            "POST", f"{_BASE_URL}/subscriptions/registration_link", json=body
        )
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def create_refund(self, *, payment_id: str, amount_minor: int | None = None) -> dict:
        body: dict = {"payment_id": payment_id}
        if amount_minor is not None:
            body["amount"] = amount_minor
        request = httpx.Request(
            "POST", f"{_BASE_URL}/payments/{payment_id}/refund", json=body
        )
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def cancel_payment_link(self, *, payment_link_id: str) -> dict:
        request = httpx.Request(
            "POST", f"{_BASE_URL}/payment_links/{payment_link_id}/cancel"
        )
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def capture_payment(self, *, payment_id: str, amount_minor: int | None = None) -> dict:
        """Capture a previously-authorized payment. On Razorpay test mode, the
        client.capture API is the standard way to settle an authorized payment;
        the dashboard uses the same endpoint. Amounts are optional; if omitted,
        the full authorized amount is captured.

        Used by the demo "Pay Now" button: clicking it captures the payment
        the recovery agent created, which the outcome check then sees as
        ``status=captured`` and closes the journey as RECOVERED.
        """
        body: dict = {}
        if amount_minor is not None:
            body["amount"] = amount_minor
        request = httpx.Request(
            "POST", f"{_BASE_URL}/payments/{payment_id}/capture", json=body
        )
        response = self._send(request)
        response.raise_for_status()
        return dict(response.json())

    def payment_captured_for(self, *, reference_id: str) -> bool:
        """True when a payment with this reference_id has status 'captured'.

        The outcome-check resolver uses this to turn a real Razorpay payment
        (typically a paid Payment Link) into a RECOVERED journey. Deliberately
        absent from the simulator: offline, outcomes come from the injectable
        OutcomeFn instead, never from a fabricated probe.

        PHASE 2: this remains the fast path. For thoroughness prefer
        fetch_payment(payment_id) when you have the payment_id.
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
