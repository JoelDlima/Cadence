"""Promise-to-Pay parser tests: Hinglish dates, durations, vague, refusal, gibberish."""

from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime

import pytest

from cadence.agents.ptp_parser import (
    KIND_DATE,
    KIND_DURATION,
    KIND_REFUSAL,
    KIND_UNPARSEABLE,
    KIND_VAGUE,
    parse_reply,
    ptp_to_timer_days,
)

pytestmark = [pytest.mark.unit]

_TODAY = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)  # Saturday


def test_kal_pakka_parses_as_next_day_date() -> None:
    # Act
    ptp = parse_reply("Kal pakka karunga", today=_TODAY)

    # Assert
    assert ptp.kind == KIND_DATE
    assert ptp.commit_date_iso == "2026-08-23"
    assert ptp.confidence == pytest.approx(0.9)


def test_three_din_baad_parses_as_three_day_duration() -> None:
    # Act
    ptp = parse_reply("3 din baad pakka", today=_TODAY)

    # Assert
    assert ptp.kind == KIND_DURATION
    assert ptp.commit_date_iso == "2026-08-25"
    assert ptp.confidence == pytest.approx(0.8)


def test_agle_mahine_is_same_day_next_month_duration() -> None:
    # Act
    ptp = parse_reply("agle mahine karta hu", today=_TODAY)

    # Assert
    assert ptp.kind == KIND_DURATION
    assert ptp.commit_date_iso == "2026-09-22"
    assert ptp_to_timer_days(ptp, today=_TODAY.date()) == 31


def test_agle_mahine_clamps_short_months() -> None:
    # Arrange
    jan_31 = datetime(2026, 1, 31, 10, 0, tzinfo=UTC)

    # Act / Assert
    assert parse_reply("next month", today=jan_31).commit_date_iso == "2026-02-28"


def test_tarikh_day_in_the_past_rolls_to_next_month() -> None:
    # Act
    ptp = parse_reply("5 tarikh ko kar dunga", today=_TODAY)

    # Assert
    assert ptp.kind == KIND_DATE
    assert ptp.commit_date_iso == "2026-09-05"


def test_tarikh_overflow_clamps_to_month_end() -> None:
    # Arrange
    sep_22 = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)

    # Act / Assert
    assert parse_reply("31 tarikh", today=sep_22).commit_date_iso == "2026-09-30"


def test_parso_and_next_week_offsets() -> None:
    # Act / Assert
    assert parse_reply("parso pakka", today=_TODAY).commit_date_iso == "2026-08-24"
    next_week = parse_reply("Next week karta hu", today=_TODAY)
    assert next_week.kind == KIND_DATE
    assert next_week.commit_date_iso == "2026-08-29"


def test_two_hafte_is_fourteen_days() -> None:
    # Act
    ptp = parse_reply("2 hafte baad dekhte hain", today=_TODAY)

    # Assert
    assert ptp.kind == KIND_DURATION
    assert ptp_to_timer_days(ptp, today=_TODAY.date()) == 14


def test_cancel_kar_do_is_full_confidence_refusal() -> None:
    # Act
    ptp = parse_reply("Cancel kar do subscription", today=_TODAY)

    # Assert
    assert ptp.kind == KIND_REFUSAL
    assert ptp.commit_date_iso is None
    assert ptp.confidence == pytest.approx(1.0)
    assert ptp_to_timer_days(ptp) is None


def test_gibberish_and_empty_are_unparseable() -> None:
    # Act / Assert
    for text in ("xqzw frobnicate 42", "", "   "):
        ptp = parse_reply(text, today=_TODAY)
        assert ptp.kind == KIND_UNPARSEABLE
        assert ptp.commit_date_iso is None
        assert ptp.confidence == pytest.approx(0.0)
        assert ptp_to_timer_days(ptp) is None


def test_naive_today_is_interpreted_in_given_timezone() -> None:
    # Arrange: 23:30 wall-clock IST on Aug 22 (19:00 UTC same day)
    naive_evening = datetime(2026, 8, 22, 23, 30)

    # Act / Assert
    ptp = parse_reply("kal", today=naive_evening, tz="Asia/Kolkata")
    assert ptp.commit_date_iso == "2026-08-23"
    aware = naive_evening.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Kolkata"))
    assert parse_reply("kal", today=aware).commit_date_iso == "2026-08-23"


def test_vague_promises_get_default_three_day_timer() -> None:
    # Act / Assert
    for text in ("pakka", "try karta hu", "jaldi karunga"):
        ptp = parse_reply(text, today=_TODAY)
        assert ptp.kind == KIND_VAGUE
        assert ptp_to_timer_days(ptp) == 3


def test_timer_days_for_dates_count_until_commitment() -> None:
    # Act / Assert
    kal = parse_reply("kal", today=_TODAY)
    assert ptp_to_timer_days(kal, today=_TODAY.date()) == 1
    assert ptp_to_timer_days(parse_reply("nahi", today=_TODAY)) is None
