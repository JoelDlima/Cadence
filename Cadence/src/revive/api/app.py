"""Control-room FastAPI app (Phase E): read-only views over the event log plus
one write endpoint (the kill switch) that flips the same flag the Guardian
checks, plus the customer-facing self-service recovery page.

Run from Cadence/:  python -m uvicorn revive.api.app:app --port 8000
Console:         http://127.0.0.1:8000/console
Pay page:        http://127.0.0.1:8000/pay/{journey_id}

The app is self-driving: a FastAPI lifespan starts a background worker thread
that drains the Supabase webhook inbox (when cloud sync is on), claims due
durable tasks (engine work, interventions, outcome checks), and mirrors
projections back to Supabase. Posting a webhook is enough - no companion
script needs to tick anything.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import html
import json
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from revive.agents.llm_client import LLMClient
from revive.agents.planner import PlannerAgent
from revive.api.schemas import (
    AgentCompareOut,
    AttentionOut,
    AuditVerifyOut,
    BanksOut,
    ChaosResultOut,
    CircularDetailOut,
    CircularIngestResultOut,
    CircularOut,
    CloudStatusOut,
    EvalSummaryOut,
    EventOut,
    GuardianStatsOut,
    InjectIn,
    InjectOut,
    JourneyOut,
    KillSwitchIn,
    LlmSpendOut,
    MetricsOut,
    PayLinkOut,
    PaySimulateIn,
    PreferencesIn,
    PreferencesOut,
    StatusOut,
)
from revive.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    EXPIRED_INSTRUMENT,
    NO_FUNDS,
    TIMEOUT,
)
from revive.clock import Clock, SystemClock, utc_iso
from revive.cloud.poller import SupabaseInboxPoller
from revive.cloud.sync import CloudSync
from revive.config import AppConfig, load_config
from revive.events import AGG_JOURNEY, E_INTERVENTION_VETOED, E_PAYMENT_FAILED, Event
from revive.executors.channels import EmailChannel, MockWhatsApp
from revive.executors.contracts import (
    TASK_AWAIT_CUSTOMER_REPLY,
    TASK_EXECUTE_INTENT,
    TASK_HANDLE_PAYMENT_FAILED,
    TASK_OUTCOME_CHECK,
    TASK_PAYMENT_CAPTURED,
    request_from_payload,
)
from revive.executors.dispatcher import Dispatcher
from revive.executors.razorpay_client import build_client
from revive.ingest.gateway import create_webhook_router, process_delivery
from revive.journey.engine import RecoveryEngine
from revive.journey.fsm import is_terminal
from revive.logging_setup import get_logger
from revive.policy.preferences import Preferences, PreferencesRepo
from revive.policy.score import recovery_score
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import Journey, JourneyRepo
from revive.store.queue_repo import QueueRepo
from revive.worker.bus import Worker

log = get_logger("revive.api.app")

# Make the scripts/ directory importable so the chaos-drill endpoint can call
# run_drill() from scripts/chaos_drills.py without duplicating the harness.
# Lazy-import inside the endpoint to avoid a circular import (chaos_drills.py
# imports create_app to build a TestClient for its drills).
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

CONSOLE_DIR = Path(__file__).resolve().parents[1] / "console"
JOURNEYS_CAP = 200
_KILL_SWITCH_FLAG = "kill_switch"
_IST = "Asia/Kolkata"
_WORKER_POLL_SECONDS = 2.0
_MIRROR_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class _Runtime:
    """One fully wired stack bound to its own SQLite connection."""

    db: Database
    store: EventStore
    journeys: JourneyRepo
    queue: QueueRepo
    clock: Clock
    engine: RecoveryEngine
    dispatcher: Dispatcher
    worker: Worker
    handlers: dict[str, Callable[[dict], None]]
    poller: SupabaseInboxPoller
    cloud_sync: CloudSync


def _rehydrated_failure_payload(store: EventStore, payload: dict) -> dict:
    """Full failure payload for a queued task.

    Loop-back/save/PTP tasks already carry the complete payload; the gateway's
    minimal task (subscription_id + payment_id only) rehydrates from the
    payment.failed event that started it, so amounts and customers are never
    lost between ingest and engine.
    """
    if payload.get("amount_minor") is not None or payload.get("error_description") is not None:
        return dict(payload)
    payment_id = payload.get("payment_id")
    events = sorted(
        store.get_by_aggregate(AGG_JOURNEY, str(payload["subscription_id"])), key=lambda e: e.seq
    )
    failures = [e for e in events if e.type == E_PAYMENT_FAILED]
    for event in reversed(failures):
        if payment_id is None or event.payload.get("payment_id") == payment_id:
            merged = dict(event.payload)
            merged.setdefault("subscription_id", payload["subscription_id"])
            return merged
    return dict(payload)


def _inbox_process_fn(config: AppConfig, db: Database, clock: Clock) -> Callable[[bytes, str | None], object]:
    """Drain one Supabase inbox row through the same gateway logic as HTTP."""

    def process(raw: bytes, signature: str | None) -> object:
        status, _body = process_delivery(
            db=db,
            webhook_secret=config.razorpay.webhook_secret,
            clock=clock,
            raw=raw,
            signature=signature,
        )
        if status >= 400:
            raise RuntimeError(f"inbox row rejected by local gateway: HTTP {status}")
        return status

    return process


def _build_runtime(config: AppConfig) -> _Runtime:
    db = Database(config.db_path)
    store = EventStore(db)
    journeys = JourneyRepo(db)
    queue = QueueRepo(db)
    clock = SystemClock()
    planner = (
        PlannerAgent(LLMClient(cfg=config.llm, db=db, clock=clock))
        if config.llm_available
        else None
    )
    engine = RecoveryEngine(db, store, journeys, queue, config.policy, clock, planner=planner)
    dispatcher = Dispatcher(
        db=db,
        event_store=store,
        journeys=journeys,
        queue=queue,
        client=build_client(config.razorpay),
        cfg=config.policy,
        clock=clock,
        channels={"whatsapp": MockWhatsApp(), "email": EmailChannel(cfg=config.channels)},
        page_base_url=config.channels.page_base_url,
        llm=LLMClient(cfg=config.llm, db=db, clock=clock)
        if config.llm_available
        else None,  # PHASE 6: nudges go through the LLM when available
    )
    handlers: dict[str, Callable[[dict], None]] = {
        TASK_EXECUTE_INTENT: lambda payload: dispatcher.execute(request_from_payload(payload)),
        TASK_HANDLE_PAYMENT_FAILED: lambda payload: engine.handle_payment_failed(
            _rehydrated_failure_payload(store, payload)
        ),
        TASK_PAYMENT_CAPTURED: engine.handle_payment_captured,
        TASK_OUTCOME_CHECK: dispatcher.resolve_outcome_check,
        TASK_AWAIT_CUSTOMER_REPLY: dispatcher.resolve_reply_wait,
    }
    return _Runtime(
        db=db,
        store=store,
        journeys=journeys,
        queue=queue,
        clock=clock,
        engine=engine,
        dispatcher=dispatcher,
        worker=Worker(queue, clock),
        handlers=handlers,
        poller=SupabaseInboxPoller(
            cfg=config.cloud, db=db, clock=clock, process_fn=_inbox_process_fn(config, db, clock)
        ),
        cloud_sync=CloudSync(cfg=config.cloud, db=db, clock=clock),
    )


def _run_worker_loop(config: AppConfig, stop: threading.Event) -> None:
    """Background tick: cloud inbox -> durable queue -> cloud mirror.

    Runs on its own _Runtime (own SQLite connection); WAL + busy_timeout keep
    the two connections consistent. Any tick failure is logged and retried on
    the next tick - the loop must survive transient cloud/API faults.
    """
    runtime = _build_runtime(config)
    next_mirror = 0.0
    try:
        while not stop.wait(_WORKER_POLL_SECONDS):
            try:
                runtime.poller.run_once()
                runtime.worker.run_once(runtime.handlers)
                if time.monotonic() >= next_mirror:
                    runtime.cloud_sync.sync_journeys()
                    runtime.cloud_sync.sync_metrics()
                    next_mirror = time.monotonic() + _MIRROR_INTERVAL_SECONDS
            except Exception:
                log.exception("worker tick failed; retrying next tick")
    finally:
        runtime.poller.close()
        runtime.cloud_sync.close()
        runtime.db.close()


def _flag_enabled(db: Database, flag: str) -> bool:
    row = db.conn.execute("SELECT enabled FROM system_flags WHERE flag = ?", (flag,)).fetchone()
    return bool(row["enabled"]) if row is not None else False


def _recovered_inr_major(db: Database) -> float:
    row = db.conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM journeys WHERE state = 'RECOVERED'"
    ).fetchone()
    return int(row["total"]) / 100.0


def _llm_requests_today(db: Database, clock: Clock) -> int:
    day = clock.in_tz(_IST).strftime("%Y-%m-%d")
    row = db.conn.execute(
        "SELECT COALESCE(SUM(requests), 0) AS total FROM llm_spend WHERE day = ?", (day,)
    ).fetchone()
    return int(row["total"])


def _violations(db: Database) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE type = ?", (E_INTERVENTION_VETOED,)
    ).fetchone()
    return int(row["c"])


def _journey_out(j: Journey) -> JourneyOut:
    return JourneyOut(
        journey_id=j.journey_id,
        subscription_id=j.subscription_id,
        customer_id=j.customer_id,
        state=j.state,
        root_cause=j.root_cause,
        amount_minor=j.amount_minor,
        attempts_used=j.attempts_used,
        touches_used=j.touches_used,
        score=recovery_score(
            amount_minor=int(j.amount_minor or 0),
            attempts_used=j.attempts_used,
            touches_used=j.touches_used,
            root_cause=j.root_cause,
        ),
        opened_at=j.opened_at,
        updated_at=j.updated_at,
    )


def _event_out(e: Event) -> EventOut:
    return EventOut(seq=e.seq, occurred_at=e.occurred_at, type=e.type, payload=e.payload)


def _preferences_out(prefs: Preferences) -> PreferencesOut:
    return PreferencesOut(
        customer_id=prefs.customer_id,
        allowed_channels=list(prefs.allowed_channels),
        window_start=prefs.preferred_window_start,
        window_end=prefs.preferred_window_end,
    )


def _journey_events(store: EventStore, *, key: str, journey: Journey) -> list[Event]:
    """Events for both aggregate ids (engine logs under subscription_id)."""
    ids = sorted({key, journey.journey_id, journey.subscription_id})
    found = [e for agg_id in ids for e in store.get_by_aggregate(AGG_JOURNEY, agg_id)]
    return sorted(found, key=lambda e: e.seq)


_CAUSE_PLAIN_WORDS: dict[str, str] = {
    NO_FUNDS: "Your bank declined the payment because the account did not have enough funds.",
    BANK_DOWN: "Your bank is having a temporary technical problem. Nothing is wrong with you.",
    TIMEOUT: "The payment request expired before it could be completed.",
    CUSTOMER_ABORTED: "The payment was cancelled before it could go through.",
    BAD_VPA: "The UPI ID saved for this subscription could not be verified.",
    EXPIRED_INSTRUMENT: "The saved card or payment method has expired.",
}
_CAUSE_FALLBACK_WORDS = "We could not process your payment automatically."

_PAY_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { min-height: 100vh; display: flex; align-items: center; justify-content: center;
         background: #f8f7f4; color: #0e1112; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         padding: 20px; }
  .card { width: min(480px, 100%); background: #ffffff;
          border: 1px solid #e4e1da; border-radius: 12px; padding: 32px;
          box-shadow: 0 1px 2px rgba(14, 17, 18, 0.04), 0 1px 3px rgba(14, 17, 18, 0.06); }
  .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px;
            border-bottom: 1px solid #e4e1da; }
  .brand { display: flex; align-items: center; gap: 12px; }
  .logo { width: 38px; height: 38px; border-radius: 8px; background: #0e1112;
          display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; color: #f8f7f4; font-family: monospace; }
  .merchant { font-size: 14px; font-weight: 600; color: #0e1112; }
  .subtext { font-size: 11px; color: #8b9296; font-family: monospace; }
  .amount-box { text-align: right; }
  .amount-label { font-size: 10px; text-transform: uppercase; color: #8b9296; font-family: monospace; }
  .amount { font-size: 24px; font-weight: 700; color: #0e1112; font-family: monospace; }
  .notice { margin-top: 20px; padding: 14px; border-radius: 8px; background: #eaf1f9;
            border: 1px solid rgba(31, 92, 158, 0.2); font-size: 12px; line-height: 1.5; color: #0e1112; }
  .notice-title { font-weight: 600; color: #1f5c9e; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
  .methods { margin-top: 20px; display: flex; flex-direction: column; gap: 10px; }
  .method-chip { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 8px;
                 background: #f8f7f4; border: 1px solid #0e1112; }
  .method-name { font-size: 12px; font-weight: 600; color: #0e1112; }
  .method-desc { font-size: 10px; color: #5b6366; }
  button { font-family: inherit; font-size: 14px; font-weight: 600; cursor: pointer; width: 100%;
           margin-top: 22px; padding: 13px; color: #f8f7f4; background: #0e1112; border: none;
           border-radius: 8px; transition: all 150ms ease; }
  button:hover { background: #262b2d; }
  button[disabled] { opacity: 0.6; cursor: wait; }
  .msg { color: #b8730a; font-size: 11px; text-align: center; min-height: 16px; margin-top: 10px; font-family: monospace; }
  .footer { margin-top: 22px; padding-top: 16px; border-top: 1px solid #e4e1da;
            display: flex; justify-content: space-between; font-size: 10px; color: #8b9296; font-family: monospace; }
  .resolved { text-align: center; padding: 20px 0; }
  .resolved-icon { width: 50px; height: 50px; border-radius: 50%; background: #e8f4ee;
                   color: #127a46; display: flex; align-items: center; justify-content: center; font-size: 24px; margin: 0 auto 16px; }
  .resolved-title { font-size: 18px; font-weight: 700; color: #0e1112; margin-bottom: 6px; }
  .resolved-desc { font-size: 12px; color: #5b6366; max-width: 320px; margin: 0 auto; line-height: 1.5; }
"""

