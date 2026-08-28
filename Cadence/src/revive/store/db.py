"""SQLite connection + migration runner.

One connection per unit of work. WAL mode for concurrent readers during the
worker loop. Foreign keys on. Migrations are plain SQL files applied in
filename order; applied filenames are tracked in `meta`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).parent


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the API threadpool and the background worker
        # use their own Database instances, but Starlette's TestClient (and
        # uvicorn's threadpool) touch this one from a different thread than it
        # was created on. Writes stay serialized by WAL + busy_timeout.
        self._conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def migrate(self) -> list[str]:
        applied: list[str] = []
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        done = {
            row["key"]
            for row in self._conn.execute("SELECT key FROM meta WHERE key LIKE 'migration:%'")
        }
        files = sorted(_MIGRATIONS_DIR.glob("V*__*.sql"))
        base = _MIGRATIONS_DIR / "migrations.sql"
        if base.is_file():
            files = [base] + files
        for file in files:
            key = f"migration:{file.name}"
            if key in done:
                continue
            sql = file.read_text(encoding="utf-8")
            with self._conn:
                self._conn.executescript(sql)
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)", (key, file.name)
                )
            applied.append(file.name)
        return applied

    def close(self) -> None:
        self._conn.close()
