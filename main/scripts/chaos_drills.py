"""Chaos drills: four adversarial scenarios, one verdict line each.

Run from main/:  python scripts/chaos_drills.py

Drills:
  1. duplicate-webhook     replayed signed subscription.pending processed once
  2. crash-resume          kill everything mid-journey, rebuild over the same db
  3. ai-provider-dead      LLM provider unreachable -> deterministic path still recovers
  4. illegal-proposal-veto Guardian vetoes illegal moves and over-tier amounts

Exit code 0 only when all four pass. Deterministic throughout: FakeClock,
simulated Razorpay client, mocked HTTP transport - no keys, no network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx
from fastapi.testclient import TestClient

from revive.agents.llm_client import LLMClient
from revive.agents.planner import PlannerAgent
from revive.api.app import create_app
from revive.classify.taxonomy import (
    EXPIRED_INSTRUMENT,
    HARD_DECLINE,
    LEGAL_MOVES,
    NO_FUNDS,
    RETRY_PAYDAY,
    WHATSAPP_NUDGE,
)
from revive.clock import FakeClock, utc_iso
from revive.config import (
    AppConfig,
    ChannelConfig,
    CloudConfig,
    LLMConfig,
    PolicyConfig,
    RazorpayConfig,
)
from revive.events import AGG_JOURNEY, E_ACTION_EXECUTED, E_CLASSIFICATION_COMPLETED
from revive.executors.contracts import TASK_EXECUTE_INTENT, request_from_payload
from revive.executors.dispatcher import Dispatcher
from revive.executors.razorpay_client import SimulatedRazorpayClient
from revive.ingest.gateway import SIGNATURE_HEADER
from revive.journey.engine import RecoveryEngine
from revive.policy.guardian import JourneyContext, Proposal, evaluate
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import (
    STATE_INTERVENING,
    STATE_RECOVERED,
    STATE_WAITING_OUTCOME,
    JourneyRepo,
)
from revive.store.queue_repo import QueueRepo
from revive.worker.bus import Worker


def _policy_cfg() -> PolicyConfig:
    return PolicyConfig(
        touch_cap_per_window=3,
        touch_window_days=14,
        max_retry_attempts=3,
        quiet_hours_start=21,
        quiet_hours_end=9,
        timezone="Asia/Kolkata",
    )


def _llm_cfg() -> LLMConfig:
    return LLMConfig(
        provider_order=["groq"],
        gemini_api_key="",
        groq_api_key="gkey",
        openrouter_api_key="",
        model_gemini="gemini-test",
        model_groq="llama-test",
        model_openrouter="or-test",
        daily_request_cap=10,
    )


def _app_cfg(db_path: Path) -> AppConfig:
    return AppConfig(
        host="127.0.0.1",
        port=8000,
        db_path=db_path,
        log_level="INFO",
        razorpay=RazorpayConfig(key_id="", key_secret="", webhook_secret="chaos_s3cret"),
        llm=_llm_cfg(),
        channels=ChannelConfig(resend_api_key="", email_from="revive@example.com"),
        policy=_policy_cfg(),
        cloud=CloudConfig(supabase_url="", supabase_service_key="", sync_enabled=False),
    )


def _verdict(drill: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}: {drill} - {detail}")
    return ok


def _record(drill: str, ok: bool, detail: str) -> dict[str, Any]:
    """Structured result for the API endpoint; no stdout."""
    return {"drill": drill, "passed": ok, "detail": detail}


# ``Database`` opens cross-thread-capable connections itself now, so the old
# sqlite3.connect shim is gone - TestClient worker threads just work.


# --- drill 1: duplicate-webhook -----------------------------------------------


def _pending_webhook_body() -> dict[str, Any]:
    return {
        "id": "evt_CHAOS_DUP_1",
        "event": "subscription.pending",
        "payload": {
            "subscription": {"entity": {"id": "sub_chaos_dup", "customer_id": "cust_dup"}},
            "payment": {
                "entity": {
                    "id": "pay_CHAOSDUP1",
                    "order_id": "order_CHAOS1",
                    "amount": 49900,
                    "currency": "INR",
                    "error_code": "insufficient_funds",
                    "error_description": "Insufficient funds in bank account",
                }
            },
        },
    }


def _post_signed(client: TestClient, secret: str, body: dict[str, Any]) -> httpx.Response:
    raw = json.dumps(body).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/razorpay", content=raw, headers={SIGNATURE_HEADER: sig})


def _run_duplicate_webhook(work: Path) -> dict[str, Any]:
    cfg = _app_cfg(work / "chaos_dup.db")
    client = TestClient(create_app(cfg=cfg))
    counter_db = Database(cfg.db_path)
    store = EventStore(counter_db)
    body = _pending_webhook_body()

    first = _post_signed(client, cfg.razorpay.webhook_secret, body)
    events_after_first = store.count()
    replay = _post_signed(client, cfg.razorpay.webhook_secret, body)
    events_after_replay = store.count()
    counter_db.close()

    ok = (
        first.json() == {"status": "accepted"}
        and replay.json() == {"status": "duplicate"}
        and events_after_replay == events_after_first > 0
    )
    detail = (
        f"delivery1={first.json()['status']}, replay={replay.json()['status']}, "
        f"event log frozen at {events_after_first} across both deliveries"
    )
    return _record("duplicate_webhook", ok, detail)


def drill_duplicate_webhook(work: Path) -> bool:
    r = _run_duplicate_webhook(work)
    return _verdict(r["drill"], r["passed"], r["detail"])


# --- drill 2: crash-resume -----------------------------------------------------


def _failed_payload(subscription_id: str) -> dict[str, Any]:
    return {
        "subscription_id": subscription_id,
        "customer_id": f"cust_{subscription_id}",
        "failure_code": "insufficient_funds",
        "error_description": "insufficient balance",
        "amount_minor": 49900,
        "currency": "INR",
    }


def _engine(db: Database, clock: FakeClock) -> RecoveryEngine:
    return RecoveryEngine(
        db=db,
        event_store=EventStore(db),
        journeys=JourneyRepo(db),
        queue=QueueRepo(db),
        cfg=_policy_cfg(),
        clock=clock,
    )


def _handlers(db: Database, clock: FakeClock) -> dict[str, Callable[[dict[str, Any]], None]]:
    dispatcher = Dispatcher(
        db=db,
        event_store=EventStore(db),
        journeys=JourneyRepo(db),
        queue=QueueRepo(db),
        client=SimulatedRazorpayClient(),
        cfg=_policy_cfg(),
        clock=clock,
        outcome_fn=lambda _seed: True,  # customer always pays the retried debit
    )
    engine = _engine(db, clock)
    return {
        TASK_EXECUTE_INTENT: lambda payload: dispatcher.execute(request_from_payload(payload)),
        "handle_payment_failed": engine.handle_payment_failed,
    }


def _run_crash_resume(work: Path) -> dict[str, Any]:
    sub_id = "sub_chaos_crash"
    db_path = work / "chaos_crash.db"
    pre_clock = FakeClock()
    pre_db = Database(db_path)
    _engine(pre_db, pre_clock).handle_payment_failed(_failed_payload(sub_id))
    journey_pre = JourneyRepo(pre_db).get_by_subscription(sub_id)
    tasks_pre = QueueRepo(pre_db).pending_count()
    pre_ok = (
        journey_pre is not None and journey_pre.state == STATE_INTERVENING and tasks_pre == 1
    )
    pre_db.close()  # SIMULATED CRASH: abandon every in-memory object right here

    post_clock = FakeClock()
    post_clock.advance(timedelta(days=3))  # past the payday timer
    reborn_db = Database(db_path)  # brand-new stack over the SAME db file
    worker = Worker(QueueRepo(reborn_db), post_clock)
    handlers = _handlers(reborn_db, post_clock)
    claimed_first_tick = worker.run_once(handlers)
    claimed_second_tick = worker.run_once(handlers)  # nothing left to double-run

    store = EventStore(reborn_db)
    journeys = JourneyRepo(reborn_db)
    final = journeys.get_by_subscription(sub_id)
    journey_id = final.journey_id if final else ""
    executions = [
        e
        for e in store.get_by_aggregate(AGG_JOURNEY, journey_id)
        if e.type == E_ACTION_EXECUTED and e.payload.get("kind") == RETRY_PAYDAY
    ]
    chain_ok = store.verify_chain()[0]
    resumed_ok = final is not None and final.state in {STATE_WAITING_OUTCOME, STATE_RECOVERED}
    reborn_db.close()
    ok = (
        pre_ok
        and resumed_ok
        and claimed_first_tick >= 1
        and claimed_second_tick == 0
        and len(executions) == 1
        and chain_ok
    )
    detail = (
        f"journey was INTERVENING with 1 queued task at crash; rebuilt stack resumed: "
        f"state={final.state if final else 'missing'}, retry executions={len(executions)} "
        f"(idempotency key consumed once), audit chain intact={chain_ok}"
    )
    return _record("crash_resume", ok, detail)


def drill_crash_resume(work: Path) -> bool:
    r = _run_crash_resume(work)
    return _verdict(r["drill"], r["passed"], r["detail"])


# --- drill 3: ai-provider-dead -------------------------------------------------


def _run_ai_provider_dead(work: Path) -> dict[str, Any]:
    sub_id = "sub_chaos_llmdead"

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated provider outage", request=request)

    db = Database(work / "chaos_llmdead.db")
    clock = FakeClock()
    llm = LLMClient(cfg=_llm_cfg(), db=db, clock=clock, transport=httpx.MockTransport(unreachable))
    completion, provider = llm.complete_json(system="sys", prompt="usr")
    proposal = PlannerAgent(llm=llm).propose(
        root_cause=NO_FUNDS,
        legal_moves=sorted(LEGAL_MOVES[NO_FUNDS]),
        failure_context={},
        attempt_no=1,
    )

    _engine(db, clock).handle_payment_failed(_failed_payload(sub_id))
    store = EventStore(db)
    classifications = [
        e
        for e in store.get_by_aggregate(AGG_JOURNEY, sub_id)
        if e.type == E_CLASSIFICATION_COMPLETED
    ]
    classified_no_funds = any(
        e.payload["root_cause"] == NO_FUNDS and e.payload["source"] == "rules"
        for e in classifications
    )
    intents = QueueRepo(db).claim_due(  # none due yet: payday timer still in the future
        now_iso=utc_iso(clock.now()), limit=10
    )
    scheduled = QueueRepo(db).pending_count() == 1 and intents == []

    post_clock = FakeClock()
    post_clock.advance(timedelta(days=3))
    worker = Worker(QueueRepo(db), post_clock)
    worker.run_once(_handlers(db, post_clock))
    final = JourneyRepo(db).get_by_subscription(sub_id)
    spend_rows = db.conn.execute("SELECT COUNT(*) AS c FROM llm_spend").fetchone()["c"]
    llm.close()
    db.close()

    ok = (
        completion is None
        and provider == ""
        and proposal is None
        and classified_no_funds
        and scheduled
        and final is not None
        and final.state == STATE_RECOVERED
        and spend_rows == 0
    )
    detail = (
        f"provider dead: complete_json=({completion!r},{provider!r}), propose={proposal}, "
        f"rules fast path classified NO_FUNDS + scheduled payday retry -> "
        f"{final.state if final else 'missing'}; llm_spend rows={spend_rows}"
    )
    return _record("ai_provider_dead", ok, detail)


def drill_ai_provider_dead(work: Path) -> bool:
    r = _run_ai_provider_dead(work)
    return _verdict(r["drill"], r["passed"], r["detail"])


# --- drill 4: illegal-proposal-veto --------------------------------------------


def _ctx(root_cause: str) -> JourneyContext:
    return JourneyContext(
        journey_id="j_chaos_veto",
        customer_id="cust_chaos_veto",
        root_cause=root_cause,
        attempts_used=0,
        touches_used=0,
        window_started_at=None,
    )


def _run_illegal_proposal_veto() -> dict[str, Any]:
    clock = FakeClock()
    scheduled_at = utc_iso(clock.now())

    # Rule-order note: on HARD_DECLINE the guardian's stop rule fires before the
    # legality matrix, so the WHATSAPP_NUDGE proposal is vetoed even harder.
    on_hard_decline = evaluate(
        Proposal(WHATSAPP_NUDGE, scheduled_at), _ctx(HARD_DECLINE), cfg=_policy_cfg(), clock=clock
    )
    on_expired_instrument = evaluate(
        Proposal(WHATSAPP_NUDGE, scheduled_at),
        _ctx(EXPIRED_INSTRUMENT),
        cfg=_policy_cfg(),
        clock=clock,
    )
    tiered = evaluate(
        Proposal(RETRY_PAYDAY, "2026-08-25T04:30:00+00:00", amount_minor=6_000_000),
        _ctx(NO_FUNDS),
        cfg=_policy_cfg(),
        clock=clock,
    )

    hd_ok = not on_hard_decline.approved and on_hard_decline.reason == "hard_decline_stop"
    illegal_ok = (
        not on_expired_instrument.approved
        and on_expired_instrument.reason == "illegal_intervention"
    )
    tier_ok = not tiered.approved and tiered.reason == "finance_approval_required"
    ok = hd_ok and illegal_ok and tier_ok
    detail = (
        f"WHATSAPP_NUDGE@HARD_DECLINE -> veto({on_hard_decline.reason}); "
        f"WHATSAPP_NUDGE@EXPIRED_INSTRUMENT -> veto({on_expired_instrument.reason}); "
        f"RETRY_PAYDAY@6_000_000minor -> veto({tiered.reason})"
    )
    return _record("illegal_proposal_veto", ok, detail)


def drill_illegal_proposal_veto() -> bool:
    r = _run_illegal_proposal_veto()
    return _verdict(r["drill"], r["passed"], r["detail"])


# Public dispatcher: API endpoint calls this with a drill name and gets a dict.
DRILL_DISPATCH: dict[str, Callable[[Path], dict[str, Any]]] = {
    "duplicate_webhook": _run_duplicate_webhook,
    "crash_resume": _run_crash_resume,
    "ai_provider_dead": _run_ai_provider_dead,
}


def run_drill(name: str, workdir: Path | None = None) -> dict[str, Any]:
    """Run one drill by name and return its structured result.

    For ``illegal_proposal_veto`` (no DB needed) the workdir is ignored.
    For others a fresh tempdir is used when ``workdir`` is None.
    """
    if name == "illegal_proposal_veto":
        return _run_illegal_proposal_veto()
    runner = DRILL_DISPATCH.get(name)
    if runner is None:
        return {"drill": name, "passed": False, "detail": f"unknown drill: {name}"}
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="revive_chaos_api_"))
    return runner(workdir)


def main() -> int:
    # Windows: some drill connections (e.g. TestClient-owned app state) cannot be
    # closed from here; ignore_cleanup_errors prevents rmtree lock errors masking results.
    with tempfile.TemporaryDirectory(prefix="revive_chaos_", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        passed = [
            drill_duplicate_webhook(work),
            drill_crash_resume(work),
            drill_ai_provider_dead(work),
            drill_illegal_proposal_veto(),
        ]
    import gc

    gc.collect()  # drop last references so SQLite handles release before temp cleanup
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
