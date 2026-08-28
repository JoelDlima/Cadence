"""Classifier tests: exact-code, keyword-fallback, unknown, and case-insensitive paths."""

from revive.classify.classifier import Classification, classify
from revive.classify.taxonomy import NO_FUNDS, UNKNOWN


def test_exact_error_code_hit_yields_full_confidence_and_matched_code() -> None:
    result = classify("insufficient_funds", None)

    assert result == Classification(
        root_cause=NO_FUNDS, source="rules", confidence=1.0, matched_code="insufficient_funds"
    )


def test_keyword_fallback_classifies_insufficient_balance_description() -> None:
    result = classify(None, "customer's account has insufficient balance")

    assert result.root_cause == NO_FUNDS
    assert result.source == "rules"
    assert result.confidence == 0.6
    assert result.matched_code is None


def test_unrecognized_code_and_description_fall_back_to_unknown() -> None:
    result = classify("totally_unknown_code", "something inexplicable happened")

    assert result == Classification(
        root_cause=UNKNOWN, source="rules", confidence=0.0, matched_code=None
    )


def test_missing_code_and_description_fall_back_to_unknown() -> None:
    result = classify(None, None)

    assert result == Classification(
        root_cause=UNKNOWN, source="rules", confidence=0.0, matched_code=None
    )


def test_uppercase_error_code_is_matched_case_insensitively() -> None:
    result = classify("INSUFFICIENT_FUNDS", None)

    assert result.root_cause == NO_FUNDS
    assert result.confidence == 1.0


def test_whitespace_padded_error_code_is_stripped_before_matching() -> None:
    result = classify("  payment_timed_out  ", None)

    assert result.confidence == 1.0