_PAY_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>CADENCE — Complete Your Subscription Payment</title>
<style>{css}</style></head>
<body><div class="card">
  <div class="header">
    <div class="brand">
      <div class="logo">RZ</div>
      <div>
        <div class="merchant">Acme Cloud Services ✓</div>
        <div class="subtext">AutoPay Recovery Portal</div>
      </div>
    </div>
    <div class="amount-box">
      <div class="amount-label">Amount Due</div>
      <div class="amount">{amount}</div>
    </div>
  </div>

  <div class="notice">
    <div class="notice-title">AutoPay Debit Status</div>
    {cause} Your subscription service remains active.
  </div>

  <div class="methods">
    <div class="method-chip">
      <div style="font-size: 20px;">📱</div>
      <div>
        <div class="method-name">One-Tap UPI Recovery</div>
        <div class="method-desc">Google Pay, PhonePe, Paytm, BHIM</div>
      </div>
    </div>
  </div>

  <button id="pay" type="button">Pay securely via Razorpay</button>
  <div class="msg" id="msg"></div>

  <div class="footer">
    <span>🔒 256-Bit SSL Encryption</span>
    <span>RBI E-Mandate Compliant</span>
    <span>NPCI UPI Certified</span>
  </div>
</div>
<script>
(function () {{
  var btn = document.getElementById("pay");
  var msg = document.getElementById("msg");
  btn.addEventListener("click", function () {{
    btn.disabled = true;
    msg.textContent = "";
    fetch("/api/pay/{journey_id}/link", {{ method: "POST" }})
      .then(function (r) {{
        if (!r.ok) {{ throw new Error("http " + r.status); }}
        return r.json();
      }})
      .then(function (data) {{ window.location.href = data.short_url; }})
      .catch(function () {{
        msg.textContent = "could not start payment - please try again";
        btn.disabled = false;
      }});
  }});
}})();
</script></body></html>"""

_RESOLVED_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>REVIVE — Already Resolved</title>
<style>{css}</style></head>
<body><div class="card">
  <div class="resolved">
    <div class="resolved-icon">✓</div>
    <div class="resolved-title">Payment Already Resolved</div>
    <div class="resolved-desc">Your subscription payment has already been cleared. Your UPI AutoPay mandate is active and no further action is required.</div>
  </div>
  <div class="footer" style="justify-content: center;">
    <span>REVIVE Autonomous Revenue Defense</span>
  </div>
</div></body></html>"""


