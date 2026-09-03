"""Tests for the RBI / NPCI circular ingestion helpers.

These exercise the heuristic extractors without touching the policy
or storage layer. The full pipeline is tested in tests/test_api.py.
"""

from cadence.policy.circulars import (
    _detect_source,
    _extract_date,
    _extract_reference,
    _extract_rules,
    _extract_summary,
)


def test_detect_source_recognises_rbi_and_npci() -> None:
    """The source detection uses the first 2,000 chars + filename hint."""
    assert _detect_source("Reserve Bank of India", path_hint="") == "RBI"
    assert _detect_source("National Payments Corporation of India", path_hint="") == "NPCI"
    # filename hint can dominate
    assert _detect_source("nothing here", path_hint="RBI_2026.pdf") == "RBI"
    # fallback
    assert _detect_source("totally unrelated", path_hint="random.pdf") == "other"


def test_extract_summary_picks_first_meaningful_sentence() -> None:
    txt = (
        "Header line that is too short.\n"
        "This is a proper opening sentence that explains the circular "
        "in at least thirty characters and ends here.\n"
        "A second sentence follows."
    )
    s = _extract_summary(txt)
    assert s.startswith("This is a proper opening sentence")
    assert s.endswith(".")
    # The 30-char minimum filter excludes the header line.


def test_extract_rules_finds_must_should_may_not() -> None:
    txt = (
        "Section 3.2 Notification timing. The merchant shall send a 24-hour "
        "notice to the customer before any retry. The customer may not be "
        "charged more than the original amount. The customer is required "
        "to receive a refund within seven business days."
    )
    rules = _extract_rules(txt, "RBI")
    assert len(rules) == 3
    for r in rules:
        assert r.requires == "RBI"
        assert r.text.endswith(".")


def test_extract_rules_caps_at_32() -> None:
    txt = "\n".join(
        f"Section 1. The merchant shall do thing {i}."
        for i in range(50)
    )
    rules = _extract_rules(txt, "RBI")
    assert len(rules) == 32


def test_extract_date_and_reference_heuristics() -> None:
    txt = (
        "RBI/2021-22/123 dated 12 March 2021. "
        "This circular supersedes NPCI/2020-21/456."
    )
    assert _extract_date(txt) is not None
    assert "March" in _extract_date(txt)
    refs = _extract_reference(txt)
    # The first reference is the RBI one; we just verify the function
    # returns a non-empty string starting with the regex group.
    assert refs is not None
    assert refs.upper().startswith(("RBI", "NPCI"))
