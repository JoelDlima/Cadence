"""PHASE 1 + 4: the payment-link lifecycle drills and the Supabase plink mirror.

These fail on the unfixed version: before the fix, the five lifecycle routes
were declared at module scope against a `router` that only exists inside
`create_live_router`, so importing the module raised NameError and every
endpoint 404'd. They also assert the two things the drills are *for*:
the journey FSM lands in the right state, and the transition is mirrored to
Supabase.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from cadence.cloud import plink_mirror as plink_mirror_module
from cadence.cloud.plink_mirror import PlinkMirror, reset_plink_mirrors
from cadence.config import (
    AppConfig,
    ChannelConfig,
    CloudConfig,
    LLMConfig,
    PolicyConfig,
    RazorpayConfig,
)

pytestmark = [pytest.mark.integration]

WEBHOOK_SECRET = "s3cret_for_lifecycle_tests"


def _config(tmp_path: Path, *, cloud: CloudConfig | None = None,
            groq_key: str = "") -> AppConfig:
    """A keyless AppConfig: the simulator stands in for Razorpay, the LLM is
    off unless a test opts in, and the cloud mirror is off unless injected."""
    policy = PolicyConfig(
        touch_cap_per_window=3, touch_window_days=14, max_retry_attempts=3,
        quiet_hours_start=21, quiet_hours_end=9, timezone="Asia/Kolkata",
    )
    return AppConfig(
        host="127.0.0.1", port=8000, db_path=tmp_path / "lifecycle.sqlite3",
        log_level="WARNING",
        razorpay=RazorpayConfig(key_id="", key_secret="", webhook_secret=WEBHOOK_SECRET),
        llm=LLMConfig(
            provider_order=["groq"] if groq_key else [], gemini_api_key="",
            groq_api_key=groq_key, openrouter_api_key="", model_gemini="",
            model_groq="llama-3.3-70b-versatile", model_openrouter="",
            daily_request_cap=0,
        ),
        channels=ChannelConfig(resend_api_key="", email_from="x@x.local"),
        policy=policy,
        cloud=cloud or CloudConfig(
            supabase_url="", supabase_service_key="", sync_enabled=False,
        ),
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    reset_plink_mirrors()
    return TestClient(create_app(cfg=_config(tmp_path)))


def _open_journey(client: TestClient) -> dict:
    """Run the live flow's first two steps and return the payment link."""
    customer = client.post("/api/live/customer", json={
        "name": "Lifecycle Test", "email": "lc@x.local", "contact": "+919999900000",
    })
    assert customer.status_code == 200, customer.text
    failure = client.post("/api/live/failure",
                          json={"customer_id": customer.json()["id"]})
    assert failure.status_code == 200, failure.text
    return failure.json()


def test_live_failure_runs_classifier_bandit_and_guardian(client: TestClient) -> None:
    opened = _open_journey(client)
    timeline = client.get(f"/api/journeys/{opened['journey_id']}/timeline").json()["events"]
    event_types = {event["type"] for event in timeline}
    assert "classification.completed" in event_types
    assert "bandit.ranked" in event_types
    assert event_types & {"intervention.approved", "intervention.vetoed"}


