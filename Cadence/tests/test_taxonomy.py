"""Taxonomy tests: error-code coverage, cause inventory, legality-matrix integrity."""

from cadence.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    ERROR_CODE_MAP,
    EXPIRED_INSTRUMENT,
    HARD_DECLINE,
    INTERVENTIONS,
    LEGAL_MOVES,
    NO_FUNDS,
    ROOT_CAUSES,
    TIMEOUT,
    UNKNOWN,
    legal_moves,
)


def test_every_documented_error_code_maps_to_its_root_cause() -> None:
    assert ERROR_CODE_MAP == {
        "insufficient_funds": NO_FUNDS,
        "bank_technical_error": BANK_DOWN,
        "gateway_technical_error": BANK_DOWN,
        "credit_failed": BANK_DOWN,
        "vpa_resolution_failed": BAD_VPA,
        "invalid_vpa": BAD_VPA,
        "payment_collect_request_expired": TIMEOUT,
        "payment_timed_out": TIMEOUT,
        "payment_cancelled": CUSTOMER_ABORTED,
        "payment_declined": CUSTOMER_ABORTED,
        "authentication_failed": HARD_DECLINE,
        "card_declined": HARD_DECLINE,
        "expired_card": EXPIRED_INSTRUMENT,
        "card_expired": EXPIRED_INSTRUMENT,
    }


def test_all_eight_root_causes_are_present_in_root_causes() -> None:
    all_causes = {
        NO_FUNDS,
        BANK_DOWN,
        TIMEOUT,
        CUSTOMER_ABORTED,
        HARD_DECLINE,
        BAD_VPA,
        EXPIRED_INSTRUMENT,
        UNKNOWN,
    }
    assert all_causes == set(ROOT_CAUSES)


def test_legal_moves_covers_every_root_cause() -> None:
    assert set(LEGAL_MOVES) == set(ROOT_CAUSES)


def test_every_legal_move_is_a_known_intervention() -> None:
    for moves in LEGAL_MOVES.values():
        assert moves <= INTERVENTIONS


def test_hard_decline_has_zero_legal_moves() -> None:
    assert LEGAL_MOVES[HARD_DECLINE] == frozenset()


def test_bogus_root_cause_returns_empty_move_set() -> None:
    assert legal_moves("bogus") == frozenset()
