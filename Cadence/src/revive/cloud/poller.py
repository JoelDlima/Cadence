"""Supabase webhook-inbox poller (Phase E3).

Razorpay cannot reach a laptop behind NAT, so its webhooks land in the
``revive-ingest`` Edge Function which stages raw payloads in ``webhook_inbox``.
This poller fetches unprocessed rows and feeds them through the SAME local
pipeline used by the direct FastAPI endpoint (injected as ``process_fn``),
then marks the row processed. Offline-first: when ``CloudConfig.is_live`` is
false, ``run_once`` returns 0 without a single network request.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from revive.clock import Clock, utc_iso
from revive.config import CloudConfig
from revive.logging_setup import get_logger
from revive.store.db import Database

log = get_logger("revive.cloud.poller")

ProcessFn = Callable[[bytes, str | None], object]

_TIMEOUT_SECONDS = 15.0


class SupabaseInboxPoller:
    """Drains ``webhook_inbox`` into the local event-sourced pipeline."""

    def __init__(
        self,
        cfg: CloudConfig,
        db: Database,
        clock: Clock,
        process_fn: ProcessFn | None = None,
        transport: httpx.Client | None = None,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._clock = clock
        self._process_fn = process_fn
        # Any object exposing httpx's request() surface works (Client, MockTransport).
        self._transport: Any = transport
        self._owned: httpx.Client | None = None

    def fetch_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        """Oldest-first unprocessed rows; empty list on any HTTP failure."""
        url = f"{self._cfg.supabase_url}/rest/v1/webhook_inbox"
        try:
            resp = self._request(
                "GET",
                url,
                params={"processed": "is.false", "order": "received_at.asc", "limit": limit},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            log.error("webhook_inbox fetch failed: %s", exc)
            return []
        if not resp.is_success:
            log.error("webhook_inbox fetch returned HTTP %d", resp.status_code)
            return []
        rows = resp.json()
        return rows if isinstance(rows, list) else []

    def process_one(self, row: dict[str, Any], process_fn: ProcessFn) -> bool:
        """Replay one inbox row through the local pipeline; mark processed on success."""
        raw = json.dumps(row["payload"]).encode("utf-8")
        try:
            process_fn(raw, row.get("signature"))
        except Exception:
            log.exception("local processing failed for inbox row %s", row.get("id"))
            return False
        return self._mark_processed(str(row["id"]))

    def run_once(self, process_fn: ProcessFn | None = None, limit: int = 20) -> int:
        """One poll cycle; returns the number of rows fully processed."""
        fn = process_fn if process_fn is not None else self._process_fn
        if fn is None:
            raise ValueError("SupabaseInboxPoller requires a process_fn")
        if not self._cfg.is_live:
            return 0
        processed = 0
        for row in self.fetch_pending(limit):
            if self.process_one(row, fn):
                processed += 1
        return processed

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()

    def _mark_processed(self, row_id: str) -> bool:
        url = f"{self._cfg.supabase_url}/rest/v1/webhook_inbox?id=eq.{row_id}"
        body = {"processed": True, "processed_at": utc_iso(self._clock.now())}
        try:
            resp = self._request("PATCH", url, json=body, headers=self._headers("return=minimal"))
        except httpx.HTTPError as exc:
            log.error("webhook_inbox patch failed for %s: %s", row_id, exc)
            return False
        if not resp.is_success:
            log.error("webhook_inbox patch returned HTTP %d for %s", resp.status_code, row_id)
            return False
        return True

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._cfg.supabase_service_key,
            "Authorization": f"Bearer {self._cfg.supabase_service_key}",
            "Content-Type": "application/json",
        }
        if prefer is not None:
            headers["Prefer"] = prefer
        return headers

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


__all__ = ["ProcessFn", "SupabaseInboxPoller"]
