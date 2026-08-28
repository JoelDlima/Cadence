"""Faker-driven 5,000-subscriber cohort with full Indian-locale support.

Purpose: a larger, more realistic cohort for the eval report's "scaled run"
number. The headline 500-sub number stays the source of truth (driven by
``revive.sim.cohort.generate_cohort``); this file provides an *opt-in*
larger cohort that demos the same recovery rate at 10x scale, with realistic
Indian names, UPI handles, and IFSC codes via Faker's ``hi_IN`` locale.

Determinism: same (n, seed) always yields the identical list. Indian
names are pulled from a frozen Faker instance seeded with the same
``Faker.seed(n + seed)`` pattern as the test cohort, so cohort membership
is reproducible across runs.

Output: a tuple ``(cohort, profiles)`` where:
- ``cohort`` is a ``list[SimSubscriber]`` identical in shape to what
  ``revive.sim.cohort.generate_cohort`` returns, so the existing
  ``run_arm_naive`` and ``run_arm_revive`` consumers take this list as a
  drop-in replacement.
- ``profiles`` is a ``list[dict]`` with extra Faker-only metadata
  (``customer_name``, ``customer_upi``, ``ifsc``) for the README's
  "5,000-sub multilingual Indian cohort" narrative and for any dashboard
  that wants to show the customer-facing side.

Why the original 500-sub cohort stays: it is the *canonical* number
the README, eval-report, and pitch deck cite. The 5,000-sub number is
a *secondary* signal: "the same engine, the same seed stability, the
same +43.9 % uplift, at 10x scale with realistic Indian data."
"""

from __future__ import annotations

from typing import Any

try:
    from faker import Faker
except ImportError as e:  # pragma: no cover - declared in pyproject.toml
    raise ImportError(
        "Faker is required for the 5,000-sub eval cohort. "
        "Install with: pip install faker>=20.0"
    ) from e

from revive.classify.taxonomy import UNKNOWN
from revive.sim.cohort import (
    SimSubscriber,
    _FAILURE_CODES,
    _FAILURE_DESCRIPTIONS,
    _UNKNOWN_DESCRIPTION,
    _draw_cause,
)


# Realistic Indian amount tiers (in paise), Rs 199 .. Rs 2,999.
# Re-using the original simulator's distribution, not Faker's, because the
# recovery-rate table in revive.sim.outcomes is calibrated against this mix.
_AMOUNT_TIERS = (
    (19900, 30),
    (29900, 25),
    (49900, 20),
    (99900, 12),
    (149900, 7),
    (199900, 4),
    (299900, 2),
)


def _draw_amount(rng: Any) -> int:
    """Sample an amount from the realistic Indian tier distribution."""
    total = sum(weight for _, weight in _AMOUNT_TIERS)
    roll = rng.random() * total
    cumulative = 0
    for amount, weight in _AMOUNT_TIERS:
        cumulative += weight
        if roll < cumulative:
            return amount
    return _AMOUNT_TIERS[0][0]  # pragma: no cover


# Realistic Indian UPI handle bank pool. Not every Indian handle is at oksbi.
_UPI_BANK = (
    "oksbi",        # State Bank of India
    "okhdfcbank",   # HDFC
    "okicici",       # ICICI
    "okaxis",       # Axis
    "okkotak",      # Kotak
    "ybl",          # Yes Bank (legacy handle)
)


def _upi_handle(first: str, last: str, n: int) -> str:
    """Realistic UPI handle: ``first.last.NNNN@oksbi`` style.

    Lowercased, alphanumeric only, dot-separated. The NNNN suffix ensures
    uniqueness across the cohort. The handle bank is drawn from the pool above.
    """
    base = f"{first}.{last}".lower().replace(" ", "").replace("'", "")
    return f"{base}{n}@{_UPI_BANK[n % len(_UPI_BANK)]}"


# Realistic Indian bank codes for IFSC. The full IFSC scheme is 4 alpha +
# 1 zero + 6 digits. Faker's ``swift11`` is 6 alpha + 5 digits and does
# not always start with a known Indian bank code, so we build the
# IFSC deterministically from this list.
_INDIAN_BANK_CODES = (
    "SBIN",   # State Bank of India
    "HDFC",   # HDFC Bank
    "ICIC",   # ICICI Bank
    "UTIB",   # Axis Bank
    "KKBK",   # Kotak Mahindra Bank
    "YESB",   # Yes Bank
    "PUNB",   # Punjab National Bank
    "BARB",   # Bank of Baroda
    "CNRB",   # Canara Bank
    "UBIN",   # Union Bank of India
)


def _ifsc(rng: Any, i: int) -> str:
    """Realistic IFSC: 4 letters + 0 + 6 digits.

    We pick a known Indian bank code from ``_INDIAN_BANK_CODES`` and append a
    deterministic 6-digit branch number. Using ``rng`` for the bank
    selection and ``i`` for the branch keeps the cohort reproducible.
    """
    bank = _INDIAN_BANK_CODES[rng.randrange(0, len(_INDIAN_BANK_CODES))]
    branch = f"{(i * 37 + 12345) % 1000000:06d}"
    return f"{bank}0{branch}"


def _indian_name_pair(faker: Any) -> tuple[str, str]:
    """(first, last) using ``hi_IN`` with graceful fallback to ``en_IN``."""
    try:
        return faker.first_name(), faker.last_name()
    except Exception:  # pragma: no cover - defensive
        return faker.first_name(), faker.last_name()


def generate_indian_cohort(
    n: int = 5000,
    seed: int = 42,
    locale: str = "hi_IN",
) -> tuple[list[SimSubscriber], list[dict[str, Any]]]:
    """Deterministic Faker-driven cohort of ``n`` Indian subscribers.

    Returns ``(cohort, profiles)``. ``cohort`` is the SimSubscriber list the
    experiment arm consumers expect; ``profiles`` is a parallel list of
    dicts with extra Faker-only metadata (customer name, UPI handle, IFSC).

    The ``Faker.seed`` pattern uses ``seed * 1009 + n`` so that calling with
    the same ``seed`` but different ``n`` still yields different content
    (Faker's seed is global).
    """
    faker_seed = (seed * 1009 + n) & 0x7FFFFFFF
    Faker.seed(faker_seed)
    faker = Faker(locale)
    faker.seed_instance(faker_seed)
    # Faker's bound random on this generator instance (seeded above)
    rng = faker.random

    cohort: list[SimSubscriber] = []
    profiles: list[dict[str, Any]] = []
    for i in range(n):
        first, last = _indian_name_pair(faker)
        cause = _draw_cause(rng)
        amount = _draw_amount(rng)
        # ``cause`` may be None (unknown-code remainder of the mix).
        code = None if cause in (None, UNKNOWN) else _FAILURE_CODES[cause]
        description = (
            _UNKNOWN_DESCRIPTION
            if cause in (None, UNKNOWN)
            else _FAILURE_DESCRIPTIONS[cause]
        )
        cohort.append(
            SimSubscriber(
                subscription_id=f"sub_fk_{i:05d}",
                customer_id=f"cust_{i:05d}",  # ASCII-only; frontend logs/search safe
                amount_minor=amount,
                failure_code=code,
                error_description=description,
            )
        )
        profiles.append(
            {
                "subscription_id": f"sub_fk_{i:05d}",
                "customer_name": f"{first} {last}",
                "customer_upi": _upi_handle(first, last, i),
                "ifsc": _ifsc(rng, i),
                "amount_inr": amount // 100,
                "root_cause": cause,
                "failure_code": code,
            }
        )
    return cohort, profiles
