"""One-way projections to the Supabase Postgres mirror (Phase 4).

Local SQLite stays the source of truth; these upserts only feed dashboards
(`journeys_mirror`, `metrics_daily`) via PostgREST with the service key.
Never f-string user data into SQL - local reads are parameterized, and cloud
writes go through httpx's json= encoder. Offline-first: not live => 0.

The schema for the three mirrored tables lives in `Cadence/supabase/schema.sql`
(run once in Supabase Studio -> SQL Editor).

Design choices documented in `Cadence/docs/cloud-mirror.md`:
  - Supabase kept over Turso / Neon / D1 because the read-side ergonomics
    (PostgREST, Supabase Dashboard) match standard cloud dashboard expectations.
  - Mirror is one-way: SQLite -> Supabase. No sync the other direction.
  - Schema is RLS-deny-all-by-default; only the service_role bypasses. The
    mirror endpoint is server-side only.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx

from cadence.clock import Clock
from cadence.config import CloudConfig
from cadence.events import E_INTERVENTION_VETOED
from cadence.logging_setup import get_logger
from cadence.store.db import Database
from cadence.store.journey_repo import STATE_RECOVERED

log = get_logger("cadence.cloud.sync")

_TIMEOUT_SECONDS = 15.0


class CloudSync:
    """Upserts local projections to Supabase; no-ops when not configured live."""

    def __init__(
        self,
        cfg: CloudConfig,
        db: Database,
        clock: Clock,
        transport: httpx.Client | None = None,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._clock = clock
        self._transport: Any = transport
        self._owned: httpx.Client | None = None
        # Sync state for /api/cloud/status. Mutex so the worker thread and
        # the FastAPI request thread don't race.
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "last_journeys_sync_at": None,    # ISO 8601 UTC string or None
            "last_metrics_sync_at": None,
            "last_journeys_pushed": 0,        # int, count of rows pushed
            "last_metrics_pushed": 0,
            "last_journeys_error": None,       # error string or None
            "last_metrics_error": None,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the current sync state for /api/cloud/status."""
        with self._lock:
            return dict(self._state)

    def sync_journeys(self, limit: int = 100) -> int:
        """Mirror the newest journeys; returns the row count pushed (0 offline/error)."""
        if not self._cfg.is_live:
            return 0
        rows = self._db.conn.execute(
            "SELECT * FROM journeys ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        payload = [self._journey_row(row) for row in rows]
        if not payload:
            with self._lock:
                self._state["last_journeys_sync_at"] = self._clock.now().astimezone().isoformat()
                self._state["last_journeys_pushed"] = 0
                self._state["last_journeys_error"] = None
            return 0
        ok = self._post("journeys_mirror", payload)
        with self._lock:
            self._state["last_journeys_sync_at"] = self._clock.now().astimezone().isoformat()
            if ok:
                self._state["last_journeys_pushed"] = len(payload)
                self._state["last_journeys_error"] = None
            else:
                self._state["last_journeys_pushed"] = 0
                self._state["last_journeys_error"] = "supabase upsert failed (see api.err)"
        return len(payload) if ok else 0

    def sync_metrics(self, day: str | None = None) -> int:
        """Aggregate local tables for ``day`` (default: today) and upsert metrics_daily."""
        if not self._cfg.is_live:
            return 0
        target_day = day if day is not None else self._clock.now().date().isoformat()
        stats = self._aggregate(target_day)
        ok = self._post("metrics_daily", [stats])
        with self._lock:
            self._state["last_metrics_sync_at"] = self._clock.now().astimezone().isoformat()
            if ok:
                self._state["last_metrics_pushed"] = 1
                self._state["last_metrics_error"] = None
            else:
                self._state["last_metrics_pushed"] = 0
                self._state["last_metrics_error"] = "supabase upsert failed (see api.err)"
        return 1 if ok else 0

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()

    @staticmethod
    def _journey_row(row: Any) -> dict[str, Any]:
        return {
            "journey_id": row["journey_id"],
            "subscription_id": row["subscription_id"],
            "customer_id": row["customer_id"],
            "state": row["state"],
            "root_cause": row["root_cause"],
            "classify_source": row["classify_source"],
            "amount_minor": row["amount_minor"],
            "attempts_used": row["attempts_used"],
            "touches_used": row["touches_used"],
            "opened_at": row["opened_at"],
            "updated_at": row["updated_at"],
        }

    def _aggregate(self, day: str) -> dict[str, Any]:
        conn = self._db.conn
        opened = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM journeys WHERE date(opened_at) = ?", (day,)
            ).fetchone()["c"]
        )
        recovered_row = conn.execute(
            """
            SELECT COUNT(*) AS c, COALESCE(SUM(amount_minor), 0) AS total
            FROM journeys WHERE state = ? AND date(closed_at) = ?
            """,
            (STATE_RECOVERED, day),
        ).fetchone()
        violations = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE type = ? AND date(occurred_at) = ?",
                (E_INTERVENTION_VETOED, day),
            ).fetchone()["c"]
        )
        return {
            "day": day,
            "journeys_opened": opened,
            "recovered_count": int(recovered_row["c"]),
            "recovered_inr_major": int(recovered_row["total"]) / 100.0,
            "violations": violations,
        }

    def _post(self, table: str, payload: list[dict[str, Any]]) -> bool:
        url = f"{self._cfg.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self._cfg.supabase_service_key,
            "Authorization": f"Bearer {self._cfg.supabase_service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        try:
            resp = self._request("POST", url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            log.error("mirror upsert to %s failed: %s", table, exc)
            return False
        if not resp.is_success:
            log.error("mirror upsert to %s returned HTTP %d", table, resp.status_code)
            return False
        return True

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Route through an injected transport/client, else an owned client."""
        if self._transport is not None:
            if isinstance(self._transport, httpx.Client):
                return self._transport.request(method, url, **kwargs)
            request = httpx.Request(
                method,
                url,
                params=kwargs.get("params"),
                headers=kwargs.get("headers"),
                json=kwargs.get("json"),
            )
            return self._transport.handle_request(request)
        if self._owned is None:
            self._owned = httpx.Client(timeout=_TIMEOUT_SECONDS)
        return self._owned.request(method, url, **kwargs)


__all__ = ["CloudSync"]

