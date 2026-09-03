"""Preferences repo tests: schema defaults, roundtrip, upsert overwrite."""

from __future__ import annotations

import pytest

from cadence.policy.preferences import Preferences, PreferencesRepo
from cadence.store.db import Database

pytestmark = [pytest.mark.unit]

T_NOW = "2026-08-22T10:00:00+00:00"


@pytest.fixture
def repo(tmp_db: Database) -> PreferencesRepo:
    return PreferencesRepo(tmp_db)


def test_get_returns_none_for_unknown_customer(repo: PreferencesRepo) -> None:
    # Act
    prefs = repo.get("cust_nope")

    # Assert
    assert prefs is None


def test_upsert_then_get_roundtrips_channels_and_window(repo: PreferencesRepo) -> None:
    # Arrange
    repo.upsert(
        customer_id="cust_1",
        allowed_channels=["whatsapp", "email"],
        window_start=8,
        window_end=12,
        now_iso=T_NOW,
    )

    # Act
    prefs = repo.get("cust_1")

    # Assert
    assert prefs == Preferences(
        customer_id="cust_1",
        allowed_channels=("whatsapp", "email"),
        preferred_window_start=8,
        preferred_window_end=12,
    )


def test_schema_defaults_apply_for_row_without_explicit_values(
    repo: PreferencesRepo, tmp_db: Database
) -> None:
    # Arrange
    tmp_db.conn.execute(
        "INSERT INTO customer_preferences (customer_id) VALUES (?)", ("cust_raw",)
    )

    # Act
    prefs = repo.get("cust_raw")

    # Assert
    assert prefs == Preferences(
        customer_id="cust_raw",
        allowed_channels=("whatsapp", "email"),
        preferred_window_start=0,
        preferred_window_end=24,
    )


def test_upsert_overwrites_existing_preferences_in_place(repo: PreferencesRepo) -> None:
    # Arrange
    repo.upsert(
        customer_id="cust_2",
        allowed_channels=["email"],
        window_start=0,
        window_end=24,
        now_iso=T_NOW,
    )
    repo.upsert(
        customer_id="cust_2",
        allowed_channels=["whatsapp"],
        window_start=18,
        window_end=21,
        now_iso=T_NOW,
    )

    # Act
    prefs = repo.get("cust_2")

    # Assert
    assert prefs == Preferences(
        customer_id="cust_2",
        allowed_channels=("whatsapp",),
        preferred_window_start=18,
        preferred_window_end=21,
    )


def test_get_strips_whitespace_around_channel_names(repo: PreferencesRepo) -> None:
    # Arrange
    repo.upsert(
        customer_id="cust_3",
        allowed_channels=[" whatsapp ", "email"],
        window_start=9,
        window_end=12,
        now_iso=T_NOW,
    )

    # Act
    prefs = repo.get("cust_3")

    # Assert
    assert prefs is not None
    assert prefs.allowed_channels == ("whatsapp", "email")
