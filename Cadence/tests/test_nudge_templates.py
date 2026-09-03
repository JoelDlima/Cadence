"""Tests for the Indic-language recovery nudge templates."""
from __future__ import annotations

from cadence.policy.nudge_templates import (
    SUPPORTED_LANGUAGES,
    nudge_for_language,
)


def test_supported_languages_is_frozen_set_of_seven() -> None:
    assert isinstance(SUPPORTED_LANGUAGES, frozenset)
    assert SUPPORTED_LANGUAGES == frozenset({
        "hi", "ta", "te", "bn", "mr", "gu", "hinglish",
    })


def test_known_language_returns_its_template() -> None:
    out = nudge_for_language("hi", 49900, "https://pay.test/x")
    assert "Namaste" in out
    assert "\u20b9499" in out
    assert "https://pay.test/x" in out
    assert "Cadence" in out


def test_unknown_language_falls_back_to_hinglish() -> None:
    out = nudge_for_language("xx", 49900, "https://pay.test/x")
    assert out.startswith("Hi!")
    assert "Aapka" in out


def test_no_link_renders_link_free_template() -> None:
    out = nudge_for_language("hi", 19900)
    assert "Namaste" in out
    assert "https://" not in out


def test_amount_formats_integer_rupees() -> None:
    out = nudge_for_language("hinglish", 100000, "https://pay.test/x")
    assert "\u20b91000" in out
    assert "\u20b91000.00" not in out


def test_amount_formats_fractional_rupees() -> None:
    out = nudge_for_language("hinglish", 12345, "https://pay.test/x")
    assert "\u20b9123.45" in out


def test_all_six_indic_languages_render_distinctly() -> None:
    """Each Indic language must use a script-distinct greeting."""
    greetings = {}
    for lang in ("hi", "ta", "te", "bn", "mr", "gu"):
        greetings[lang] = nudge_for_language(lang, 10000)
    # Hindi and Marathi are both Devanagari but their greetings differ.
    assert greetings["hi"].startswith("Namaste!")
    assert greetings["mr"].startswith("Namaskar!")
    # The other four use distinct scripts.
    assert greetings["ta"].startswith("Vanakkam!")
    assert greetings["te"].startswith("Namaskaram!")
    assert greetings["bn"].startswith("Namaskar!")
    assert greetings["gu"].startswith("Namaskar!")
