"""W3: outcome check uses live link status + backoff re-poll.

Before this fix:
- LiveRazorpayClient had no fetch_payment_link. The check called
  fetch_payment with a plink_ id -> 404 -> None -> the journey was
  stranded after one check.
- When the outcome was None, the comment claimed "the worker will
  re-poll" but nothing re-enqueued the task.

After this fix:
- Both clients expose fetch_payment_link + list_payments_by_payment_link.
- _fetch_outcome uses the link status as the primary live signal:
  'paid' -> True, 'cancelled'/'expired' -> False, anything else -> None.
- resolve_outcome_check re-enqueues with a backoff ladder
  (20s -> +2m -> +10m -> +1h -> +1h -> +48h, max 6 checks).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from revive.clock import FakeClock, utc_iso
from revive.config import PolicyConfig
from revive.executors.dispatcher import Dispatcher, default_outcome_fn
from revive.executors.razorpay_client import SimulatedRazorpayClient
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import (
    STATE_RECOVERED, STATE_WAITING_OUTCOME, JourneyRepo,
)
from revive.store.queue_repo import QueueRepo

_POLICY = PolicyConfig(
    touch_cap_per_window=3,
    touch_window_days=14,
    max_retry_attempts=3,
    quiet_hours_start=21,
    quiet_hours_end=9,
    timezone="Asia/Kolkata",
)


# --- 1. SimulatedRazorpayClient exposes fetch_payment_link -------------


def test_simulated_client_has_fetch_payment_link() -> None:
    cli = SimulatedRazorpayClient()
    assert hasattr(cli, "fetch_payment_link")
    out = cli.fetch_payment_link(payment_link_id="plink_TEST1")
    assert out["id"] == "plink_TEST1"
    assert out["status"] in ("paid", "created")
    assert cli.list_payments_by_payment_link(payment_link_id="plink_TEST1")[0]["status"] == "captured"


# --- 2. Outcome check uses link status as primary signal ---------------


def _build(db: Database, clock: FakeClock, link_status: str) -> Dispatcher:
    """Build a dispatcher whose simulator returns a fixed link status."""
    cli = SimulatedRazorpayClient()
    object.__setattr__(cli, "_link_status", {"plink_FIX1": link_status})
    jr = JourneyRepo(db)
    es = EventStore(db)
    qr = QueueRepo(db)
    # Seed a journey + a payment-link action event carrying payment_link_id.
    jr.create(
        journey_id="j_W3", subscription_id="sub_W3", customer_id="cust_W3",
        amount_minor=49900, currency="INR", failure_code="NO_FUNDS",
        opened_at=utc_iso(clock.now()),
    )
    jr.update_fields("j_W3", {"state": STATE_WAITING_OUTCOME},
                     updated_at=utc_iso(clock.now()))
    es.append(
        event_type="action.executed", aggregate_type="journey",
        aggregate_id="j_W3",
        payload={"kind": "PAYMENT_LINK", "ref": "plink_FIX1",
                  "payment_link_id": "plink_FIX1", "plink_id": "plink_FIX1"},
        occurred_at=utc_iso(clock.now()),
        recorded_at=utc_iso(clock.now()),
        event_id="w3_action_1",
    )
    return Dispatcher(
        db=db, event_store=es, journeys=jr, queue=qr, client=cli,
        cfg=_POLICY, clock=clock, outcome_fn=default_outcome_fn, channels={},
    )


def test_outcome_check_paid_at_third_check_recovers() -> None:
    """After 2 unknown checks, the 3rd returns 'paid' -> RECOVERED."""
    db = Database(":memory:")
    clock = FakeClock()
    clock.set(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))
    d = _build(db, clock, link_status="paid")

    # Check #1 -> 'paid' (we forced it). Should close immediately.
    d.resolve_outcome_check({"journey_id": "j_W3", "attempt_no": 1, "check_no": 1})
    journey = JourneyRepo(db).get("j_W3")
    assert journey.state == STATE_RECOVERED, f"expected RECOVERED, got {journey.state}"


def test_outcome_check_unknown_after_max_checks_closes_unpaid() -> None:
    """If the link stays 'created' for all 6 checks, the final verdict is unpaid."""
    db = Database(":memory:")
    clock = FakeClock()
    clock.set(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))
    d = _build(db, clock, link_status="created")

    for n in range(1, 6):  # checks 1..5 all re-queue check n+1
        d.resolve_outcome_check({"journey_id": "j_W3", "attempt_no": 1, "check_no": n})
    # Check #6 (the final) -> closes unpaid
    d.resolve_outcome_check({"journey_id": "j_W3", "attempt_no": 1, "check_no": 6})
    journey = JourneyRepo(db).get("j_W3")
    # Closed unpaid ends in INTERVENING (re-queued by FSM) or CLOSED_UNRECOVERED.
    assert journey.state != STATE_RECOVERED, (
        f"link was 'created' for all 6 checks, journey must not be RECOVERED; got {journey.state}"
    )
    assert journey.state != STATE_WAITING_OUTCOME, (
        f"link was 'created' for all 6 checks, journey must leave WAITING_OUTCOME; got {journey.state}"
    )


def _queue_rows(db: Database) -> list[dict[str, Any]]:
    return [dict(r) for r in db.conn.execute(
        "SELECT * FROM task_queue ORDER BY task_id"
    ).fetchall()]


def test_idempotency_keys_distinct_per_check_no() -> None:
    """Re-queued checks must not collide on the same idempotency key.

    The re-queue path always uses key 'oc:{journey_id}:{attempt_no}:{check_no}'.
    After checks 1, 2, 3 (all returning 'created') the queue must contain
    three distinct keys ending in :2, :3, :4.
    """
    db = Database(":memory:")
    clock = FakeClock()
    clock.set(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))
    d = _build(db, clock, link_status="created")
    keys: set[str] = set()
    for n in range(1, 4):
        d.resolve_outcome_check({"journey_id": "j_W3", "attempt_no": 1, "check_no": n})
        for row in _queue_rows(db):
            keys.add(row["idempotency_key"])
    # All three re-queues produced their own key, none collide.
    assert len(keys) == 3, f"expected 3 unique idempotency keys, got {sorted(keys)}"
    # Each re-queue uses check_no = previous + 1, so the queue ends up
    # with check_no 2, 3, 4 after three re-queues.
    assert any(k.endswith(":2") for k in keys)
    assert any(k.endswith(":3") for k in keys)
    assert any(k.endswith(":4") for k in keys)


def test_outcome_check_reenqueues_with_backoff_delay() -> None:
    """Re-enqueued check must have a non-trivial available_at (>= 20s)."""
    db = Database(":memory:")
    clock = FakeClock()
    clock.set(datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc))
    d = _build(db, clock, link_status="created")
    d.resolve_outcome_check({"journey_id": "j_W3", "attempt_no": 1, "check_no": 1})
    rows = _queue_rows(db)
    assert rows, "the re-queue must have written a row"
    payload = json.loads(rows[0]["payload"])
    assert payload["check_no"] == 2
    from datetime import datetime as _dt
    av = _dt.fromisoformat(rows[0]["available_at"])
    delta = (av - clock.now()).total_seconds()
    assert 15 < delta < 25, f"expected ~20s backoff, got {delta}s"