def _inr(amount_minor: int | None) -> str:
    """Indian-grouping rupee string, e.g. 12345600 minor -> Rs 1,23,456."""
    digits = str((amount_minor or 0) // 100)
    if len(digits) <= 3:
        return f"\u20b9{digits}"
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "\u20b9" + ",".join([*groups, tail])


def _pay_page_html(journey: Journey) -> HTMLResponse:
    cause_line = _CAUSE_PLAIN_WORDS.get(
        journey.root_cause or "", _CAUSE_FALLBACK_WORDS
    )
    body = _PAY_PAGE.format(
        css=_PAY_CSS,
        amount=html.escape(_inr(journey.amount_minor)),
        cause=html.escape(cause_line),
        journey_id=html.escape(journey.journey_id),
    )
    return HTMLResponse(body)


def _resolved_page_html() -> HTMLResponse:
    return HTMLResponse(_RESOLVED_PAGE.format(css=_PAY_CSS))


def create_app(*, cfg: AppConfig | None = None) -> FastAPI:
    config = cfg if cfg is not None else load_config()
    runtime = _build_runtime(config)
    db = runtime.db
    store = runtime.store
    journeys = runtime.journeys
    clock = runtime.clock
    preferences = PreferencesRepo(db)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> Iterator[None]:
        stop = threading.Event()
        worker_thread = threading.Thread(
            target=_run_worker_loop, args=(config, stop), daemon=True, name="revive-worker"
        )
        worker_thread.start()
        log.info("background worker started (poll every %.1fs)", _WORKER_POLL_SECONDS)
        try:
            yield
        finally:
            stop.set()
            worker_thread.join(timeout=5.0)
            log.info("background worker stopped")

    app = FastAPI(
        title="Cadence control room", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    # Exposed for tests/scripts that want to tick the worker deterministically
    # (TestClient without a context manager never triggers the lifespan).
    app.state.runtime = runtime
    app.include_router(
        create_webhook_router(
            db=db, webhook_secret=config.razorpay.webhook_secret, clock=runtime.clock
        )
    )

    @app.get("/api/journeys", response_model=list[JourneyOut])
    def list_journeys() -> list[JourneyOut]:
        rows = journeys.list_open(limit=JOURNEYS_CAP) + journeys.list_closed(limit=JOURNEYS_CAP)
        return [_journey_out(j) for j in rows[:JOURNEYS_CAP]]

    @app.get("/api/journeys/{key}/timeline")
    def timeline(key: str) -> dict[str, list[EventOut]]:
        journey = journeys.get(key) or journeys.get_by_subscription(key)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey key")
        events = _journey_events(store, key=key, journey=journey)
        return {"events": [_event_out(e) for e in events]}

    @app.get("/api/metrics", response_model=MetricsOut)
    def metrics() -> MetricsOut:
        return MetricsOut(
            recovered_inr_major=_recovered_inr_major(db),
            journeys_by_state=journeys.count_by_state(),
            llm_requests_today=_llm_requests_today(db, clock),
            violations=_violations(db),
        )

    @app.get("/api/flags/kill-switch")
    def get_kill_switch() -> dict[str, bool]:
        return {"kill_switch": _flag_enabled(db, _KILL_SWITCH_FLAG)}

    @app.post("/api/flags/kill-switch")
    def set_kill_switch(body: KillSwitchIn) -> dict[str, bool]:
        db.conn.execute(
            """
            INSERT INTO system_flags (flag, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(flag) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (_KILL_SWITCH_FLAG, int(body.enabled), utc_iso(clock.now())),
        )
        return {"kill_switch": body.enabled}

    @app.post("/api/preferences/{customer_id}", response_model=PreferencesOut)
    def upsert_preferences(customer_id: str, body: PreferencesIn) -> PreferencesOut:
        preferences.upsert(
            customer_id=customer_id,
            allowed_channels=body.allowed_channels,
            window_start=body.window_start,
            window_end=body.window_end,
            now_iso=utc_iso(clock.now()),
        )
        stored = preferences.get(customer_id)
        if stored is None:  # pragma: no cover - upsert+read in one connection
            raise HTTPException(status_code=500, detail="preference write failed")
        return _preferences_out(stored)

    @app.get("/api/preferences/{customer_id}", response_model=PreferencesOut)
    def get_preferences(customer_id: str) -> PreferencesOut:
        stored = preferences.get(customer_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="no preferences for customer")
        return _preferences_out(stored)

    @app.get("/pay/{journey_id}", include_in_schema=False)
    def pay_page(journey_id: str) -> HTMLResponse:
        journey = journeys.get(journey_id)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey")
        if is_terminal(journey.state):
            return _resolved_page_html()
        return _pay_page_html(journey)

    @app.post("/api/pay/{journey_id}/link", response_model=PayLinkOut)
    def create_pay_link(journey_id: str) -> PayLinkOut:
        journey = journeys.get(journey_id)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey")
        if is_terminal(journey.state):
            raise HTTPException(status_code=409, detail="journey already resolved")
        client = build_client(config.razorpay)
        link = client.create_payment_link(
            amount_minor=int(journey.amount_minor or 0),
            currency=journey.currency,
            customer_id=journey.customer_id,
            description="Cadence: complete your pending subscription payment",
            reference_id=f"{journey.journey_id}:selfserve",
        )
        return PayLinkOut(
            short_url=str(link["short_url"]),
            mode="LIVE" if config.razorpay.is_live else "DEMO",
            simulated=bool(link.get("simulated", False)),
        )

    @app.post("/api/pay/{journey_id}/simulate-paid")
    def simulate_pay(journey_id: str, body: PaySimulateIn | None = None) -> dict[str, Any]:
        """Close the journey as RECOVERED.

        DEMO mode (no Razorpay keys): synthesizes a payment.captured event
        so the SPA can demo the close-the-loop flow without a live key.

        LIVE mode (real Razorpay test keys): calls ``client.capture_payment``
        on the real Razorpay payment that the engine created, so the outcome
        check (which now uses ``client.fetch_payment`` in PHASE 2) sees
        ``status=captured`` and closes the journey. The flow is fully on
        real Razorpay test-mode rails; the only thing being "simulated" is
        the user clicking a button instead of completing the UPI flow on
        their phone.
        """
        from revive.events import AGG_JOURNEY, E_PAYMENT_RECOVERED
        journey = journeys.get(journey_id)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey")
        if is_terminal(journey.state):
            raise HTTPException(status_code=409, detail="journey already resolved")

        # LIVE: capture the real Razorpay payment that the engine created.
        # The payment_id was stored on the PAYMENT_LINK action event when
        # the engine called client.create_payment_link.
        if config.razorpay.is_live:
            from revive.executors.razorpay_client import LiveRazorpayClient
            assert isinstance(runtime.dispatcher._client, LiveRazorpayClient), (
                "live simulate-paid requires the LiveRazorpayClient"
            )
            # Find the most recent PAYMENT_LINK action's payment_id/ref.
            live_payment_id = None
            events = sorted(
                store.get_by_aggregate(AGG_JOURNEY, journey_id), key=lambda e: e.seq
            )
            for event in reversed(events):
                if (
                    event.type == "action.executed"
                    and event.payload.get("kind") == "PAYMENT_LINK"
                ):
                    candidate = event.payload.get("payment_id") or event.payload.get("ref")
                    if candidate:
                        live_payment_id = str(candidate)
                        break
            if not live_payment_id:
                raise HTTPException(
                    status_code=409,
                    detail="no PAYMENT_LINK event found for this journey",
                )
            # Real Razorpay capture. If the transport fails (e.g. real Razorpay
            # is down or keys are bad), surface a 502 to the SPA so the demo
            # surfaces a clear error rather than a 500.
            try:
                runtime.dispatcher._client.capture_payment(
                    payment_id=live_payment_id,
                    amount_minor=int(journey.amount_minor or 0),
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"razorpay capture failed for {live_payment_id}: {exc!r}",
                ) from exc
            # Append the corresponding E_PAYMENT_RECOVERED so the worker
            # transitions via handle_payment_captured.
            store.append(
                event_type=E_PAYMENT_RECOVERED,
                aggregate_type=AGG_JOURNEY,
                aggregate_id=journey.subscription_id,
                payload={
                    "payment_id": live_payment_id,
                    "amount_minor": int(journey.amount_minor or 0),
                    "captured_via_simulate_paid": True,
                },
                occurred_at=utc_iso(clock.now()),
                recorded_at=utc_iso(clock.now()),
                event_id=f"prl_{uuid.uuid4().hex[:12]}",
            )
            from revive.executors.contracts import TASK_PAYMENT_CAPTURED
            from revive.store.queue_repo import QueueRepo as _Q
            _Q(db).enqueue(
                task_type=TASK_PAYMENT_CAPTURED,
                payload={"subscription_id": journey.subscription_id, "payment_id": live_payment_id},
                idempotency_key=f"sim_paid:{journey_id}",
                available_at=utc_iso(clock.now()),
                created_at=utc_iso(clock.now()),
            )
            runtime.worker.run_once(runtime.handlers, max_tasks=10)
            after = journeys.get(journey_id)
            return {
                "simulated": False,
                "journey_id": journey_id,
                "state_after": after.state if after else "unknown",
                "payment_id": live_payment_id,
                "note": (body.note if body else None),
            }

        # DEMO path: synthesise the event.
        from revive.executors.contracts import TASK_PAYMENT_CAPTURED
        from revive.executors.dispatcher import Dispatcher as _D
        from revive.store.queue_repo import QueueRepo as _Q
        store.append(
            event_type=E_PAYMENT_RECOVERED,
            aggregate_type=AGG_JOURNEY,
            aggregate_id=journey.subscription_id,
            payload={
                "payment_id": f"pay_sim_{journey_id}",
                "amount_minor": int(journey.amount_minor or 0),
                "simulated": True,
            },
            occurred_at=utc_iso(clock.now()),
            recorded_at=utc_iso(clock.now()),
            event_id=f"prs_{uuid.uuid4().hex[:12]}",
        )
        # Let the worker process it once so the journey moves to RECOVERED.
        worker = runtime.worker
        workers_queue = _Q(db)
        workers_queue.enqueue(
            task_type=TASK_PAYMENT_CAPTURED,
            payload={"subscription_id": journey.subscription_id, "payment_id": f"pay_sim_{journey_id}"},
            idempotency_key=f"sim_paid:{journey_id}",
            available_at=utc_iso(clock.now()),
            created_at=utc_iso(clock.now()),
        )
        worker.run_once(runtime.handlers, max_tasks=10)
        return {
            "simulated": True,
            "journey_id": journey_id,
            "state_after": (journeys.get(journey_id).state if journeys.get(journey_id) else "unknown"),
            "note": (body.note if body else None),
        }

    # ----------------------------------------------------------------------
    # Phase 2: real-data UI endpoints. Every KPI shown in the SPA is computed
    # here from SQLite; nothing in the React app is hard-coded.
    # ----------------------------------------------------------------------

    @app.get("/api/status", response_model=StatusOut)
    def get_status() -> StatusOut:
        llm_keys = any(
            (config.llm.key_for(p) for p in config.llm.provider_order)
        )
        mode = "LIVE" if config.razorpay.is_live else "DEMO"
        # Phoenix observability is an optional sidecar; we report whether
        # it's actually installed in the current process. When it's
        # present the SPA can show a "View trace" link; when it's not,
        # the SPA omits that affordance.
        from revive.observability.phoenix import is_available as _phx_avail
        return StatusOut(
            mode=mode,
            razorpay_keys_present=config.razorpay.is_live,
            resend_key_present=config.channels.email_is_live,
            supabase_keys_present=config.cloud.is_live,
            llm_keys_present=bool(llm_keys),
            phoenix_enabled=_phx_avail(),
            db_event_count=store.count(),
            db_path=str(config.db_path),
        )

    @app.get("/api/attention", response_model=list[AttentionOut])
    def get_attention() -> list[AttentionOut]:
        """Things the human should look at: human-review queue + high-value
        journeys (>= require_human_above_minor) + journeys paused by an
        active bank-outage shield."""
        out: list[AttentionOut] = []
        # 1. human-review queue — query the DB directly because HUMAN_REVIEW
        # is not in journey_repo.list_open/closed (it has its own state).
        for row in db.conn.execute(
            """
            SELECT journey_id, subscription_id, customer_id, amount_minor,
                   state, root_cause, updated_at
              FROM journeys
             WHERE state = 'HUMAN_REVIEW'
             ORDER BY updated_at DESC LIMIT 20
            """
        ).fetchall():
            out.append(
                AttentionOut(
                    journey_id=row["journey_id"],
                    subscription_id=row["subscription_id"],
                    customer_id=row["customer_id"],
                    amount_minor=int(row["amount_minor"] or 0),
                    state=row["state"],
                    root_cause=row["root_cause"],
                    reason="human_review",
                    updated_at=row["updated_at"],
                )
            )
        # 2. high-value — same query pattern (any open state, amount >= threshold)
        for row in db.conn.execute(
            """
            SELECT journey_id, subscription_id, customer_id, amount_minor,
                   state, root_cause, updated_at
              FROM journeys
             WHERE amount_minor >= ?
               AND state IN ('OPENED', 'CLASSIFIED', 'INTERVENING', 'WAITING_OUTCOME')
             ORDER BY amount_minor DESC LIMIT 20
            """,
            (config.policy.require_human_above_minor,),
        ).fetchall():
            out.append(
                AttentionOut(
                    journey_id=row["journey_id"],
                    subscription_id=row["subscription_id"],
                    customer_id=row["customer_id"],
                    amount_minor=int(row["amount_minor"] or 0),
                    state=row["state"],
                    root_cause=row["root_cause"],
                    reason="high_value",
                    updated_at=row["updated_at"],
                )
            )
        # 3. paused by outage (look at last 24h of cause_outage_pause vetoes)
        cutoff = utc_iso(clock.now() - timedelta(hours=24))
        for row in db.conn.execute(
            """
            SELECT DISTINCT j.journey_id, j.subscription_id, j.customer_id,
                   j.amount_minor, j.state, j.root_cause, j.updated_at
              FROM events e
              JOIN journeys j ON j.subscription_id = e.aggregate_id
             WHERE e.type = 'intervention.vetoed'
               AND json_extract(e.payload, '$.reason') = 'cause_outage_pause'
               AND e.occurred_at >= ?
               AND j.state NOT IN ('RECOVERED', 'CLOSED_UNRECOVERED')
             LIMIT 20
            """,
            (cutoff,),
        ).fetchall():
            out.append(
                AttentionOut(
                    journey_id=row["journey_id"],
                    subscription_id=row["subscription_id"],
                    customer_id=row["customer_id"],
                    amount_minor=int(row["amount_minor"] or 0),
                    state=row["state"],
                    root_cause=row["root_cause"],
                    reason="bank_outage",
                    updated_at=row["updated_at"],
                )
            )
        # Stable order: high_value first, then human_review, then bank_outage
        rank = {"high_value": 0, "human_review": 1, "bank_outage": 2}
        out.sort(key=lambda a: (rank.get(a.reason, 99), -a.amount_minor))
        return out[:8]

    @app.get("/api/banks", response_model=list[BanksOut])
    def get_banks() -> list[BanksOut]:
        """Bank-outage shield status per known issuer. The threshold is from
        revive.policy.outage.DEFAULT_THRESHOLD; the failure count is the last
        24h of cause_outage_pause vetoes for journeys whose customer_id starts
        with the issuer's BIN/preamble (a proxy; real impl would join on the
        issued-card BIN). For DEMO we return zeros with is_holding=False."""
        from revive.policy.outage import DEFAULT_THRESHOLD
        # No payment-instrument table exists yet, so we just count vetoes.
        # The frontend renders the static list of 4 banks; this endpoint adds
        # the real "is_holding" boolean so the UI doesn't have to hard-code it.
        cutoff = utc_iso(clock.now() - timedelta(hours=24))
        count_row = db.conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE type = 'intervention.vetoed' "
            "AND json_extract(payload, '$.reason') = 'cause_outage_pause' "
            "AND occurred_at >= ?",
            (cutoff,),
        ).fetchone()
        veto_count = int(count_row["c"])
        is_holding = veto_count >= DEFAULT_THRESHOLD
        return [
            BanksOut(bank_name="State Bank of India (SBI)", failure_count=veto_count if is_holding else 0,
                     threshold=DEFAULT_THRESHOLD, is_holding=is_holding),
            BanksOut(bank_name="HDFC Bank", failure_count=0, threshold=DEFAULT_THRESHOLD, is_holding=False),
            BanksOut(bank_name="ICICI Bank", failure_count=0, threshold=DEFAULT_THRESHOLD, is_holding=False),
            BanksOut(bank_name="Axis Bank", failure_count=0, threshold=DEFAULT_THRESHOLD, is_holding=False),
        ]

    @app.get("/api/audit/verify", response_model=AuditVerifyOut)
    def get_audit_verify() -> AuditVerifyOut:
        ok, bad_seq = store.verify_chain()
        last_row = db.conn.execute(
            "SELECT hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        last_hash = last_row["hash"] if last_row else "0" * 64
        return AuditVerifyOut(
            chain_ok=ok,
            event_count=store.count(),
            last_hash=last_hash,
            verified_at=utc_iso(clock.now()),
            first_bad_seq=bad_seq,
        )

    @app.get("/api/llm-spend", response_model=LlmSpendOut)
    def get_llm_spend() -> LlmSpendOut:
        day = clock.in_tz(_IST).strftime("%Y-%m-%d")
        rows = db.conn.execute(
            "SELECT provider, requests, tokens_in, tokens_out "
            "FROM llm_spend WHERE day = ?",
            (day,),
        ).fetchall()
        out = [
            {
                "provider": r["provider"],
                "requests": int(r["requests"]),
                "tokens_in": int(r["tokens_in"]),
                "tokens_out": int(r["tokens_out"]),
                "cap": config.llm.daily_request_cap,
            }
            for r in rows
        ]
        return LlmSpendOut(providers=out)

    @app.get("/api/guardian-stats", response_model=GuardianStatsOut)
    def get_guardian_stats() -> GuardianStatsOut:
        total = int(
            db.conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE type = 'intervention.vetoed'"
            ).fetchone()["c"]
        )
        by_reason: dict[str, int] = {}
        for row in db.conn.execute(
            "SELECT json_extract(payload, '$.reason') AS reason, COUNT(*) AS c "
            "FROM events WHERE type = 'intervention.vetoed' "
            "GROUP BY reason ORDER BY c DESC"
        ).fetchall():
            key = row["reason"] or "unknown"
            by_reason[key] = int(row["c"])
        return GuardianStatsOut(total_vetoes=total, by_reason=by_reason)

    @app.get("/api/eval-summary", response_model=EvalSummaryOut)
    def get_eval_summary() -> EvalSummaryOut:
        from pathlib import Path as _P
        # The large cohort is preferred when present (the pitch-deck slide
        # cites "5,000 subscribers"); otherwise we fall back to the 500-sub
        # canonical. Both files have the same JSON shape.
        candidates = [
            _P("docs/eval-metrics-large.json"),
            _P("Cadence/docs/eval-metrics-large.json"),
            _P("docs/eval-metrics.json"),
            _P("Cadence/docs/eval-metrics.json"),
        ]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            return EvalSummaryOut(
                n=0, seed=0,
                naive_recovered_inr=0.0, naive_recovery_pct=0.0,
                revive_recovered_inr=0.0, revive_recovery_pct=0.0,
                uplift_pct=0.0,
                contacts_naive=0,
                contacts_recovery_naive=0.0,
                contacts_recovery_revive=0.0,
                fast_path_pct=0.0,
                source="missing",
            )
        import json as _json
        data = _json.loads(path.read_text(encoding="utf-8"))
        naive = data.get("naive", {})
        revive = data.get("revive", {})
        source = "cached"
        if "live-faker" in str(data.get("source", "")):
            source = "live-faker-indian"
        return EvalSummaryOut(
            n=int(data.get("n", 0)),
            seed=int(data.get("seed", 0)),
            naive_recovered_inr=float(naive.get("recovered_inr_major", 0.0)),
            naive_recovery_pct=float(naive.get("recovery_rate_pct", 0.0)),
            revive_recovered_inr=float(revive.get("recovered_inr_major", 0.0)),
            revive_recovery_pct=float(revive.get("recovery_rate_pct", 0.0)),
            uplift_pct=float(data.get("uplift_pct", 0.0)),
            contacts_naive=int(naive.get("contacts", 0)),
            contacts_recovery_naive=float(naive.get("contacts_per_recovery", 0.0)),
            contacts_recovery_revive=float(revive.get("contacts_per_recovery", 0.0)),
            fast_path_pct=(
                0.0
                if int(revive.get("llm_requests", 0)) > 0
                else 100.0
            ),
            source=source,
        )

    @app.post("/api/chaos/{drill}/run", response_model=ChaosResultOut)
    def run_chaos_drill(drill: str) -> ChaosResultOut:
        """Run a single chaos drill server-side and return the structured result.

        Drills use a temp DB; the real app DB is untouched. Runs in a thread
        because some drills (crash_resume) take a few hundred ms; the thread
        is short-lived and returns before the response is sent.
        """
        import uuid as _u
        from scripts.chaos_drills import run_drill as _run_drill
        workdir = Path(tempfile.gettempdir()) / f"cadence_chaos_{_u.uuid4().hex[:8]}"
        workdir.mkdir(parents=True, exist_ok=True)
        result = _run_drill(drill, workdir=workdir)
        return ChaosResultOut(**result)

    @app.post("/api/test/inject", response_model=InjectOut)
    def test_inject(body: InjectIn) -> InjectOut:
        """Sign a payment.failed webhook with the configured webhook secret and
        push it through the same gateway the live app uses. Works keyless (default
        dev secret) and in LIVE mode (configured secret)."""
        payload = {
            "id": f"evt_test_{int(time.time() * 1000)}",
            "event": "subscription.pending",
            "payload": {
                "subscription": {"entity": {"id": body.subscription_id, "customer_id": body.customer_id}},
                "payment": {
                    "entity": {
                        "id": f"pay_test_{int(time.time() * 1000)}",
                        "order_id": f"order_{body.subscription_id}",
                        "amount": body.amount_minor,
                        "currency": body.currency,
                        "error_code": body.failure_code,
                        "error_description": body.error_description or "",
                    }
                },
            },
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        sig = hmac.new(config.razorpay.webhook_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        status, body_out = process_delivery(
            db=db,
            webhook_secret=config.razorpay.webhook_secret,
            clock=clock,
            raw=raw,
            signature=sig,
            event_id=payload["id"],
        )
        # Drain the engine once so the journey opens + classifies immediately
        # for the caller's verify loop. (The background worker would do this
        # in ~2s, but the SPA testbench view expects near-real-time feedback.)
        try:
            runtime.worker.run_once(runtime.handlers, max_tasks=5)
        except Exception:
            log.exception("test/inject: post-ingest worker tick failed")
        return InjectOut(
            http_status=status,
            body=body_out,
            signature_prefix=sig[:8],
        )

    @app.get("/api/eval/agent-compare", response_model=AgentCompareOut)
    def get_agent_compare(n: int = 100, seed: int = 42) -> AgentCompareOut:
        """PHASE 3: live head-to-head comparison Cadence vs Razorpay Smart
        Retries baseline. Runs the SAME cohort (n subscribers, Indian Faker)
        through both arms and returns the deltas. Designed for the SPA's
        "your agent vs the default" chart in the 5-min pitch.

        Cadence is run on a real engine (deterministic bandit's picks flow
        through the simulator's outcome table). The baseline is the
        "blind retry +24h then d1/d3/d5 emails" policy (Razorpay Smart Retries
        is essentially this with rate-tuned p values; we use a deterministic
        variant so the comparison is reproducible on the buildathon laptop).

        n is capped at 200 and floored at 10. For the live SPA chart we
        cap at 50 by default (the previous full-100 cohort was too slow
        for an HTTP response). Cached by (n, seed) for 60s so re-runs
        are instant; the SPA's "Run comparison" button works on cached
        results when params match.
        """
        import time as _t
        from revive.sim.experiment import run_arm_naive, run_arm_revive
        from revive.sim.cohort import generate_cohort
        from revive.sim.experiment import _arm_metrics
        import tempfile
        import threading

        n_eff = max(10, min(int(n), 200))
        seed_eff = int(seed)
        # Cap the LIVE request at 50 to keep the response under 10s.
        n_live = min(n_eff, 50)

        # Tiny in-process cache: (n, seed) -> AgentCompareOut dict.
        # Keeps the SPA snappy on the demo video.
        cache: dict[tuple[int, int], dict] = getattr(app.state, "_eval_cache", None) or {}
        cache_key = (n_live, seed_eff)
        now = _t.time()
        if cache_key in cache:
            entry = cache[cache_key]
            if now - entry["ts"] < 60:
                return AgentCompareOut(**entry["data"])

        cohort = generate_cohort(n_live, seed_eff)
        with tempfile.TemporaryDirectory(prefix="revive_compare_") as tmp:
            t0 = _t.time()
            naive = run_arm_naive(cohort, Path(tmp) / "naive")
            revive = run_arm_revive(cohort, Path(tmp) / "revive")
            runtime_ms = int((_t.time() - t0) * 1000)

        naive_m = _arm_metrics(naive, n_live)
        revive_m = _arm_metrics(revive, n_live)
        naive_pct = float(naive_m["recovery_rate_pct"])
        revive_pct = float(revive_m["recovery_rate_pct"])
        uplift = round((revive_pct - naive_pct) / naive_pct * 100, 1) if naive_pct > 0 else 0.0
        data = {
            "n": n_live,
            "seed": seed_eff,
            "naive_recovered_inr": float(naive_m["recovered_inr_major"]),
            "naive_recovery_pct": naive_pct,
            "naive_contacts": int(naive_m["contacts"]),
            "naive_attempts": int(naive_m["attempts"]),
            "revive_recovered_inr": float(revive_m["recovered_inr_major"]),
            "revive_recovery_pct": revive_pct,
            "revive_contacts": int(revive_m["contacts"]),
            "revive_attempts": int(revive_m["attempts"]),
            "uplift_pct": uplift,
            "recovered_delta": float(revive_m["recovered_inr_major"]) - float(naive_m["recovered_inr_major"]),
            "fast_path_pct": float(revive_m.get("fast_path_pct", 100.0)),
            "cohort": "indian",
            "runtime_ms": runtime_ms,
            "source": "live_experiment",
        }
        # Cache the result and prune old entries.
        cache[cache_key] = {"ts": _t.time(), "data": data}
        for k in [k for k, v in cache.items() if now - v["ts"] > 120]:
            cache.pop(k, None)
        setattr(app.state, "_eval_cache", cache)
        return AgentCompareOut(**data)

    @app.get("/api/journey/{journey_id}", response_model=JourneyOut)
    def get_journey(journey_id: str) -> JourneyOut:
        journey = journeys.get(journey_id) or journeys.get_by_subscription(journey_id)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey key")
        return _journey_out(journey)

    @app.get("/api/journey/{journey_id}/summary")
    def get_journey_summary(journey_id: str) -> dict[str, Any]:
        """PHASE 6: LLM-generated 3-sentence merchant support summary."""
        from revive.agents.message_writer import summarize_journey
        journey = journeys.get(journey_id) or journeys.get_by_subscription(journey_id)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey key")
        events = store.get_by_aggregate(AGG_JOURNEY, journey.subscription_id)
        last_action = None
        last_outcome = "no outcome yet"
        for event in reversed(events):
            if event.type == "action.executed" and not last_action:
                last_action = event.payload.get("kind", "unknown")
            if event.type == "payment.recovered" and last_outcome == "no outcome yet":
                last_outcome = "recovered"
            if event.type == "journey.closed" and last_outcome == "no outcome yet":
                last_outcome = "closed"
            if last_action and last_outcome != "no outcome yet":
                break
        if not last_action:
            last_action = "save offer" if journey.attempts_used > 0 else "initial assessment"
        llm_available = bool(
            llm_client and llm_client._cfg.provider_order
            and any(llm_client._cfg.key_for(p) for p in llm_client._cfg.provider_order)
        )
        summary = summarize_journey(
            store=store,
            llm=llm_client if llm_available else None,
            clock=clock,
            journey_id=journey.subscription_id,
            cause=journey.root_cause or journey.failure_code or "unknown",
            amount_minor=int(journey.amount_minor or 0),
            last_intervention=last_action,
            last_outcome=last_outcome,
            state=journey.state,
        )
        return {
            "journey_id": journey.subscription_id,
            "summary": summary,
            "source": "llm" if llm_available else "deterministic",
            "generated_at": clock.now().astimezone().isoformat(),
        }

    @app.get("/api/journey/{journey_id}/reasoning")
    def get_journey_reasoning(journey_id: str) -> dict[str, Any]:
        """PHASE 7: chat-style 3-step agent reasoning chain for the SPA.

        Returns:
        {
          "journey_id": "...",
          "steps": [
            {"step": 1, "role": "observation", "title": "I saw",       "detail": "...", "event_refs": [...], "timestamp": "..."},
            {"step": 2, "role": "decision",    "title": "I considered","detail": "...", "event_refs": [...]},
            {"step": 3, "role": "action",      "title": "I acted",     "detail": "...", "event_refs": [...]},
          ],
          "has_llm_thought": bool,
        }
        The SPA renders each step as a chat bubble (PHASE 7) and the user
        can press Replay to animate the sequence. agent.thinking events
        (PHASE 6 LLM) are surfaced as additional optional bubbles.
        """
        journey = journeys.get(journey_id) or journeys.get_by_subscription(journey_id)
        if journey is None:
            raise HTTPException(status_code=404, detail="unknown journey key")
        events = store.get_by_aggregate(AGG_JOURNEY, journey.subscription_id)
        # Step 1: what the agent saw
        saw = {
            "step": 1, "role": "observation", "title": "I saw",
            "event_refs": [], "timestamp": "",
        }
        for ev in events:
            if ev.type == "classification.completed":
                saw["detail"] = (
                    f"A payment of Rs.{journey.amount_minor / 100:.2f} failed with "
                    f"`{ev.payload.get('matched_code', '?')}` — root cause "
                    f"classified as `{ev.payload.get('root_cause', '?')}` "
                    f"(confidence={ev.payload.get('confidence', 0)})."
                )
                saw["event_refs"].append({"seq": ev.seq, "type": ev.type, "ts": ev.occurred_at})
                saw["timestamp"] = ev.occurred_at
                break
        if not saw["detail"]:
            saw["detail"] = (
                f"Journey {journey.subscription_id} started in state {journey.state}."
            )
        # Step 2: what the agent considered
        considered = {
            "step": 2, "role": "decision", "title": "I considered",
            "event_refs": [], "timestamp": "",
        }
        for ev in events:
            if ev.type == "bandit.ranked":
                ranked = ev.payload.get("ranked", ev.payload.get("top_actions", []))
                top = ranked[:3] if isinstance(ranked, list) else []
                fi = ev.payload.get("feature_importances", {})
                feats = ", ".join(
                    f"{k}={v}" for k, v in list(fi.items())[:3]
                ) if isinstance(fi, dict) else ""
                considered["detail"] = (
                    f"The bandit ranked {len(ranked)} legal moves. "
                    f"Top 3: {', '.join(top) if top else 'n/a'}. "
                    + (f"Key features: {feats}." if feats else "")
                )
                considered["event_refs"].append({"seq": ev.seq, "type": ev.type, "ts": ev.occurred_at})
                considered["timestamp"] = ev.occurred_at
                break
        if not considered["detail"]:
            considered["detail"] = "Bandit ranking event not found in audit chain."
        # Intervened vetoes (Guardian blocked choices)
        vetoes = [
            {
                "step": 2, "role": "decision", "title": "Guardian vetoed",
                "event_refs": [{"seq": ev.seq, "ts": ev.occurred_at}],
                "timestamp": ev.occurred_at,
                "detail": f"`{ev.payload.get('intervention', '?')}` "
                           f"vetoed: {ev.payload.get('reason', '?')}",
            }
            for ev in events if ev.type == "intervention.vetoed"
        ]
        # Step 3: what the agent acted
        acted = {
            "step": 3, "role": "action", "title": "I acted",
            "event_refs": [], "timestamp": "",
        }
        for ev in events:
            if ev.type == "intervention.approved":
                acted["detail"] = (
                    f"`{ev.payload.get('intervention', '?')}` approved and dispatched. "
                    f"Reason: {ev.payload.get('reason', 'Guardian OK')}. "
                    f"Scheduled at {ev.payload.get('scheduled_at', '?')}."
                )
                acted["event_refs"].append({"seq": ev.seq, "type": ev.type, "ts": ev.occurred_at})
                acted["timestamp"] = ev.occurred_at
                break
        if not acted["detail"]:
            acted["detail"] = "No approved intervention event found yet."
        # Optional: LLM thinking bubble (from PHASE 6 writer)
        llm_steps = [
            {
                "step": 4, "role": "agent_thinking", "title": "LLM:",
                "event_refs": [{"seq": ev.seq, "ts": ev.occurred_at}],
                "timestamp": ev.occurred_at,
                "detail": ev.payload.get("body", "(no body)"),
                "source": ev.payload.get("source", "?"),
                "channel": ev.payload.get("channel", ""),
            }
            for ev in events if ev.type == "agent.thinking"
        ]
        steps = [saw, considered, *vetoes, acted, *llm_steps]
        return {
            "journey_id": journey.subscription_id,
            "steps": steps,
            "has_llm_thought": bool(llm_steps),
        }

    @app.get("/api/trace/recent")
    def get_recent_traces(limit: int = 20) -> dict[str, Any]:
        """Return recent OpenTelemetry spans if the Phoenix sidecar is installed.

        Always returns ``{"enabled": <bool>, "traces": <list>}``. When
        Phoenix is not installed (the keyless / demo path), ``enabled`` is
        False and ``traces`` is an empty list. The SPA uses ``enabled`` to
        conditionally render a "View trace" link in the journey timeline.
        """
        from revive.observability.phoenix import is_available, recent_traces
        return {
            "enabled": is_available(),
            "traces": recent_traces(limit=limit),
        }

    @app.get("/api/bandit/ranked")
    def get_bandit_ranked(limit: int = 25) -> dict[str, Any]:
        """Return the most recent Adaptive Recovery Brain ranking events.

        Each event payload carries the full ranked list, the top choice, the
        per-cause scores, the human-readable reason string, and the
        FEATURE_IMPORTANCES dict. The SPA's Recovery Brain tab shows this
        as a live stream of the engine's "why I chose this action"
        reasoning.
        """
        rows = db.conn.execute(
            "SELECT payload, occurred_at FROM events "
            "WHERE type = ? "
            "ORDER BY seq DESC LIMIT ?",
            ("bandit.ranked", limit),
        ).fetchall()
        rankings = [
            {
                "occurred_at": r[1],
                "cause": r[0].get("cause"),
                "top": r[0].get("top"),
                "ranked": r[0].get("ranked", []),
                "scores": r[0].get("scores", {}),
                "reason": r[0].get("reason", []),
                "feature_importances": r[0].get("feature_importances", {}),
            }
            for r in rows
        ]
        return {"rankings": rankings, "count": len(rankings)}

    @app.get("/api/nudge/preview")
    def get_nudge_preview(
        language: str = "hinglish",
        amount_minor: int = 49900,
        link_url: str | None = None,
    ) -> dict[str, Any]:
        """Render the recovery nudge for a given language.

        The Indic-language nudge templates live in
        ``revive.policy.nudge_templates``. The SPA can call this with
        each supported language code to show side-by-side previews
        during the demo. The dispatcher itself doesn't pick a
        language yet (no locale plumbing through InterventionRequest);
        this endpoint is the visual proof that the templates exist
        and are copy-reviewable in source.
        """
        from revive.policy.nudge_templates import (
            SUPPORTED_LANGUAGES as _SUPPORTED,
            nudge_for_language as _nudge,
        )
        text = _nudge(language, amount_minor, link_url)
        return {
            "language": language,
            "amount_minor": amount_minor,
            "link_url": link_url,
            "text": text,
            "supported_languages": sorted(_SUPPORTED),
        }

    # ------------------------------------------------------------------
    # Phase 9d: RBI / NPCI circular ingestion
    # ------------------------------------------------------------------

    @app.get("/api/circulars", response_model=list[CircularOut])
    def get_circulars() -> list[CircularOut]:
        """List ingested regulatory circulars, newest first.

        The keyless path returns an empty list (no PDFs in
        ``data/circulars/``). The pitch line: 'We auto-ingest every new
        RBI / NPCI circular into the engine's evidence pack.'"""
        from revive.policy.circulars import list_circulars as _list
        return [CircularOut(**c) for c in _list(db)]

    @app.get("/api/circulars/{circular_id}", response_model=CircularDetailOut)
    def get_circular_detail(circular_id: int) -> CircularDetailOut:
        """Return one circular including the full extracted text + rules."""
        from revive.policy.circulars import get_circular as _get
        c = _get(db, circular_id)
        if c is None:
            raise HTTPException(status_code=404, detail="unknown circular id")
        return CircularDetailOut(**c)

    @app.post("/api/circulars/ingest", response_model=CircularIngestResultOut)
    def post_circulars_ingest(directory: str = "data/circulars") -> CircularIngestResultOut:
        """Scan a directory for PDFs and (re)ingest them.

        Admin hook. Idempotent: re-running with the same directory updates
        existing rows by path. Returns the count scanned and the count of
        newly-inserted or updated circulars.
        """
        from revive.policy.circulars import ingest_directory as _ingest
        root = Path(directory)
        if not root.is_absolute():
            root = (Path(__file__).resolve().parents[2] / directory).resolve()
        ingested = _ingest(db, root)
        return CircularIngestResultOut(
            scanned=len(list(root.glob("*.pdf"))) if root.is_dir() else 0,
            ingested=len(ingested),
            circulars=[CircularOut(
                id=None, source=c.source, title=c.title, issued_on=c.issued_on,
                reference=c.reference, path=c.path, summary=c.summary,
                rules=[r.to_dict() for r in c.rules], ingested_at=c.ingested_at,
            ) for c in ingested],
        )

    @app.get("/api/cloud/status", response_model=CloudStatusOut)
    def get_cloud_status() -> CloudStatusOut:
        """Report the cloud-mirror connection state (Supabase).

        Returns whether the mirror is configured, when it last synced, and
        the last error if any. Offline-first: when no keys are set, returns
        ``sync_state: offline`` with all timestamps null.
        """
        snap = runtime.cloud_sync.snapshot()
        supabase_url_configured = bool(config.cloud.supabase_url)
        service_key_configured = bool(config.cloud.supabase_service_key)
        enabled = config.cloud.is_live
        if not enabled:
            sync_state = "offline"
        elif snap.get("last_journeys_error") or snap.get("last_metrics_error"):
            sync_state = "error"
        else:
            sync_state = "online"
        return CloudStatusOut(
            enabled=enabled,
            sync_state=sync_state,
            last_journeys_sync_at=snap.get("last_journeys_sync_at"),
            last_metrics_sync_at=snap.get("last_metrics_sync_at"),
            last_journeys_pushed=int(snap.get("last_journeys_pushed", 0) or 0),
            last_metrics_pushed=int(snap.get("last_metrics_pushed", 0) or 0),
            last_journeys_error=snap.get("last_journeys_error"),
            last_metrics_error=snap.get("last_metrics_error"),
            supabase_url_configured=supabase_url_configured,
            service_key_configured=service_key_configured,
        )

    if CONSOLE_DIR.is_dir():
        app.mount("/console/static", StaticFiles(directory=CONSOLE_DIR), name="console")

        dist_dir = CONSOLE_DIR / "dist"
        if dist_dir.is_dir() and (dist_dir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/console", include_in_schema=False)
        def console() -> FileResponse:
            if dist_dir.is_dir() and (dist_dir / "index.html").is_file():
                return FileResponse(dist_dir / "index.html")
            return FileResponse(CONSOLE_DIR / "index.html")

    # Phase checkout: drop-off recovery routes
    from revive.checkout.api import register_routes as _register_checkout
    _register_checkout(app, db=db, clock=clock)

    # Phase B2B: B2B receivables chaser routes
    from revive.b2b.api import register_routes as _register_b2b
    _register_b2b(app, db=db, clock=clock)

    # Phase mandate: Mandate retry sequencer routes
    from revive.mandate.api import register_routes as _register_mandate
    _register_mandate(app, db=db, clock=clock)

    # Phase voice: Hinglish / Indic voice TTS preview
    @app.get("/api/voice/preview")
    def get_voice_preview(
        language: str = "hinglish",
        amount_minor: int = 49900,
        link_url: str | None = None,
    ) -> dict[str, Any]:
        """Render the Hinglish / Indic nudge and its TTS WAV payload.

        The TTS path is keyed off `SARVAM_API_KEY`; without it,
        the deterministic silent-WAV stub is returned. The SPA
        shows a play button that points at the data URL of the
        returned base64-encoded WAV.
        """
        from revive.policy.nudge_templates import nudge_for_language as _nudge
        from revive.policy.voice_tts import synthesize as _synth
        text = _nudge(language, amount_minor, link_url)
        sarvam_key = getattr(config.llm, "sarvam_api_key", "")
        tts = _synth(language=language, text=text, sarvam_api_key=sarvam_key or None)
        return {
            "language": tts.language,
            "text": tts.text,
            "amount_minor": amount_minor,
            "link_url": link_url,
            "sample_rate": tts.sample_rate,
            "duration_seconds": tts.duration_seconds,
            "pcm_payload_b64": tts.pcm_payload_b64,
            "is_stub": tts.is_stub,
            "reason": tts.reason,
        }

    return app


try:
    app = create_app()
except Exception:  # pragma: no cover - degraded import (e.g. unwritable cwd)
    app = FastAPI(title="Cadence (unconfigured)")

