"""Mandate sequencer API endpoints.

Endpoints:
- POST /api/mandate/failed      — record a mandate failure + run sequencer
- GET  /api/mandate/sequenced   — list recent sequencer decisions
- GET  /api/mandate/state/{id}  — read the current mandate state
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from revive.clock import Clock
from revive.mandate.sequencer import (
    ACTION_STOP_AND_HUMAN_REVIEW,
    MandateFailure,
    MandateState,
    decide,
)
from revive.store.db import Database

# JSON file for tracking the most recent sequencer decisions.
# Lives next to the eval metrics so the SPA can poll it cheaply.
_DATA_FILE = Path("docs/mandate_sequencer_log.jsonl")


class MandateFailureIn(BaseModel):
    subscription_id: str
    customer_id: str
    mandate_id: str
    cause: str
    occurred_at: str | None = None
    mandate_status: str = "active"
    paused_at: str | None = None
    recent_failures: list[dict[str, str]] = Field(default_factory=list)


class SequencerOut(BaseModel):
    mandate_id: str
    action: str
    schedule_after_seconds: int
    reason: str
    ran_at: str


def _short_id(seed: str) -> str:
    return f"ms_{hashlib.sha1(seed.encode()).hexdigest()[:10]}"


def _ensure_data_file() -> Path:
    p = _DATA_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("", encoding="utf-8")
    return p


def register_routes(app: FastAPI, *, db: Database, clock: Clock) -> None:
    events = _ensure_event_store(db)

    @app.post("/api/mandate/failed", response_model=SequencerOut)
    def post_mandate_failed(req: MandateFailureIn) -> SequencerOut:
        now = clock.now().astimezone(UTC)
        occurred_at_iso = req.occurred_at or now.isoformat()
        # Build the MandateState from the request.
        recent = tuple(
            MandateFailure(
                cause=f["cause"],
                occurred_at=_parse_iso(f["occurred_at"]),
            )
            for f in req.recent_failures
        )
        state = MandateState(
            id=req.mandate_id,
            customer_id=req.customer_id,
            status=req.mandate_status,
            paused_at=_parse_iso(req.paused_at) if req.paused_at else None,
            recent_failures=recent,
        )
        d = decide(state, now=now, cause=req.cause)
        # Persist a hash-chained audit event.
        try:
            events.append(
                aggregate_type="mandate",
                aggregate_id=req.mandate_id,
                event_type="mandate.sequenced",
                payload={
                    "customer_id": req.customer_id,
                    "subscription_id": req.subscription_id,
                    "cause": req.cause,
                    "action": d.action,
                    "schedule_after_seconds": int(d.schedule_after.total_seconds()),
                    "reason": d.reason,
                    "recent_failures_count": len(recent),
                },
                occurred_at=now.isoformat(),
                recorded_at=now.isoformat(),
                event_id=str(uuid.uuid4()),
            )
        except Exception:
            pass
        # Append a one-line JSON record to the rolling log so the
        # SPA can poll /api/mandate/sequenced cheaply.
        record = {
            "mandate_id": req.mandate_id,
            "customer_id": req.customer_id,
            "subscription_id": req.subscription_id,
            "cause": req.cause,
            "action": d.action,
            "schedule_after_seconds": int(d.schedule_after.total_seconds()),
            "reason": d.reason,
            "ran_at": now.isoformat(),
        }
        p = _ensure_data_file()
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return SequencerOut(
            mandate_id=req.mandate_id,
            action=d.action,
            schedule_after_seconds=int(d.schedule_after.total_seconds()),
            reason=d.reason,
            ran_at=now.isoformat(),
        )

    @app.get("/api/mandate/sequenced", response_model=list[SequencerOut])
    def get_sequenced(limit: int = Query(25, ge=1, le=200)) -> list[SequencerOut]:
        p = _ensure_data_file()
        lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
        return [
            SequencerOut(
                mandate_id=json.loads(line)["mandate_id"],
                action=json.loads(line)["action"],
                schedule_after_seconds=json.loads(line)["schedule_after_seconds"],
                reason=json.loads(line)["reason"],
                ran_at=json.loads(line)["ran_at"],
            )
            for line in lines
            if line.strip()
        ]

    @app.get("/api/mandate/sequenced/summary")
    def get_sequenced_summary() -> dict[str, Any]:
        p = _ensure_data_file()
        lines = p.read_text(encoding="utf-8").splitlines()
        counts: dict[str, int] = {}
        for line in lines[-200:]:
            if not line.strip():
                continue
            d = json.loads(line)
            action = d.get("action", "unknown")
            counts[action] = counts.get(action, 0) + 1
        return {"counts": counts, "total": len(lines)}


def _ensure_event_store(db: Database):
    from revive.store.event_store import EventStore
    return EventStore(db)


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


__all__ = ["MandateFailureIn", "SequencerOut", "register_routes"]
