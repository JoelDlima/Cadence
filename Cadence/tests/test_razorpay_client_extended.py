"""Tests for the expanded Razorpay client surface (PHASE 1)."""
from __future__ import annotations

import json

import httpx
import pytest

from revive.executors.razorpay_client import (
    LiveRazorpayClient,
    SimulatedRazorpayClient,
    build_client,
)
from revive.config import RazorpayConfig


def _make_transport(responses: list[tuple[int, dict | str]]) -> httpx.MockTransport:
    """Build an httpx.MockTransport that replays the given responses in order."""
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            status, body = next(it)
        except StopIteration:
            return httpx.Response(500, content=b"no more responses")
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, content=str(body).encode())

    return httpx.MockTransport(handler)


def test_simulated_create_customer_is_deterministic():
    s = SimulatedRazorpayClient()
    a = s.create_customer(name="Test", email="t@x.com", contact="+919876543210")
    b = s.create_customer(name="Test", email="t@x.com", contact="+919876543210")
    assert a["id"] == b["id"]  # same input -> same deterministic id
    assert a["id"].startswith("cust_sim_")
    assert a["simulated"] is True


def test_simulated_fetch_payment_is_deterministic():
    s = SimulatedRazorpayClient()
    a = s.fetch_payment(payment_id="pay_xyz")
    b = s.fetch_payment(payment_id="pay_xyz")
    assert a["status"] == b["status"]  # deterministic
    assert a["status"] in ("captured", "failed")


def test_simulated_create_payment_link_id_format():
    s = SimulatedRazorpayClient()
    link = s.create_payment_link(
        amount_minor=49900,
        currency="INR",
        customer_id="cust_1",
        description="test",
        reference_id="ref_42",
    )
    assert link["id"].startswith("plink_sim_")
    assert link["short_url"].startswith("https://rzp.io/i/sim_")
    assert link["status"] == "created"


def test_simulated_create_subscription_and_registration_link():
    s = SimulatedRazorpayClient()
    sub = s.create_subscription(plan_id="plan_X", customer_id="cust_1", total_count=12)
    assert sub["id"].startswith("sub_sim_")
    assert sub["plan_id"] == "plan_X"
    reg = s.create_registration_link(
        customer={"id": "cust_1"}, amount_minor=49900, currency="INR"
    )
    assert reg["id"].startswith("reglink_sim_")


def test_simulated_create_refund():
    s = SimulatedRazorpayClient()
    r = s.create_refund(payment_id="pay_xyz", amount_minor=10000)
    assert r["id"].startswith("rfnd_sim_")
    assert r["payment_id"] == "pay_xyz"
    assert r["amount"] == 10000


def test_simulated_cancel_payment_link():
    s = SimulatedRazorpayClient()
    r = s.cancel_payment_link(payment_link_id="plink_xyz")
    assert r["cancelled"] is True


def test_build_client_returns_simulator_without_keys():
    cfg = RazorpayConfig(key_id="", key_secret="", webhook_secret="x")
    client = build_client(cfg)
    assert isinstance(client, SimulatedRazorpayClient)
    assert client.mode == "simulated"


def test_build_client_returns_live_with_keys():
    cfg = RazorpayConfig(key_id="k", key_secret="s", webhook_secret="x")
    client = build_client(cfg)
    assert isinstance(client, LiveRazorpayClient)
    assert client.mode == "live"


def test_live_create_customer_sends_expected_body():
    """The POST body shape Razorpay sees (when lookup_first=False).
    The mock returns success on POST; lookup-first path is exercised
    separately in test_live_create_customer_reuses_when_match_exists."""
    import httpx
    from revive.executors.razorpay_client import LiveRazorpayClient
    from revive.config import RazorpayConfig

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(200, content=json.dumps({"id": "cust_X", "contact": captured["body"].get("contact")}).encode(), headers={"content-type": "application/json"})
        # GET for lookup-first (not used here, but mock must respond)
        return httpx.Response(200, content=json.dumps({"items": []}).encode(), headers={"content-type": "application/json"})

    cfg = RazorpayConfig(key_id="k", key_secret="s", webhook_secret="x")
    client = LiveRazorpayClient(
        cfg=cfg, transport=httpx.Client(transport=httpx.MockTransport(handler))
    )
    out = client.create_customer(
        name="T", email="e@x.com", contact="+919876543210", lookup_first=False
    )
    assert out["id"] == "cust_X"
    assert captured["body"]["name"] == "T"
    assert captured["body"]["email"] == "e@x.com"
    assert captured["body"]["contact"] == "+919876543210"


def test_live_create_customer_reuses_when_match_exists():
    """The reuse path on the LiveRazorpayClient itself: GET /v1/customers,
    find one with matching contact, return it. Uses the client's own
    transport so the mock is honoured."""
    import json
    import httpx
    from revive.executors.razorpay_client import LiveRazorpayClient
    from revive.config import RazorpayConfig

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "items": [
                            {"id": "cust_OLD", "entity": "customer", "contact": "+919876543210"},
                            {"id": "cust_OTHER", "entity": "customer", "contact": "+910000000000"},
                        ]
                    }
                ).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200,
            content=json.dumps({"id": "cust_NEW", "entity": "customer", "contact": "+919876543210"}).encode(),
            headers={"content-type": "application/json"},
        )

    cfg = RazorpayConfig(key_id="k", key_secret="s", webhook_secret="x")
    client = LiveRazorpayClient(
        cfg=cfg, transport=httpx.Client(transport=httpx.MockTransport(handler))
    )
    out = client.create_customer(name="T", email="e", contact="+919876543210")
    assert out["id"] == "cust_OLD"
    assert out["contact"] == "+919876543210"


def test_live_fetch_payment_returns_dict():
    transport = _make_transport(
        [
            (
                200,
                {
                    "id": "pay_X",
                    "entity": "payment",
                    "amount": 49900,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                    "error_code": None,
                },
            )
        ]
    )
    cfg = RazorpayConfig(key_id="k", key_secret="s", webhook_secret="x")
    client = LiveRazorpayClient(cfg=cfg, transport=httpx.Client(transport=transport))
    out = client.fetch_payment(payment_id="pay_X")
    assert out["id"] == "pay_X"
    assert out["status"] == "captured"


def test_live_simulate_mandate_retry_raises():
    cfg = RazorpayConfig(key_id="k", key_secret="s", webhook_secret="x")
    client = LiveRazorpayClient(cfg=cfg, transport=httpx.Client(transport=_make_transport([])))
    with pytest.raises(RuntimeError, match="NPCI rails"):
        client.simulate_mandate_retry(subscription_id="sub_1", amount_minor=100, seed="x")
