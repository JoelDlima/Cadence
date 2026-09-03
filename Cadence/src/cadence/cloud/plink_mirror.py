"""Supabase mirror for Razorpay payment links (Phase 4).

Local SQLite + the hash chain stay the source of truth. This module keeps a
one-way projection of every payment link Cadence creates -- and every
lifecycle transition it drives -- in the `cadence_payment_links` table, so a
judge can watch rows appear in the Supabase Studio table editor while the
demo runs.

Design notes, consistent with `cloud/sync.py`:
  - One-way: SQLite -> Supabase. Nothing is ever read back as truth.
  - Fully no-op when the cloud config is not live (no URL / no service key /
    sync disabled). Every public method returns False instead of raising, so
    a cloud outage can never fail a payment-recovery drill.
  - Writes go through httpx's json= encoder (never string-interpolated SQL).
  - Upserts use PostgREST `on_conflict=plink_id` + merge-duplicates, so
    re-running the demo updates the existing row instead of duplicating it.
  - `lifecycle_events` is a JSONB array appended to via the read-modify-write
    below. PostgREST cannot append to JSONB in one call without a stored
    procedure, and a stored procedure would mean a second migration for the
    judge to run; one extra GET is the cheaper trade at demo volume.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx

from cadence.config import AppConfig, CloudConfig
from cadence.logging_setup import get_logger

log = get_logger("cadence.cloud.plink_mirror")

_TIMEOUT_SECONDS = 10.0
_TABLE = "cadence_payment_links"
_MAX_LIFECYCLE_EVENTS = 40


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class PlinkMirror:
    """Upserts payment links + their lifecycle events to Supabase."""

    def __init__(self, cfg: CloudConfig, transport: httpx.Client | None = None) -> None:
        self._cfg = cfg
        self._transport = transport
        self._owned: httpx.Client | None = None
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "enabled": bool(cfg.is_live),
            "last_write_at": None,
            "writes_ok": 0,
            "writes_failed": 0,
            "last_error": None,
            "last_read_error": None,
        }

    # -- introspection -------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self._cfg.is_live)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    # -- writes --------------------------------------------------------
    def upsert_plink(
        self,
        *,
        plink_id: str,
        journey_id: str,
        subscription_id: str | None = None,
        customer_id: str | None = None,
        amount_minor: int | None = None,
        currency: str = "INR",
        status: str = "created",
        short_url: str = "",
        reference_id: str = "",
        created_at: str | None = None,
    ) -> bool:
        """Insert (or merge into) the row for one payment link."""
        if not self.enabled or not plink_id:
            return False
        now = _utc_now_iso()
        row = {
            "plink_id": plink_id,
            "journey_id": journey_id,
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "status": status,
            "short_url": short_url,
            "reference_id": reference_id,
            "created_at": created_at or now,
            "last_updated_at": now,
        }
        return self._upsert([row])

    def record_lifecycle_event(
        self,
        *,
        plink_id: str,
        event_type: str,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Append one transition to the row's `lifecycle_events` JSONB array
        and (when given) move the row's `status` forward."""
        if not self.enabled or not plink_id:
            return False
        entry = {
            "at": _utc_now_iso(),
            "event_type": event_type,
            "status": status,
            "payload": payload or {},
        }
        existing = self._fetch_row(plink_id)
        events: list[dict[str, Any]] = []
        if existing is not None:
            raw_events = existing.get("lifecycle_events")
            if isinstance(raw_events, list):
                events = list(raw_events)
        events.append(entry)
        events = events[-_MAX_LIFECYCLE_EVENTS:]
        row: dict[str, Any] = {
            "plink_id": plink_id,
            "lifecycle_events": events,
            "last_updated_at": entry["at"],
        }
        if status:
            row["status"] = status
        # Keep the identifying columns when the row does not exist yet, so a
        # lifecycle event on an unmirrored link still lands (NOT NULL-safe).
        if existing is None and payload:
            row.setdefault("journey_id", payload.get("journey_id"))
            row.setdefault("subscription_id", payload.get("subscription_id"))
            row.setdefault("customer_id", payload.get("customer_id"))
            row.setdefault("amount_minor", payload.get("amount_minor"))
            row.setdefault("currency", payload.get("currency") or "INR")
            row.setdefault("short_url", payload.get("short_url") or "")
            row.setdefault("reference_id", payload.get("reference_id") or "")
            row.setdefault("created_at", entry["at"])
        return self._upsert([row])

    # -- reads (for /api/cloud/plinks, so the SPA never sees the key) ---
    def list_plinks(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        url = f"{self._cfg.supabase_url}/rest/v1/{_TABLE}"
        params = {
            "select": "*",
            "order": "last_updated_at.desc",
            "limit": str(max(1, min(limit, 200))),
        }
        try:
            resp = self._request("GET", url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            self._note_read_error(str(exc))
            log.error("plink mirror list failed: %s", exc)
            return []
        if not resp.is_success:
            # PGRST205 = table not in the schema cache, i.e. the V7 migration
            # has not been run yet. Say so instead of returning a silent [].
            detail = resp.text[:200]
            if "PGRST205" in detail or resp.status_code == 404:
                detail = (
                    f"{_TABLE} not found -- run "
                    "supabase/migrations/V7__cadence_payment_links.sql in "
                    "Supabase Studio > SQL Editor"
                )
            self._note_read_error(detail)
            log.error("plink mirror list returned HTTP %d: %s", resp.status_code, detail)
            return []
        data = resp.json()
        self._note_read_error(None)
        return list(data) if isinstance(data, list) else []

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()
            self._owned = None

    # -- internals -----------------------------------------------------
    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._cfg.supabase_service_key,
            "Authorization": f"Bearer {self._cfg.supabase_service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _fetch_row(self, plink_id: str) -> dict[str, Any] | None:
        url = f"{self._cfg.supabase_url}/rest/v1/{_TABLE}"
        params = {"select": "*", "plink_id": f"eq.{plink_id}", "limit": "1"}
        try:
            resp = self._request("GET", url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            log.info("plink mirror read %s failed: %s", plink_id, exc)
            return None
        if not resp.is_success:
            return None
        data = resp.json()
        if isinstance(data, list) and data:
            return dict(data[0])
        return None

    def _upsert(self, rows: list[dict[str, Any]]) -> bool:
        url = f"{self._cfg.supabase_url}/rest/v1/{_TABLE}?on_conflict=plink_id"
        headers = self._headers("resolution=merge-duplicates,return=minimal")
        try:
            resp = self._request("POST", url, json=rows, headers=headers)
        except httpx.HTTPError as exc:
            self._note(ok=False, error=str(exc))
            log.error("plink mirror upsert failed: %s", exc)
            return False
        if not resp.is_success:
            self._note(ok=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
            log.error("plink mirror upsert returned HTTP %d", resp.status_code)
            return False
        self._note(ok=True)
        return True

    def _note(self, *, ok: bool, error: str | None = None) -> None:
        with self._lock:
            self._state["last_write_at"] = _utc_now_iso()
            if ok:
                self._state["writes_ok"] += 1
                self._state["last_error"] = None
            else:
                self._state["writes_failed"] += 1
                self._state["last_error"] = error

    def _note_read_error(self, error: str | None) -> None:
        with self._lock:
            self._state["last_read_error"] = error

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Route through an injected transport/client, else an owned client.
        Mirrors CloudSync._request so tests can inject a MockTransport."""
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


# One process-wide mirror per cloud config. The lifecycle routes call this from
# request threads; building an httpx client per call would be wasteful and the
# instance is internally locked.
_MIRRORS: dict[tuple[str, str, bool], PlinkMirror] = {}
_MIRRORS_LOCK = threading.Lock()


def get_plink_mirror(config: AppConfig | CloudConfig) -> PlinkMirror:
    """Process-wide PlinkMirror for this cloud config. Accepts an AppConfig
    (convenience for callers holding `runtime.config`) or a CloudConfig."""
    cfg = config.cloud if isinstance(config, AppConfig) else config
    key = (cfg.supabase_url, cfg.supabase_service_key[:12], bool(cfg.sync_enabled))
    with _MIRRORS_LOCK:
        mirror = _MIRRORS.get(key)
        if mirror is None:
            mirror = PlinkMirror(cfg)
            _MIRRORS[key] = mirror
        return mirror


def reset_plink_mirrors() -> None:
    """Test hook: drop the cached mirrors (and their httpx clients)."""
    with _MIRRORS_LOCK:
        for mirror in _MIRRORS.values():
            mirror.close()
        _MIRRORS.clear()


__all__ = ["PlinkMirror", "get_plink_mirror", "reset_plink_mirrors"]
