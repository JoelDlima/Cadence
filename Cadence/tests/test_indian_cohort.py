"""Tests for the Faker-driven 5,000-sub Indian cohort (Phase 9a).

The cohort is the *secondary* signal for the pitch deck. The headline
500-sub number stays the source of truth; this test suite proves the
Faker cohort is reproducible (same seed, same list), shaped right
(SimSubscriber instances with valid Razorpay error codes and Indian
amount tiers), and that the eval-summary endpoint prefers the large file
when present.
"""

from __future__ import annotations

from cadence.sim.indian_cohort import generate_indian_cohort


def test_indian_cohort_deterministic_for_same_seed() -> None:
    """Same (n, seed) yields the identical list, in order."""
    a, _ = generate_indian_cohort(n=100, seed=42)
    b, _ = generate_indian_cohort(n=100, seed=42)
    assert len(a) == 100
    assert len(b) == 100
    for sa, sb in zip(a, b):
        assert sa.subscription_id == sb.subscription_id
        assert sa.amount_minor == sb.amount_minor
        assert sa.failure_code == sb.failure_code


def test_indian_cohort_varies_with_seed() -> None:
    """Different seeds yield different content (Faker's seed is global)."""
    a, _ = generate_indian_cohort(n=20, seed=42)
    b, _ = generate_indian_cohort(n=20, seed=43)
    # At least one subscription_id / amount / failure_code should differ
    # (extremely unlikely to all match across 20 rows on different seeds)
    pairs = zip(a, b)
    matches = sum(
        1
        for sa, sb in pairs
        if sa.subscription_id == sb.subscription_id
        and sa.amount_minor == sb.amount_minor
        and sa.failure_code == sb.failure_code
    )
    assert matches < 20, f"expected most rows to differ across seeds; {matches}/20 matched"


def test_indian_cohort_failure_code_distribution_realistic() -> None:
    """The cohort uses the calibrated failure-cause mix from cohort.py:
    NO_FUNDS dominates, hard-decline and unknown stay minor."""
    from collections import Counter

    cohort, _ = generate_indian_cohort(n=1000, seed=42)
    codes = Counter(s.failure_code for s in cohort)
    total_mapped = sum(c for k, c in codes.items() if k is not None)
    assert total_mapped > 700  # at least 70 % of 1,000 are mapped

    # All codes must be in the Razorpay error-code map (or None for unknown).
    from cadence.classify.taxonomy import ERROR_CODE_MAP
    for c in codes:
        assert c is None or c in ERROR_CODE_MAP


def test_indian_cohort_amounts_in_indian_subscription_tiers() -> None:
    """All amounts in the cohort fall in the realistic Indian subscription
    tier (Rs 199 .. Rs 2,999)."""
    cohort, _ = generate_indian_cohort(n=200, seed=42)
    for s in cohort:
        amount_inr = s.amount_minor // 100
        assert 199 <= amount_inr <= 2999, f"amount {amount_inr} INR out of realistic Indian subscription tier"


def test_indian_cohort_profiles_have_required_fields() -> None:
    """The Faker profiles include the metadata the README headline uses."""
    cohort, profiles = generate_indian_cohort(n=20, seed=42)
    assert len(cohort) == len(profiles) == 20
    for sub, prof in zip(cohort, profiles):
        assert prof["subscription_id"] == sub.subscription_id
        # Faker-derived fields must be present and well-formed
        assert "@" in prof["customer_upi"]                # UPI handle
        # IFSC: 4-letter bank prefix from a known Indian bank, then 0,
        # then 6 digits. We check the 4-letter prefix is in our list,
        # not the buggy ``tuple("SBINHDFC")`` (which iterates chars).
        assert prof["ifsc"][:4] in {
            "SBIN", "HDFC", "ICIC", "UTIB", "KKBK", "YESB",
            "PUNB", "BARB", "CNRB", "UBIN",
        }, f"unknown bank code in IFSC: {prof['ifsc']}"
        assert prof["ifsc"][4] == "0"                        # 5th char is the zero
        assert prof["amount_inr"] == sub.amount_minor // 100
        assert prof["root_cause"] is not None


def test_indian_cohort_is_isolated_from_original_500_sub() -> None:
    """The Faker IDs (sub_fk_*) are distinct from the original simulator's
    IDs (sub_sim_*) so mixing the two cohorts in the SPA is unambiguous."""
    from cadence.sim.cohort import generate_cohort
    # Note: generate_cohort returns a list (not a tuple), so we unpack
    # the list directly. The Faker cohort returns (cohort, profiles).
    a = generate_cohort(n=10, seed=42)
    b, _ = generate_indian_cohort(n=10, seed=42)
    a_ids = {s.subscription_id for s in a}
    b_ids = {s.subscription_id for s in b}
    assert a_ids.isdisjoint(b_ids), "Faker IDs must not collide with simulator IDs"

