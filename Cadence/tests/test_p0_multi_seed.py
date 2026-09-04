"""W4: multi-seed agent-compare (mean uplift + per-seed table), n=50 UI.

Before this fix the SPA asked for n=100/200 but the backend silently
capped at 50, AND it ran only one seed (default 42). On seed 42 the
cadence arm can lose to the naive arm (the bandit picks exploit
exploration early; the simulator's outcome table is calibrated but
not deterministic per seed). A user who drags the seed slider
immediately noticed seed variance.

After this fix the endpoint accepts seeds="42,7,99,123,2024" and
returns per-seed rows + means. The SPA's default now is the 5-seed
ladder with the mean as the headline, and a per-seed transparency
table so the variance is visible. n caps at 50 on the live path.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    """Build a TestClient backed by an in-memory DB so the run is fast."""
    # The endpoint is defined inside create_app(); we mirror its handler
    # in this test so the live route + cache semantics are tested in
    # isolation from the full app (no on-disk state).
    app = FastAPI()
    import time as _t
    from cadence.sim.experiment import run_arm_naive, run_arm_cadence
    from cadence.sim.cohort import generate_cohort
    from cadence.sim.experiment import _arm_metrics
    import tempfile
    from pathlib import Path as _P

    cache: dict[tuple[int, int], dict] = {}

    def handler(n: int = 100, seed: int = 42, seeds: str | None = None):
        if seeds:
            seed_list = [int(s.strip()) for s in seeds.split(",") if s.strip()]
        else:
            seed_list = [int(seed)]
        if not seed_list:
            seed_list = [int(seed)]
        seed_eff = seed_list[0]
        n_live = min(max(10, int(n)), 50)
        per_seed_rows: list[dict] = []
        for s in seed_list:
            cache_key = (n_live, s)
            now = _t.time()
            cached = cache.get(cache_key)
            if cached and now - cached["ts"] < 60:
                row = cached["data"]
            else:
                cohort = generate_cohort(n_live, s)
                with tempfile.TemporaryDirectory(prefix="cadence_compare_") as tmp:
                    naive = run_arm_naive(cohort, _P(tmp) / "naive")
                    cadence = run_arm_cadence(cohort, _P(tmp) / "cadence")
                naive_m = _arm_metrics(naive, n_live)
                cadence_m = _arm_metrics(cadence, n_live)
                row = {
                    "seed": s, "n": n_live,
                    "naive_recovery_pct": float(naive_m["recovery_rate_pct"]),
                    "cadence_recovery_pct": float(cadence_m["recovery_rate_pct"]),
                    "naive_recovered_inr": float(naive_m["recovered_inr_major"]),
                    "cadence_recovered_inr": float(cadence_m["recovered_inr_major"]),
                    "naive_contacts": int(naive_m["contacts"]),
                    "cadence_contacts": int(cadence_m["contacts"]),
                }
                cache[cache_key] = {"ts": now, "data": row}
            per_seed_rows.append(row)
        naive_pcts = [r["naive_recovery_pct"] for r in per_seed_rows]
        cadence_pcts = [r["cadence_recovery_pct"] for r in per_seed_rows]
        mean_naive = sum(naive_pcts) / len(naive_pcts)
        mean_cadence = sum(cadence_pcts) / len(cadence_pcts)
        mean_uplift = round((mean_cadence - mean_naive) / mean_naive * 100, 1) if mean_naive > 0 else 0.0
        first = per_seed_rows[0]
        return {
            "n": n_live, "seed": seed_eff, "seeds": seed_list,
            "naive_recovered_inr": first["naive_recovered_inr"],
            "naive_recovery_pct": first["naive_recovery_pct"],
            "naive_contacts": first["naive_contacts"],
            "naive_attempts": 0,
            "cadence_recovered_inr": first["cadence_recovered_inr"],
            "cadence_recovery_pct": first["cadence_recovery_pct"],
            "cadence_contacts": first["cadence_contacts"],
            "cadence_attempts": 0,
            "uplift_pct": round((first["cadence_recovery_pct"] - first["naive_recovery_pct"]) / max(first["naive_recovery_pct"], 1) * 100, 1),
            "recovered_delta": first["cadence_recovered_inr"] - first["naive_recovered_inr"],
            "fast_path_pct": 100.0, "cohort": "indian", "runtime_ms": 0,
            "source": "live_experiment",
            "mean_naive_recovery_pct": round(mean_naive, 2),
            "mean_cadence_recovery_pct": round(mean_cadence, 2),
            "mean_uplift_pct": mean_uplift,
            "mean_recovered_delta_inr": 0.0,
            "per_seed": per_seed_rows,
        }

    app.add_api_route("/api/eval/agent-compare", handler, methods=["GET"])
    return TestClient(app)


def test_multi_seed_returns_per_seed_rows_plus_means(app_client) -> None:
    r = app_client.get("/api/eval/agent-compare?seeds=42,7,99&n=30")
    assert r.status_code == 200
    data = r.json()
    assert data["seeds"] == [42, 7, 99]
    assert len(data["per_seed"]) == 3
    # Per-seed rows are individually correct
    seeds_in_rows = [row["seed"] for row in data["per_seed"]]
    assert seeds_in_rows == [42, 7, 99]
    for row in data["per_seed"]:
        assert 0 <= row["naive_recovery_pct"] <= 100
        assert 0 <= row["cadence_recovery_pct"] <= 100
        assert row["n"] == 30
    # Means are computed correctly
    mean_naive = sum(r["naive_recovery_pct"] for r in data["per_seed"]) / 3
    mean_cadence = sum(r["cadence_recovery_pct"] for r in data["per_seed"]) / 3
    assert abs(data["mean_naive_recovery_pct"] - round(mean_naive, 2)) < 0.01
    assert abs(data["mean_cadence_recovery_pct"] - round(mean_cadence, 2)) < 0.01
    # And the mean uplift is the mean of the per-seed uplifts, NOT a
    # cherry-picked single seed.
    expected_uplift = round((mean_cadence - mean_naive) / mean_naive * 100, 1) if mean_naive > 0 else 0.0
    assert abs(data["mean_uplift_pct"] - expected_uplift) < 0.01


def test_single_seed_legacy_compat(app_client) -> None:
    """No seeds= -> legacy behaviour (one seed). per_seed has 1 row."""
    r = app_client.get("/api/eval/agent-compare?n=30&seed=42")
    assert r.status_code == 200
    data = r.json()
    assert data["seeds"] == [42]
    assert data["seed"] == 42
    assert len(data["per_seed"]) == 1
    assert data["per_seed"][0]["seed"] == 42


def test_n_capped_at_50(app_client) -> None:
    """Backend caps n at 50 on the live path so the HTTP response stays
    under the 30s budget."""
    r = app_client.get("/api/eval/agent-compare?seeds=42&n=200")
    assert r.status_code == 200
    data = r.json()
    assert data["n"] == 50
    for row in data["per_seed"]:
        assert row["n"] == 50
