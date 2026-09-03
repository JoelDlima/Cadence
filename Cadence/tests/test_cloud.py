"""Phase E3 cloud tests: webhook-inbox polling + journey/metrics mirroring.

httpx.MockTransport captures outgoing PostgREST requests; offline-first
behavior is proven by asserting ZERO requests when not live.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from cadence.clock import FakeClock
from cadence.cloud.poller import SupabaseInboxPoller
from cadence.cloud.sync import CloudSync
from cadence.config import CloudConfig
from cadence.store.db import Database
from cadence.store.journey_repo import JourneyRepo

LIVE_CFG = CloudConfig("https://xyz.supabase.co", "service-key", True)
OFFLINE_CFG = CloudConfig("", "", False)

Handler = Callable[[httpx.Request], httpx.Response]


def _capture(handler: Handler) -> tuple[list[httpx.Request], httpx.MockTransport]:
    """MockTransport that records every request in order."""
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return requests, httpx.MockTransport(recording_handler)


def _noop_process(raw: bytes, signature: str | None) -> object:
    return None


def _seed_journey(
    repo: JourneyRepo,
    *,
    journey_id: str,
    subscription_id: str,
    opened_at: str,
    amount_minor: int,
) -> None:
    repo.create(
        journey_id=journey_id,
        subscription_id=subscription_id,
        customer_id=f"cust-{journey_id}",
        amount_minor=amount_minor,
        currency="INR",
        failure_code="insufficient_funds",
        opened_at=opened_at,
    )


# ---------------------------------------------------------------------------
# Poller


def test_poller_offline_makes_zero_requests(tmp_db: Database, fake_clock: FakeClock) -> None:
    requests, transport = _capture(lambda request: httpx.Response(200, json=[]))
    poller = SupabaseInboxPoller(OFFLINE_CFG, tmp_db, fake_clock, transport=transport)

    assert poller.run_once(_noop_process) == 0
    assert requests == []


def test_poller_processes_row_then_marks_processed(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    row = {
        "id": "row-1",
        "payload": {"event": "subscription.pending", "amount": 49900},
        "signature": "sig-abc",
        "processed": False,
    }
    seen: list[tuple[bytes, str | None]] = []

    def process(raw: bytes, signature: str | None) -> object:
        seen.append((raw, signature))
        return True

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[row])
        return httpx.Response(204)

    requests, transport = _capture(handler)
    poller = SupabaseInboxPoller(
        LIVE_CFG, tmp_db, fake_clock, process_fn=process, transport=transport
    )

    assert poller.run_once(process) == 1
    assert seen == [(json.dumps(row["payload"]).encode(), "sig-abc")]
    patch = next(r for r in requests if r.method == "PATCH")
    assert "id=eq.row-1" in str(patch.url)
    assert patch.headers["Prefer"] == "return=minimal"
    body = json.loads(patch.content)
    assert body["processed"] is True
    assert body["processed_at"] == fake_clock.now().isoformat()


def test_poller_fetch_failure_returns_empty_list(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _, transport = _capture(handler)
    poller = SupabaseInboxPoller(LIVE_CFG, tmp_db, fake_clock, transport=transport)

    assert poller.fetch_pending() == []
    assert poller.run_once(_noop_process) == 0


# ---------------------------------------------------------------------------
# CloudSync


def test_sync_journeys_posts_mirror_upsert(tmp_db: Database, fake_clock: FakeClock) -> None:
    repo = JourneyRepo(tmp_db)
    _seed_journey(
        repo,
        journey_id="j-1",
        subscription_id="sub-1",
        opened_at="2026-08-21T09:00:00+00:00",
        amount_minor=29900,
    )
    _seed_journey(
        repo,
        journey_id="j-2",
        subscription_id="sub-2",
        opened_at="2026-08-21T08:00:00+00:00",
        amount_minor=19900,
    )
    requests, transport = _capture(lambda request: httpx.Response(201))
    sync = CloudSync(LIVE_CFG, tmp_db, fake_clock, transport=transport)

    pushed = sync.sync_journeys()

    assert pushed == 2
    post = next(r for r in requests if r.method == "POST")
    assert post.url.path.endswith("/rest/v1/journeys_mirror")
    assert "merge-duplicates" in post.headers["Prefer"]
    assert post.headers["apikey"] == "service-key"
    rows = json.loads(post.content)
    assert [r["journey_id"] for r in rows] == ["j-1", "j-2"]


def test_sync_journeys_offline_returns_zero_without_requests(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    _seed_journey(
        JourneyRepo(tmp_db),
        journey_id="j-x",
        subscription_id="sub-x",
        opened_at="2026-08-21T09:00:00+00:00",
        amount_minor=100,
    )
    requests, transport = _capture(lambda request: httpx.Response(201))

    sync = CloudSync(OFFLINE_CFG, tmp_db, fake_clock, transport=transport)

    assert sync.sync_journeys() == 0
    assert sync.sync_metrics() == 0
    assert requests == []


def test_sync_metrics_aggregates_recovered_amount(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    repo = JourneyRepo(tmp_db)
    _seed_journey(
        repo,
        journey_id="j-r",
        subscription_id="sub-r",
        opened_at="2026-08-20T09:00:00+00:00",
        amount_minor=49900,
    )
    repo.update_fields(
        "j-r",
        {"state": "RECOVERED", "closed_at": "2026-08-22T07:30:00+00:00"},
        updated_at="2026-08-22T07:30:00+00:00",
    )
    requests, transport = _capture(lambda request: httpx.Response(201))
    sync = CloudSync(LIVE_CFG, tmp_db, fake_clock, transport=transport)

    pushed = sync.sync_metrics()

    assert pushed == 1
    post = next(r for r in requests if r.method == "POST")
    assert post.url.path.endswith("/rest/v1/metrics_daily")
    body = json.loads(post.content)[0]
    assert body["day"] == "2026-08-22"
    assert body["recovered_count"] == 1
    assert body["recovered_inr_major"] == pytest.approx(499.0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
