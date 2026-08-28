"""Seed a single keyless synthetic journey so a fresh `pip install -e ".[dev]"`
clone shows real numbers in the console within seconds.

What it does:
  1. Creates a fresh SQLite DB (data/revive.db) with all migrations applied.
  2. Signs a payment.failed webhook with the dev webhook secret.
  3. Replays it through the same gateway the live app uses.
  4. Lets the engine classify + dispatch.
  5. Prints the journey id, the verified hash chain, and a curl the user can
     re-run to inject more failures.

Zero API keys. Runs in DEMO mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def _bootstrap_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_bootstrap_path()

from revive.clock import SystemClock  # noqa: E402
from revive.config import load_config  # noqa: E402
from revive.events import AGG_JOURNEY  # noqa: E402
from revive.ingest.gateway import process_delivery  # noqa: E402
from revive.journey.engine import RecoveryEngine  # noqa: E402
from revive.store.db import Database  # noqa: E402
from revive.store.event_store import EventStore  # noqa: E402
from revive.store.journey_repo import JourneyRepo  # noqa: E402
from revive.store.queue_repo import QueueRepo  # noqa: E402


def _wipe_db(db_path: Path) -> None:
    """Best-effort unlink; survives a stale WAL/SHM from a previous crashed run."""
    import time as _t
    for stale in (db_path, db_path.with_suffix(db_path.suffix + "-wal"),
                  db_path.with_suffix(db_path.suffix + "-shm")):
        for attempt in range(3):
            if not stale.exists():
                break
            try:
                stale.unlink()
            except PermissionError:
                _t.sleep(0.2)
        if stale.exists():
            print(f"!! could not delete {stale} (in use); close other Cadence processes")


def _make_payload(subscription_id: str) -> dict:
    return {
        "id": f"evt_seed_{int(time.time())}",
        "event": "subscription.pending",
        "payload": {
            "subscription": {"entity": {"id": subscription_id, "customer_id": "cust_seed"}},
            "payment": {
                "entity": {
                    "id": f"pay_seed_{int(time.time())}",
                    "order_id": f"order_{subscription_id}",
                    "amount": 49900,
                    "currency": "INR",
                    "error_code": "insufficient_funds",
                    "error_description": "Insufficient funds in bank account (seed)",
                }
            },
        },
    }


def main() -> int:
    import os as _os
    # Use a separate DB path so we don't collide with a running API / pytest
    # that has data/revive.db open. Default: data/revive-seed.db.
    seed_db = _os.environ.get("SEED_DB_PATH", "data/revive-seed.db")
    db_path = Path(seed_db)
    # Keep the user's normal config (razorpay secret, timezone) but force DB.
    config = load_config()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _wipe_db(db_path)
    print(f"==> fresh DB at {db_path} (DEMO mode, separate from main app DB)")

    db = Database(db_path)
    store = EventStore(db)
    journeys = JourneyRepo(db)
    queue = QueueRepo(db)
    clock = SystemClock()

    payload = _make_payload("sub_seed_01")
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hmac.new(config.razorpay.webhook_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    status, body = process_delivery(
        db=db,
        webhook_secret=config.razorpay.webhook_secret,
        clock=clock,
        raw=raw,
        signature=sig,
        event_id=payload["id"],
    )
    if status != 200:
        print(f"!! webhook rejected: HTTP {status} {body}")
        return 1

    # Drain the engine once. process_delivery enqueues; the worker would normally
    # call this, but the seed runs synchronously so the user sees the journey.
    engine = RecoveryEngine(
        db=db,
        event_store=store,
        journeys=journeys,
        queue=queue,
        cfg=config.policy,
        clock=clock,
    )
    now_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    due = queue.claim_due(now_iso=now_iso, limit=1)
    if due:
        task = due[0]
        enriched = {
            "subscription_id": task.payload["subscription_id"],
            "customer_id": "cust_seed",
            "amount_minor": payload["payload"]["payment"]["entity"]["amount"],
            "currency": payload["payload"]["payment"]["entity"]["currency"],
            "failure_code": payload["payload"]["payment"]["entity"]["error_code"],
            "error_description": payload["payload"]["payment"]["entity"]["error_description"],
        }
        engine.handle_payment_failed(enriched)
        queue.mark_done(task.task_id)

    journey = journeys.get_by_subscription("sub_seed_01")
    if journey is None:
        print("!! journey was not opened by the engine (unexpected)")
        return 1

    ok, bad_seq = store.verify_chain()
    chain_status = "OK" if ok else f"FAILED at seq {bad_seq}"

    events = store.get_by_aggregate(AGG_JOURNEY, journey.subscription_id)
    print(
        f"==> seeded journey {journey.journey_id}  state={journey.state}  "
        f"root_cause={journey.root_cause or 'pending'}  events={len(events)}  chain={chain_status}"
    )
    print()
    print("Next steps:")
    print("  - Run the API:   python -m uvicorn revive.api.app:app --port 8000")
    print("  - Open the SPA:  cd frontend && npm run dev   (http://127.0.0.1:3000)")
    print("  - Re-inject:     curl -X POST http://127.0.0.1:8000/api/test/inject \\")
    print("                       -H 'Content-Type: application/json' \\")
    print("                       -d '{\"subscription_id\":\"sub_demo\",\"customer_id\":\"cust_demo\",")
    print("                            \"failure_code\":\"insufficient_funds\",\"amount_minor\":49900}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
