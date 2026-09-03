"""Cadence MCP (Model Context Protocol) server.

Exposes a read-only view of Cadence recovery operations to any MCP-compatible
AI agent client (Claude Desktop, Cursor, VS Code, OpenAI Agents SDK).

Built on the official `mcp` Python SDK v1.x (the same SDK that powers the
Razorpay MCP server, Stripe MCP server, and the Anthropic quickstart).

Governance: every tool is READ-ONLY by design. Agents observe recovery
operations; they never operate money. This module has no write path - no tool
can mutate a journey, spend budget, retry a debit, or flip a flag.

Tools (8 total):
    - cadence_list_journeys: paginated list of recovery journeys
    - cadence_get_timeline: hash-chained event timeline for one journey
    - cadence_get_metrics: control-room totals (recovered INR, state counts, etc.)
    - cadence_list_dead_letters: tasks that exhausted retries
    - cadence_get_status: DEMO/LIVE mode + which keys are present
    - cadence_get_attention: journeys flagged for human review / high value
    - cadence_audit_verify: hash-chain integrity check (chain_ok + last hash)
    - cadence_get_guardian_stats: veto counts grouped by reason

Run from Cadence/:  python scripts/run_mcp.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from cadence.clock import SystemClock
from cadence.events import AGG_JOURNEY, E_INTERVENTION_VETOED
from cadence.logging_setup import get_logger
from cadence.store.db import Database
from cadence.store.event_store import EventStore
from cadence.store.journey_repo import JourneyRepo, journey_to_dict
from cadence.store.queue_repo import QueueRepo

_IST = "Asia/Kolkata"
_log = get_logger(__name__)

SERVER_NAME = "cadence-mcp"
SERVER_VERSION = "0.2.0"


# ---------------------------------------------------------------------------
# A single FastMCP instance is module-level so the canonical MCP tool list
# (used by `mcp list-tools`, Claude Desktop discovery, etc.) reflects the
# tools declared below at import time.
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name=SERVER_NAME,
    instructions=(
        "Cadence is an autonomous revenue-recovery system for Indian "
        "Razorpay subscriptions. It is READ-ONLY: you can inspect recovery "
        "journeys, timelines, metrics, the audit hash chain, and the "
        "Policy Guardian's veto stats. You cannot mutate state, spend budget, "
        "or retry a debit. Use these tools to answer questions about the "
        "state of the recovery loop; do not attempt write operations."
    ),
)


# ---------------------------------------------------------------------------
# Tool implementations. The closure captures the Database so the server
# reads from the same SQLite file the FastAPI app uses.
# ---------------------------------------------------------------------------

_db_ref: dict[str, Database] = {}


def _set_db(db: Database) -> None:
    """Inject the live database. Called by scripts/run_mcp.py on startup."""
    _db_ref["db"] = db


def _store() -> EventStore:
    return EventStore(_db_ref["db"])


def _journeys() -> JourneyRepo:
    return JourneyRepo(_db_ref["db"])


def _queue() -> QueueRepo:
    return QueueRepo(_db_ref["db"])


def _clock() -> SystemClock:
    return SystemClock()


def _clamp_limit(arguments: dict[str, Any], default: int) -> int:
    return max(1, min(int(arguments.get("limit", default)), 200))


# ---------------------------------------------------------------------------
# 8 read-only tools. The `@mcp.tool()` decorator publishes each function to the
# MCP protocol with auto-generated JSON Schema from the type hints.
# ---------------------------------------------------------------------------


@mcp.tool()
def cadence_list_journeys(limit: int = 50) -> list[dict[str, Any]]:
    """List recovery journeys (open first, then closed), newest activity first.

    Args:
        limit: Maximum number of journeys to return (1-200, default 50).
    """
    limit = _clamp_limit({"limit": limit}, default=50)
    rows = _journeys().list_open(limit=limit) + _journeys().list_closed(limit=limit)
    return [journey_to_dict(j) for j in rows[:limit]]


@mcp.tool()
def cadence_get_timeline(journey_key: str) -> dict[str, Any]:
    """Return the hash-chained event timeline for one journey.

    The key can be either the journey_id (e.g. j_abc123) or the
    subscription_id (e.g. sub_demo). Events are returned in seq order.
    """
    journey = _journeys().get(journey_key) or _journeys().get_by_subscription(journey_key)
    if journey is None:
        return {"error": f"unknown journey key: {journey_key}"}
    ids = sorted({journey_key, journey.journey_id, journey.subscription_id})
    found = [e for agg_id in ids for e in _store().get_by_aggregate(AGG_JOURNEY, agg_id)]
    return {
        "journey_id": journey.journey_id,
        "subscription_id": journey.subscription_id,
        "events": [
            {"seq": e.seq, "occurred_at": e.occurred_at, "type": e.type, "payload": e.payload}
            for e in sorted(found, key=lambda e: e.seq)
        ],
    }


@mcp.tool()
def cadence_get_metrics() -> dict[str, Any]:
    """Return control-room totals: recovered INR, journeys by state, LLM
    requests today, and Guardian veto count.
    """
    db = _db_ref["db"]
    recovered = db.conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM journeys WHERE state='RECOVERED'"
    ).fetchone()
    day = _clock().in_tz(_IST).strftime("%Y-%m-%d")
    llm = db.conn.execute(
        "SELECT COALESCE(SUM(requests), 0) AS total FROM llm_spend WHERE day = ?", (day,)
    ).fetchone()
    vetoes = db.conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE type = ?", (E_INTERVENTION_VETOED,)
    ).fetchone()
    return {
        "recovered_inr_major": int(recovered["total"]) / 100.0,
        "journeys_by_state": _journeys().count_by_state(),
        "llm_requests_today": int(llm["total"]),
        "violations": int(vetoes["c"]),
    }


@mcp.tool()
def cadence_list_dead_letters(limit: int = 20) -> list[dict[str, Any]]:
    """List queue tasks that exhausted retries (the dead-letter queue)."""
    limit = _clamp_limit({"limit": limit}, default=20)
    return [
        {
            "task_id": t.task_id,
            "task_type": t.task_type,
            "payload": t.payload,
            "attempts": t.attempts,
            "max_attempts": t.max_attempts,
            "available_at": t.available_at,
        }
        for t in _queue().dead_letters(limit=limit)
    ]


@mcp.tool()
def cadence_get_status() -> dict[str, Any]:
    """Return the current DEMO/LIVE mode and which integration keys are present.

    DEMO = no real keys configured; every external dependency uses a
    deterministic simulator. LIVE = at least one key is set and the live
    code path is active for that dependency.

    D1: the test environment can pass an explicit empty env (so dotenv
    is suppressed and the .env file is not consulted). Production code
    continues to call load_config() which reads os.environ + the
    project-root .env.
    """
    from cadence.config import load_config
    cfg = load_config()
    llm_keys = any(cfg.llm.key_for(p) for p in cfg.llm.provider_order)
    return {
        "mode": "LIVE" if cfg.razorpay.is_live else "DEMO",
        "razorpay_keys_present": cfg.razorpay.is_live,
        "resend_key_present": cfg.channels.email_is_live,
        "supabase_keys_present": cfg.cloud.is_live,
        "llm_keys_present": bool(llm_keys),
        "db_event_count": _store().count(),
    }


def _demo_status_from_db(db_event_count: int) -> dict[str, Any]:
    """D1: the DEMO-mode status shape, with every key flag forced to
    False. The MCP server tool can be exercised under an empty env
    without needing a real .env.
    """
    return {
        "mode": "DEMO",
        "razorpay_keys_present": False,
        "resend_key_present": False,
        "supabase_keys_present": False,
        "llm_keys_present": False,
        "db_event_count": db_event_count,
    }


@mcp.tool()
def cadence_get_attention(limit: int = 8) -> list[dict[str, Any]]:
    """Return journeys flagged for human review or statutory policy hold.

    Reasons: 'human_review' (state == HUMAN_REVIEW), 'high_value' (amount
    >= require_human_above_minor, currently 50,000 INR), 'bank_outage'
    (paused by an active outage shield in the last 24h).
    """
    from cadence.config import load_config

    cfg = load_config()
    db = _db_ref["db"]
    out: list[dict[str, Any]] = []
    # 1. human-review queue
    for row in db.conn.execute(
        "SELECT journey_id, subscription_id, customer_id, amount_minor, "
        "state, root_cause, updated_at FROM journeys "
        "WHERE state = 'HUMAN_REVIEW' ORDER BY updated_at DESC LIMIT 20"
    ).fetchall():
        out.append({
            "journey_id": row["journey_id"],
            "subscription_id": row["subscription_id"],
            "customer_id": row["customer_id"],
            "amount_minor": int(row["amount_minor"] or 0),
            "state": row["state"],
            "root_cause": row["root_cause"],
            "reason": "human_review",
            "updated_at": row["updated_at"],
        })
    # 2. high-value
    for row in db.conn.execute(
        "SELECT journey_id, subscription_id, customer_id, amount_minor, "
        "state, root_cause, updated_at FROM journeys "
        "WHERE amount_minor >= ? AND state IN ('OPENED', 'CLASSIFIED', 'INTERVENING', 'WAITING_OUTCOME') "
        "ORDER BY amount_minor DESC LIMIT 20",
        (cfg.policy.require_human_above_minor,),
    ).fetchall():
        out.append({
            "journey_id": row["journey_id"],
            "subscription_id": row["subscription_id"],
            "customer_id": row["customer_id"],
            "amount_minor": int(row["amount_minor"] or 0),
            "state": row["state"],
            "root_cause": row["root_cause"],
            "reason": "high_value",
            "updated_at": row["updated_at"],
        })
    # 3. paused by outage (last 24h of cause_outage_pause vetoes)
    from datetime import datetime, timedelta, UTC
    cutoff = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cutoff_dt = datetime.now(UTC) - timedelta(hours=24)
    cutoff = cutoff_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for row in db.conn.execute(
        "SELECT DISTINCT j.journey_id, j.subscription_id, j.customer_id, "
        "j.amount_minor, j.state, j.root_cause, j.updated_at "
        "FROM events e JOIN journeys j ON j.subscription_id = e.aggregate_id "
        "WHERE e.type = 'intervention.vetoed' "
        "AND json_extract(e.payload, '$.reason') = 'cause_outage_pause' "
        "AND e.occurred_at >= ? AND j.state NOT IN ('RECOVERED', 'CLOSED_UNRECOVERED') "
        "LIMIT 20",
        (cutoff,),
    ).fetchall():
        out.append({
            "journey_id": row["journey_id"],
            "subscription_id": row["subscription_id"],
            "customer_id": row["customer_id"],
            "amount_minor": int(row["amount_minor"] or 0),
            "state": row["state"],
            "root_cause": row["root_cause"],
            "reason": "bank_outage",
            "updated_at": row["updated_at"],
        })
    rank = {"high_value": 0, "human_review": 1, "bank_outage": 2}
    out.sort(key=lambda a: (rank.get(a["reason"], 99), -a["amount_minor"]))
    return out[:limit]


@mcp.tool()
def cadence_audit_verify() -> dict[str, Any]:
    """Verify the audit hash chain and return the last hash.

    Returns chain_ok: true when every event's hash recomputes from the prior
    hash plus canonical event fields. first_bad_seq is the seq of the first
    tamper when chain_ok is false.
    """
    store = _store()
    ok, bad_seq = store.verify_chain()
    last_row = _db_ref["db"].conn.execute(
        "SELECT hash FROM events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    last_hash = last_row["hash"] if last_row else "0" * 64
    return {
        "chain_ok": ok,
        "event_count": store.count(),
        "last_hash": last_hash,
        "first_bad_seq": bad_seq,
    }


@mcp.tool()
def cadence_get_guardian_stats() -> dict[str, Any]:
    """Aggregate Guardian vetoes grouped by reason.

    Reasons include: touch_cap_reached, window_expired, attempts_exhausted,
    hard_decline_stop, illegal_intervention, kill_switch, quiet_hours_deferred,
    cause_outage_pause, finance_approval_required, manager_approval_required.
    """
    db = _db_ref["db"]
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
        by_reason[str(row["reason"])] = int(row["c"])
    return {"total_vetoes": total, "by_reason": by_reason}


# ---------------------------------------------------------------------------
# Public entry points. scripts/run_mcp.py calls serve(db) which sets the
# database reference and runs the FastMCP stdio transport.
# ---------------------------------------------------------------------------

def serve(db: Database) -> None:
    """Wire the database and run the FastMCP stdio transport until EOF.

    Suitable for `mcp` config blocks in Claude Desktop / Cursor / VS Code.
    Logs go to stderr (the FastMCP SDK handles this correctly - stdout is
    reserved for the JSON-RPC protocol).
    """
    _set_db(db)
    _log.info("cadence-mcp v%s serving on stdio (8 read-only tools)", SERVER_VERSION)
    mcp.run()


__all__ = ["mcp", "serve", "SERVER_NAME", "SERVER_VERSION"]

