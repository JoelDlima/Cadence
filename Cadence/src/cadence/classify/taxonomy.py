"""Payment failure taxonomy: root causes, interventions, error-code map, legality matrix."""

from __future__ import annotations

NO_FUNDS = "NO_FUNDS"
BANK_DOWN = "BANK_DOWN"
TIMEOUT = "TIMEOUT"
CUSTOMER_ABORTED = "CUSTOMER_ABORTED"
ABANDONED_CHECKOUT = "ABANDONED_CHECKOUT"
HARD_DECLINE = "HARD_DECLINE"
BAD_VPA = "BAD_VPA"
EXPIRED_INSTRUMENT = "EXPIRED_INSTRUMENT"
UNKNOWN = "UNKNOWN"

ROOT_CAUSES: frozenset[str] = frozenset(
    {
        NO_FUNDS,
        BANK_DOWN,
        TIMEOUT,
        CUSTOMER_ABORTED,
        ABANDONED_CHECKOUT,
        HARD_DECLINE,
        BAD_VPA,
        EXPIRED_INSTRUMENT,
        UNKNOWN,
    }
)

RETRY_NOW = "RETRY_NOW"
RETRY_LATER = "RETRY_LATER"
RETRY_PAYDAY = "RETRY_PAYDAY"
SWITCH_METHOD = "SWITCH_METHOD"
GRACE_OFFER = "GRACE_OFFER"
WHATSAPP_NUDGE = "WHATSAPP_NUDGE"
EMAIL_NUDGE = "EMAIL_NUDGE"
PAYMENT_LINK = "PAYMENT_LINK"
HUMAN_REVIEW = "HUMAN_REVIEW"

INTERVENTIONS: frozenset[str] = frozenset(
    {
        RETRY_NOW,
        RETRY_LATER,
        RETRY_PAYDAY,
        SWITCH_METHOD,
        GRACE_OFFER,
        WHATSAPP_NUDGE,
        EMAIL_NUDGE,
        PAYMENT_LINK,
        HUMAN_REVIEW,
    }
)

ERROR_CODE_MAP: dict[str, str] = {
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
    "checkout_idle": ABANDONED_CHECKOUT,
    "authentication_failed": HARD_DECLINE,
    "card_declined": HARD_DECLINE,
    "expired_card": EXPIRED_INSTRUMENT,
    "card_expired": EXPIRED_INSTRUMENT,
}

DESCRIPTION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("insufficient", NO_FUNDS),
    ("downtime", BANK_DOWN),
    ("technical error", BANK_DOWN),
    ("collect request expired", TIMEOUT),
    ("time limit", TIMEOUT),
    ("cancelled", CUSTOMER_ABORTED),
    ("not debited", CUSTOMER_ABORTED),
    ("expired", EXPIRED_INSTRUMENT),
    ("invalid vpa", BAD_VPA),
    ("authentication", HARD_DECLINE),
    ("declined", HARD_DECLINE),
)

LEGAL_MOVES: dict[str, frozenset[str]] = {
    NO_FUNDS: frozenset(
        {RETRY_PAYDAY, RETRY_NOW, SWITCH_METHOD, GRACE_OFFER, WHATSAPP_NUDGE, EMAIL_NUDGE, PAYMENT_LINK}
    ),
    BANK_DOWN: frozenset({RETRY_LATER, RETRY_NOW, WHATSAPP_NUDGE, EMAIL_NUDGE}),
    TIMEOUT: frozenset({RETRY_LATER, RETRY_NOW, PAYMENT_LINK, WHATSAPP_NUDGE, EMAIL_NUDGE}),
    CUSTOMER_ABORTED: frozenset({WHATSAPP_NUDGE, EMAIL_NUDGE, PAYMENT_LINK}),
    # A self-managed idle Payment Link is not a failed mandate. Send exactly
    # one recovery message; do not create another link or schedule a debit.
    ABANDONED_CHECKOUT: frozenset({EMAIL_NUDGE, WHATSAPP_NUDGE}),
    HARD_DECLINE: frozenset(),  # strictly stop - no recovery moves
    BAD_VPA: frozenset({SWITCH_METHOD, EMAIL_NUDGE}),
    EXPIRED_INSTRUMENT: frozenset({SWITCH_METHOD, EMAIL_NUDGE}),
    UNKNOWN: frozenset({HUMAN_REVIEW}),
}


def legal_moves(root_cause: str) -> frozenset[str]:
    """Legal interventions for a root cause; empty set for causes outside the taxonomy."""
    return LEGAL_MOVES.get(root_cause, frozenset())
