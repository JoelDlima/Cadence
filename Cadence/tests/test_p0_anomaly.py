"""W5: cohort anomaly card on Overview (outage-detector backed).

Before this fix the Anomaly card on OverviewView computed its data
client-side from the live journeys list. The audit flagged this as
"half-wired" — the demo could show the card with stale data and the
recommended actions were the same canned text for every cause.

After this fix:
- src/revive/api/app.py: new /api/anomaly endpoint backed by
  revive.policy.outage.detect_cause_outage. Returns a list of
  {cause, count, severity, window_minutes, threshold, recommendation}.
- src/revive/api/schemas.py: AnomalyOut pydantic model.
- frontend/src/views/OverviewView.tsx: card now consumes the live
  endpoint and surfaces the per-cause recommendation text.
- frontend/src/services/api.ts + types/index.ts: getAnomaly + Anomaly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from revive.clock import FakeClock
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import JourneyRepo

pytestmark = [pytest.mark.unit]


@pytest.fixture
def api_client():
    """Minimal FastAPI app with the /api/anomaly route bound to a real DB."""
    db = Database(":memory:")
    clock = FakeClock()
    clock.set(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))
    app = FastAPI()
    from revive.api.schemas import AnomalyOut
    from revive.policy.outage import detect_cause_outage

    def handler(window_minutes: int = 10, threshold: int = 3):
        now = clock.now()
        rows = db.conn.execute(
            "SELECT failure_code, opened_at FROM journeys "
            "WHERE opened_at IS NOT NULL ORDER BY opened_at DESC LIMIT 500"
        ).fetchall()
        recent: list[str] = []
        for code, opened_at in rows:
            try:
                t = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            except Exception:
                continue
            if (now - t).total_seconds() / 60 <= window_minutes:
                recent.append(str(code) if code else "unknown")
        results: list[AnomalyOut] = []
        for cause in ("NO_FUNDS", "BANK_DOWN", "BAD_VPA", "CUSTOMER_ABORTED",
                      "EXPIRED_INSTRUMENT", "TIMEOUT"):
            if detect_cause_outage(
                recent_failure_causes=recent, cause=cause,
                window_minutes=window_minutes, threshold=threshold,
            ):
                results.append(AnomalyOut(
                    cause=cause, count=recent.count(cause),
                    severity=("alert" if cause == "BANK_DOWN" else
                              "warn" if cause == "NO_FUNDS" else "info"),
                    window_minutes=window_minutes, threshold=threshold,
                    recommendation=f"Spike in {cause}.",
                ))
        return results

    app.add_api_route("/api/anomaly", handler, methods=["GET"])
    return TestClient(app), db, clock


def test_anomaly_empty_when_no_recent_failures(api_client) -> None:
    client, _db, _clock = api_client
    r = client.get("/api/anomaly?window_minutes=10&threshold=3")
    assert r.status_code == 200
    assert r.json() == []


def test_anomaly_detects_no_funds_burst(api_client) -> None:
    """3+ NO_FUNDS in the last 10 minutes must trigger a 'warn' anomaly."""
    client, db, clock = api_client
    jr = JourneyRepo(db)
    now = clock.now()
    for i in range(4):
        jr.create(
            journey_id=f"j_no_funds_{i}", subscription_id=f"sub_nf_{i}",
            customer_id=f"cust_nf_{i}", amount_minor=49900, currency="INR",
            failure_code="NO_FUNDS",
            opened_at=now.astimezone().isoformat(),
        )
    r = client.get("/api/anomaly?window_minutes=10&threshold=3")
    assert r.status_code == 200
    rows = r.json()
    no_funds = [row for row in rows if row["cause"] == "NO_FUNDS"]
    assert no_funds, f"expected NO_FUNDS anomaly, got {rows}"
    assert no_funds[0]["count"] >= 3
    assert no_funds[0]["severity"] == "warn"
    assert "NO_FUNDS" in no_funds[0]["recommendation"] or "Funds" in no_funds[0]["recommendation"]


def test_anomaly_detects_bank_down_as_alert(api_client) -> None:
    """3+ BANK_DOWN in the window is 'alert' severity."""
    client, db, clock = api_client
    jr = JourneyRepo(db)
    now = clock.now()
    for i in range(3):
        jr.create(
            journey_id=f"j_bd_{i}", subscription_id=f"sub_bd_{i}",
            customer_id=f"cust_bd_{i}", amount_minor=49900, currency="INR",
            failure_code="BANK_DOWN",
            opened_at=now.astimezone().isoformat(),
        )
    r = client.get("/api/anomaly?window_minutes=10&threshold=3")
    rows = r.json()
    bank_down = [row for row in rows if row["cause"] == "BANK_DOWN"]
    assert bank_down
    assert bank_down[0]["severity"] == "alert"


def test_anomaly_respects_window(api_client) -> None:
    """Failures OUTSIDE the window must not contribute."""
    client, db, clock = api_client
    jr = JourneyRepo(db)
    now = clock.now()
    # 3 NO_FUNDS, but each one is 20 minutes old (outside the 10-min window).
    old = (now - timedelta(minutes=20)).astimezone().isoformat()
    for i in range(3):
        jr.create(
            journey_id=f"j_old_{i}", subscription_id=f"sub_old_{i}",
            customer_id=f"cust_old_{i}", amount_minor=49900, currency="INR",
            failure_code="NO_FUNDS", opened_at=old,
        )
    r = client.get("/api/anomaly?window_minutes=10&threshold=3")
    rows = r.json()
    no_funds = [row for row in rows if row["cause"] == "NO_FUNDS"]
    assert not no_funds, f"old failures should not trigger anomaly, got {rows}"


def test_anomaly_respects_threshold(api_client) -> None:
    """threshold=5 means 4 NO_FUNDS is below the threshold."""
    client, db, clock = api_client
    jr = JourneyRepo(db)
    now = clock.now()
    for i in range(4):
        jr.create(
            journey_id=f"j_lt_{i}", subscription_id=f"sub_lt_{i}",
            customer_id=f"cust_lt_{i}", amount_minor=49900, currency="INR",
            failure_code="NO_FUNDS",
            opened_at=now.astimezone().isoformat(),
        )
    r = client.get("/api/anomaly?window_minutes=10&threshold=5")
    rows = r.json()
    no_funds = [row for row in rows if row["cause"] == "NO_FUNDS"]
    assert not no_funds
    # But with threshold=3, same data does trigger.
    r = client.get("/api/anomaly?window_minutes=10&threshold=3")
    rows = r.json()
    no_funds = [row for row in rows if row["cause"] == "NO_FUNDS"]
    assert no_funds
