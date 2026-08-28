"""Shared pytest fixtures: throwaway SQLite database and deterministic clock."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from revive.clock import FakeClock
from revive.store.db import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[Database]:
    """Fresh SQLite database with the canonical schema.

    ``Database`` applies ``migrations.sql`` itself and opens its connection
    with ``check_same_thread=False``, so the fixture is directly usable from
    Starlette TestClient worker threads - no patching needed.
    """
    db = Database(tmp_path / "t.db")
    yield db
    db.close()


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()  # defaults 2026-08-22T10:00Z