# --------------------------------------------------------------------------
# 5.1 force-paid
# --------------------------------------------------------------------------
def test_force_paid_endpoint_marks_link_paid_and_closes_recovered(client: TestClient) -> None:
    opened = _open_journey(client)
    reference_id = opened["payment_link"]["reference_id"]

    resp = client.post("/api/live/lifecycle/force-paid",
                       json={"reference_id": reference_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["http"] == 200, body            # the HMAC-signed ingest was accepted
    assert body["plink_state"] == "paid"
    assert body["cadence_state"] == "RECOVERED"
    assert body["plink_id"] == opened["payment_link"]["id"]

    # The Dashboard reads the same fact out of the chain, not out of a cache.
    rows = client.get("/api/dashboard/payment-links").json()
    row = next(r for r in rows if r["plink_id"] == body["plink_id"])
    assert row["status"] == "paid"
    assert row["amount_paid_minor"] == row["amount_minor"]
    assert row["lifecycle"][-1]["to_status"] == "paid"

    # A lifecycle write must never break the hash chain.
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


# --------------------------------------------------------------------------
# 5.2 force-failed
# --------------------------------------------------------------------------
def test_force_failed_endpoint_reenters_recovery(client: TestClient) -> None:
    opened = _open_journey(client)

    resp = client.post("/api/live/lifecycle/force-failed",
                       json={"reference_id": opened["payment_link"]["reference_id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cadence_state"] == "INTERVENING"
    # Razorpay leaves a link payable after a failed debit; the drill must not
    # pretend otherwise.
    assert body["plink_state"] == "created"

    rows = client.get("/api/dashboard/payment-links").json()
    row = next(r for r in rows if r["plink_id"] == body["plink_id"])
    assert row["status"] == "created"
    assert row["journey_state"] == "INTERVENING"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


# --------------------------------------------------------------------------
# 5.3 force-expired
# --------------------------------------------------------------------------
def test_force_expired_endpoint_closes_unrecovered(client: TestClient) -> None:
    opened = _open_journey(client)

    resp = client.post("/api/live/lifecycle/force-expired",
                       json={"reference_id": opened["payment_link"]["reference_id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cadence_state"] == "CLOSED_UNRECOVERED"
    assert body["razorpay_cancelled"] is True   # the cancel API really is called

    journey = client.get(f"/api/journey/{opened['journey_id']}").json()
    assert journey["state"] == "CLOSED_UNRECOVERED"

    rows = client.get("/api/dashboard/payment-links").json()
    row = next(r for r in rows if r["plink_id"] == body["plink_id"])
    assert row["status"] == "expired"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


# --------------------------------------------------------------------------
# 5.4 smart orchestrator without an LLM
# --------------------------------------------------------------------------
def test_smart_endpoint_defaults_to_paid_without_llm(client: TestClient) -> None:
    opened = _open_journey(client)

    resp = client.post("/api/live/lifecycle/smart", json={
        "reference_id": opened["payment_link"]["reference_id"],
        "customer_hint": "always pays after a nudge",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["llm_used"] is False, "no key configured -> must not call out"
    assert body["chosen"]["outcome"] == "paid"
    assert "no LLM configured" in body["chosen"]["reason"]
    assert body["dispatched"]["cadence_state"] == "RECOVERED"

    # The decision is auditable even with no LLM in the loop.
    events = client.get(f"/api/journeys/{opened['journey_id']}/timeline").json()["events"]
    thinking = [e for e in events if e["type"] == "agent.thinking"]
    assert thinking, "smart must record its reasoning in the chain"
    assert thinking[-1]["payload"]["agent"] == "lifecycle_smart"
    assert thinking[-1]["payload"]["customer_hint"] == "always pays after a nudge"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


# --------------------------------------------------------------------------
# 5.5 Supabase plink mirror
# --------------------------------------------------------------------------
def test_plink_mirror_writes_to_supabase(tmp_path: Path, monkeypatch) -> None:
    """With SUPABASE_* configured, creating a link and forcing it paid must
    upsert into cadence_payment_links -- and a cloud failure must not break
    the drill."""
    reset_plink_mirrors()
    seen: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.content))
        if request.method == "GET":
            return httpx.Response(200, json=[])       # row not there yet
        return httpx.Response(201, json=[])

    cloud = CloudConfig(
        supabase_url="https://proj.supabase.co",
        supabase_service_key="service-role-key",
        sync_enabled=True,
    )
    mirror = PlinkMirror(cloud, transport=httpx.Client(
        transport=httpx.MockTransport(handler)))
    assert mirror.enabled
    monkeypatch.setattr(plink_mirror_module, "get_plink_mirror", lambda _cfg: mirror)

    client = TestClient(create_app(cfg=_config(tmp_path, cloud=cloud)))
    opened = _open_journey(client)
    plink_id = opened["payment_link"]["id"]

    writes = [(m, u, c) for (m, u, c) in seen if m == "POST"]
    assert writes, "creating a payment link must upsert the mirror row"
    assert all("cadence_payment_links" in url for _m, url, _c in writes)
    assert "on_conflict=plink_id" in writes[0][1], "upsert, not duplicate-insert"
    assert plink_id.encode() in writes[0][2]

    resp = client.post("/api/live/lifecycle/force-paid",
                       json={"reference_id": opened["payment_link"]["reference_id"]})
    assert resp.status_code == 200, resp.text

    bodies = b"".join(c for m, _u, c in seen if m == "POST" and isinstance(c, bytes))
    assert b"lifecycle.force_paid" in bodies, "the transition must be mirrored"
    assert b'"status":"paid"' in bodies or b'"status": "paid"' in bodies
    snapshot = mirror.snapshot()
    assert snapshot["writes_ok"] >= 2 and snapshot["writes_failed"] == 0

    # Cloud outage: the drill still succeeds, the audit chain still verifies.
    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("supabase unreachable", request=request)

    broken = PlinkMirror(cloud, transport=httpx.Client(
        transport=httpx.MockTransport(failing)))
    monkeypatch.setattr(plink_mirror_module, "get_plink_mirror", lambda _cfg: broken)
    second = _open_journey(client)
    resp = client.post("/api/live/lifecycle/force-paid",
                       json={"reference_id": second["payment_link"]["reference_id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["cadence_state"] == "RECOVERED"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True

    reset_plink_mirrors()


def test_force_paid_is_idempotent(client: TestClient) -> None:
    """Clicking the drill twice must not append a second 'paid' transition."""
    opened = _open_journey(client)
    reference_id = opened["payment_link"]["reference_id"]

    first = client.post("/api/live/lifecycle/force-paid",
                        json={"reference_id": reference_id}).json()
    assert first.get("already") is None
    rows = client.get("/api/dashboard/payment-links").json()
    trail_len = len(next(r for r in rows
                         if r["plink_id"] == first["plink_id"])["lifecycle"])

    second = client.post("/api/live/lifecycle/force-paid",
                         json={"reference_id": reference_id})
    assert second.status_code == 200, second.text
    assert second.json()["already"] is True
    assert second.json()["cadence_state"] == "RECOVERED"

    rows = client.get("/api/dashboard/payment-links").json()
    row = next(r for r in rows if r["plink_id"] == first["plink_id"])
    assert len(row["lifecycle"]) == trail_len, "second call must not add a transition"
    assert client.get("/api/audit/verify").json()["chain_ok"] is True


def test_lifecycle_rejects_unknown_reference(client: TestClient) -> None:
    """A bad reference must 404 with a usable message, not 500."""
    resp = client.post("/api/live/lifecycle/force-paid",
                       json={"reference_id": "j_nope:1"})
    assert resp.status_code == 404
    assert "j_nope" in resp.json()["detail"]

    resp = client.post("/api/live/lifecycle/force-paid",
                       json={"reference_id": "not-a-reference"})
    assert resp.status_code == 404
    assert "journey_id" in resp.json()["detail"]


def test_dashboard_stats_reflect_recovered_money(client: TestClient) -> None:
    """The stats endpoint is the header of the new Dashboard; it must move
    when a journey closes RECOVERED."""
    before = client.get("/api/dashboard/stats").json()
    opened = _open_journey(client)
    client.post("/api/live/lifecycle/force-paid",
                json={"reference_id": opened["payment_link"]["reference_id"]})
    after = client.get("/api/dashboard/stats").json()

    assert after["recovered_count"] == before["recovered_count"] + 1
    assert after["recovered_inr"] > before["recovered_inr"]
    assert after["plink_count"] >= 1
    assert after["plink_paid_count"] >= 1
