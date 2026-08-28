"""Simulator calibration, cohort generation, and experiment determinism tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from random import Random

import pytest

from revive.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    ERROR_CODE_MAP,
    EXPIRED_INSTRUMENT,
    HARD_DECLINE,
    NO_FUNDS,
    RETRY_PAYDAY,
    SWITCH_METHOD,
    TIMEOUT,
    UNKNOWN,
)
from revive.sim.cohort import SIM_UNKNOWN_CODE, generate_cohort, root_cause_of, webhook_payload
from revive.sim.experiment import run_experiment
from revive.sim.outcomes import outcome_for, recovery_probability


@pytest.mark.unit
def test_recovery_table_matches_calibration() -> None:
    assert recovery_probability(NO_FUNDS, "retry", 1) == 0.38
    assert recovery_probability(NO_FUNDS, "retry", 2) == 0.22
    assert recovery_probability(NO_FUNDS, "retry", 3) == 0.12
    assert recovery_probability(NO_FUNDS, "retry", 99) == 0.12  # tail repeats
    assert recovery_probability(BANK_DOWN, "retry", 1) == 0.55
    assert recovery_probability(BANK_DOWN, "retry", 3) == 0.55  # flat
    assert recovery_probability(TIMEOUT, "link", 1) == 0.40
    assert recovery_probability(TIMEOUT, "retry", 1) == 0.30
    assert recovery_probability(CUSTOMER_ABORTED, "nudge", 1) == 0.18
    assert recovery_probability(CUSTOMER_ABORTED, "link", 1) == 0.25
    assert recovery_probability(BAD_VPA, "switch", 1) == 0.35
    assert recovery_probability(EXPIRED_INSTRUMENT, "switch", 1) == 0.30
    assert recovery_probability(HARD_DECLINE, "retry", 1) == 0.0
    assert recovery_probability(HARD_DECLINE, "link", 2) == 0.0
    assert recovery_probability(UNKNOWN, "nudge", 1) == 0.0
    assert recovery_probability(NO_FUNDS, "uncalibrated_category", 1) == 0.0


@pytest.mark.unit
def test_outcome_for_is_seed_deterministic_bool() -> None:
    draws_a = [outcome_for(Random(i), NO_FUNDS, RETRY_PAYDAY, 1) for i in range(200)]
    draws_b = [outcome_for(Random(i), NO_FUNDS, RETRY_PAYDAY, 1) for i in range(200)]
    assert draws_a == draws_b
    assert all(isinstance(draw, bool) for draw in draws_a)
    hard = [outcome_for(Random(i), HARD_DECLINE, SWITCH_METHOD, 1) for i in range(100)]
    assert not any(hard)


def test_cohort_is_deterministic_and_realistic() -> None:
    first = generate_cohort(n=80, seed=7)
    second = generate_cohort(n=80, seed=7)

    assert first == second
    assert len(first) == 80
    for subscriber in first:
        assert subscriber.subscription_id != ""
        assert subscriber.customer_id != ""
        assert 199 <= subscriber.amount_minor // 100 <= 2999
        description = subscriber.error_description.lower()
        if subscriber.failure_code is None:
            continue
        assert subscriber.failure_code in ERROR_CODE_MAP
        assert root_cause_of(subscriber) == ERROR_CODE_MAP[subscriber.failure_code]
        assert description != ""
    unknowns = [s for s in first if s.failure_code is None]
    assert all(root_cause_of(s) == UNKNOWN for s in unknowns)


def test_webhook_payload_uses_simulator_code_for_unknowns() -> None:
    unknown = next(s for s in generate_cohort(n=400, seed=5) if s.failure_code is None)

    payload = webhook_payload(unknown)

    assert payload["failure_code"] == SIM_UNKNOWN_CODE
    assert payload["currency"] == "INR"
    assert payload["amount_minor"] == unknown.amount_minor


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (NO_FUNDS, 0.45),
        (BANK_DOWN, 0.12),
        (TIMEOUT, 0.10),
        (CUSTOMER_ABORTED, 0.12),
        (HARD_DECLINE, 0.06),
        (BAD_VPA, 0.07),
        (EXPIRED_INSTRUMENT, 0.05),
    ],
)
def test_cohort_mix_within_tolerance(cause: str, expected: float) -> None:
    cohort = generate_cohort(n=4000, seed=11)
    observed = sum(1 for s in cohort if root_cause_of(s) == cause) / len(cohort)

    assert abs(observed - expected) < 0.05


def test_run_experiment_produces_artifacts_under_budget(tmp_path: Path) -> None:
    started = time.monotonic()

    metrics = run_experiment(n=60, seed=7, out_dir=tmp_path)
    elapsed = time.monotonic() - started

    report = (tmp_path / "eval-report.md").read_text(encoding="utf-8")
    assert (tmp_path / "eval-metrics.json").exists()
    assert elapsed < 60
    assert "INR" in report
    assert "naive" in report
    assert "revive" in report
    assert metrics["revive"]["recovered_inr_major"] >= 0
    assert metrics["revive"]["llm_requests"] == 0
    assert isinstance(metrics["uplift_pct"], float)


def test_rerun_same_seed_is_byte_identical(tmp_path: Path) -> None:
    run_one = tmp_path / "one"
    run_two = tmp_path / "two"

    run_experiment(n=60, seed=7, out_dir=run_one)
    run_experiment(n=60, seed=7, out_dir=run_two)

    first = (run_one / "eval-metrics.json").read_bytes()
    second = (run_two / "eval-metrics.json").read_bytes()
    assert first == second
    parsed = json.loads(first)
    assert parsed["seed"] == 7
    assert parsed["n"] == 60
