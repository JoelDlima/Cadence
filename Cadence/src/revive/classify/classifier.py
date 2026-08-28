"""Rules-first failure classifier: exact error-code hit, then description keyword fallback."""

from __future__ import annotations

from dataclasses import dataclass

from revive.classify.taxonomy import DESCRIPTION_KEYWORDS, ERROR_CODE_MAP, UNKNOWN

SOURCE_RULES = "rules"
SOURCE_LLM = "llm"
SOURCE_STICKY = "sticky"
CONFIDENCE_EXACT_CODE = 1.0
CONFIDENCE_KEYWORD = 0.6
CONFIDENCE_UNKNOWN = 0.0


@dataclass(frozen=True)
class Classification:
    root_cause: str
    source: str
    confidence: float
    matched_code: str | None


def classify(error_code: str | None, error_description: str | None) -> Classification:
    """Classify a payment failure; exact code wins over keyword scan, else unknown."""
    normalized_code = error_code.strip().lower() if error_code else ""
    if normalized_code in ERROR_CODE_MAP:
        return Classification(
            root_cause=ERROR_CODE_MAP[normalized_code],
            source=SOURCE_RULES,
            confidence=CONFIDENCE_EXACT_CODE,
            matched_code=normalized_code,
        )
    normalized_description = error_description.lower() if error_description else ""
    for keyword, cause in DESCRIPTION_KEYWORDS:
        if keyword in normalized_description:
            return Classification(
                root_cause=cause,
                source=SOURCE_RULES,
                confidence=CONFIDENCE_KEYWORD,
                matched_code=None,
            )
    return Classification(
        root_cause=UNKNOWN,
        source=SOURCE_RULES,
        confidence=CONFIDENCE_UNKNOWN,
        matched_code=None,
    )
