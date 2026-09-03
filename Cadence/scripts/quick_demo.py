"""One-command live demo: watch one failed subscription get recovered.

Run from Cadence/:  python scripts/quick_demo.py

No API keys needed - Razorpay calls use the deterministic simulator, so this shows
the REAL engine paths (ingest shape, classification, guardian, scheduling, durable
timers, executors, event log) end to end.
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cadence.clock import FakeClock, utc_iso
from cadence.config import PolicyConfig
from cadence.executors.contracts import TASK_EXECUTE_INTENT, request_from_payload
from cadence.executors.dispatcher import Dispatcher
from cadence.executors.razorpay_client import SimulatedRazorpayClient
from cadence.journey.engine import RecoveryEngine
from cadence.store.db import Database
from cadence.store.event_store import EventStore
from cadence.store.journey_repo import JourneyRepo
from cadence.store.queue_repo import QueueRepo
from cadence.worker.bus import Worker

DB_PATH = Path("data/demo.db")
if DB_PATH.exists():
    DB_PATH.unlink()

db = Database(DB_PATH)
store = EventStore(db)
journeys = JourneyRepo(db)
queue = QueueRepo(db)
clock = FakeClock()  # starts 2026-08-22 10:00 UTC
cfg = PolicyConfig(
    touch_cap_per_window=3,
    touch_window_days=14,
    max_retry_attempts=3,
    quiet_hours_start=21,
    quiet_hours_end=9,
    timezone="Asia/Kolkata",
    auto_approve_below_minor=500_000,
    require_human_above_minor=5_000_000,
)

engine = RecoveryEngine(db, store, journeys, queue, cfg, clock)
dispatcher = Dispatcher(
    db=db,
    event_store=store,
    journeys=journeys,
    queue=queue,
    client=SimulatedRazorpayClient(),
    cfg=cfg,
    clock=clock,
    outcome_fn=lambda seed: True,  # customer pays on retry for the happy-path demo
)
worker = Worker(queue, clock)


def show(stage: str) -> None:
    print(f"\n=== {stage} ===")
    for e in store.get_by_aggregate("journey", "sub_demo"):
        print(f"  {e.occurred_at}  {e.type:<28} {str(e.payload)[:90]}")


print("Day 0: Razorpay reports a failed auto-debit (insufficient balance, Rs 499)")
engine.handle_payment_failed(
    {
        "subscription_id": "sub_demo",
        "customer_id": "cust_demo",
        "failure_code": "insufficient_funds",
        "error_description": "insufficient balance",
        "amount_minor": 49900,
        "currency": "INR",
    }
)
show("after diagnosis + guardian + scheduling")
j = journeys.get_by_subscription("sub_demo")
assert j.state == "INTERVENING", j.state

due = queue.pending_count()
print(f"\nQueued tasks waiting: {due} (retry fires on next payday 10:00 IST)")

clock.advance(timedelta(days=14))  # jump to payday
for t in queue.claim_due(now_iso=utc_iso(clock.now()), limit=10):
    if t.task_type == TASK_EXECUTE_INTENT:
        dispatcher.execute(request_from_payload(t.payload))

show("after retry executed on payday")
j = journeys.get_by_subscription("sub_demo")
print(f"\nFinal journey state: {j.state}")
print("Audit chain verified:", store.verify_chain()[0])
print("\nEvery step above is an immutable, hash-chained event. That is the product.")

