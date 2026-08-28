"""Durable queue + timers repository.

One table (`task_queue`) serves both: rows with future `available_at` are timers;
due rows are work. Claiming uses a single atomic UPDATE...RETURNING inside an
immediate transaction so two workers can never take the same task.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from revive.store.db import Database


@dataclass(frozen=True)
class Task:
    task_id: int
    task_type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    available_at: str


class QueueRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def enqueue(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        available_at: str,
        created_at: str,
        idempotency_key: str | None = None,
        max_attempts: int = 5,
    ) -> int | None:
        """Insert a task. Returns task_id, or None if idempotency_key already seen."""
        key = idempotency_key or f"{task_type}:{uuid.uuid4().hex}"
        try:
            cursor = self._db.conn.execute(
                """
                INSERT INTO task_queue
                    (idempotency_key, task_type, payload, available_at, created_at, max_attempts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    task_type,
                    json.dumps(payload, sort_keys=True),
                    available_at,
                    created_at,
                    max_attempts,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - unique violation means duplicate
            if "UNIQUE constraint failed: task_queue.idempotency_key" in str(exc):
                return None
            raise
        return int(cursor.lastrowid)

    def claim_due(self, *, now_iso: str, limit: int = 10) -> list[Task]:
        """Atomically claim up to `limit` due pending tasks (status -> processing)."""
        claimed: list[Task] = []
        with self._db.conn:
            rows = self._db.conn.execute(
                """
                UPDATE task_queue
                   SET status='processing', claimed_at=?
                 WHERE task_id IN (
                     SELECT task_id FROM task_queue
                      WHERE status='pending' AND available_at <= ?
                      ORDER BY available_at ASC
                      LIMIT ?
                 )
                 RETURNING task_id, task_type, payload, attempts, max_attempts, available_at
                """,
                (now_iso, now_iso, limit),
            ).fetchall()
        for row in rows:
            claimed.append(
                Task(
                    task_id=row["task_id"],
                    task_type=row["task_type"],
                    payload=json.loads(row["payload"]),
                    attempts=row["attempts"],
                    max_attempts=row["max_attempts"],
                    available_at=row["available_at"],
                )
            )
        return claimed

    def mark_done(self, task_id: int) -> None:
        self._db.conn.execute(
            "UPDATE task_queue SET status='done' WHERE task_id=?", (task_id,)
        )

    def mark_failed_retry(
        self, task_id: int, *, backoff_seconds: int, next_available_at: str, error: str
    ) -> None:
        """Increment attempts; re-queue with backoff or send to DLQ when exhausted."""
        row = self._db.conn.execute(
            "SELECT attempts, max_attempts FROM task_queue WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            return
        attempts = row["attempts"] + 1
        status = "dead" if attempts >= row["max_attempts"] else "pending"
        self._db.conn.execute(
            """
            UPDATE task_queue
               SET attempts=?, status=?, last_error=?, available_at=?, claimed_at=NULL
             WHERE task_id=?
            """,
            (attempts, status, error[:500], next_available_at, task_id),
        )

    def pending_count(self) -> int:
        row = self._db.conn.execute(
            "SELECT COUNT(*) AS c FROM task_queue WHERE status='pending'"
        ).fetchone()
        return int(row["c"])

    def dead_letters(self, limit: int = 50) -> list[Task]:
        rows = self._db.conn.execute(
            """
            SELECT task_id, task_type, payload, attempts, max_attempts, available_at
              FROM task_queue WHERE status='dead' ORDER BY task_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            Task(
                task_id=r["task_id"],
                task_type=r["task_type"],
                payload=json.loads(r["payload"]),
                attempts=r["attempts"],
                max_attempts=r["max_attempts"],
                available_at=r["available_at"],
            )
            for r in rows
        ]
