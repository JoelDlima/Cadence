"""5,000-subscriber Faker-driven Indian-cohort evaluation.

Runs the same naive-vs-Revive experiment on a Faker-generated cohort of
realistic Indian subscribers (names, UPI handles, IFSC codes via the
``hi_IN`` locale). Writes:

- ``docs/eval-metrics-large.json`` — same shape as
  ``docs/eval-metrics.json`` (the 500-sub canonical) so the
  ``/api/eval-summary`` endpoint picks it up.
- ``data/indian-cohort-profiles.json`` — Faker-only metadata (name, UPI
  handle, IFSC) for the dashboard / README headline.

The 500-sub ``docs/eval-metrics.json`` stays the canonical number the
README cites; this script produces a *secondary* number for the pitch
deck's "scaled run" slide. Determinism: same (n, seed) yields the
identical list every time.

Usage:
    python scripts/run_eval_indian.py              # default n=5000
    python scripts/run_eval_indian.py --n 1000     # smaller for CI
    python scripts/run_eval_indian.py --seed 7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revive.sim.experiment import run_experiment
from revive.sim.indian_cohort import generate_indian_cohort


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Revive eval on a 5,000-sub Faker-driven Indian cohort."
    )
    parser.add_argument("--n", type=int, default=5000, help="cohort size (default 5000)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    parser.add_argument(
        "--out-dir", default="docs", help="output dir for metrics json (default docs)"
    )
    parser.add_argument(
        "--profiles-out",
        default="data/indian-cohort-profiles.json",
        help="output path for Faker profiles (default data/indian-cohort-profiles.json)",
    )
    args = parser.parse_args()

    # Build the Faker cohort; we only need the SimSubscriber list for the
    # experiment; the profiles are written to disk for the README / dashboard.
    print(f"Generating {args.n}-sub Faker-driven Indian cohort (seed={args.seed})...")
    cohort, profiles = generate_indian_cohort(n=args.n, seed=args.seed)
    print(
        f"  cohort ready: {len(cohort)} subscribers, "
        f"{sum(1 for s in cohort if s.failure_code)} with mapped error codes, "
        f"{sum(1 for s in cohort if not s.failure_code)} with unknown codes"
    )

    # Run the experiment arm-by-arm (mirrors run_experiment's structure so
    # the same ArmResult aggregator works).
    print("Running naive arm...")
    from revive.sim.experiment import _arm_metrics, _collect_results, _run_revive_on
    import tempfile
    from revive.sim.experiment import run_arm_naive, run_arm_revive

    with tempfile.TemporaryDirectory(prefix="revive_eval_indian_") as tmp:
        naive = run_arm_naive(cohort, Path(tmp) / "naive")
        # The revive arm takes a directory; reuse the existing run_arm_revive.
        revive = run_arm_revive(cohort, Path(tmp) / "revive")
        metrics = {
            "n": len(cohort),
            "seed": args.seed,
            "naive": _arm_metrics(naive, len(cohort)),
            "revive": _arm_metrics(revive, len(cohort)),
            "uplift_pct": (
                (_arm_metrics(revive, len(cohort))["recovery_rate_pct"]
                 - _arm_metrics(naive, len(cohort))["recovery_rate_pct"])
                / max(1e-9, _arm_metrics(naive, len(cohort))["recovery_rate_pct"])
            ) * 100,
            "source": "live-faker-indian",
        }

    # Write the metrics JSON (same shape as docs/eval-metrics.json).
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "eval-metrics-large.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote metrics: {metrics_path}")

    # Write the Faker profiles (Faker-only metadata; not consumed by
    # the experiment arm loops).
    profiles_path = Path(args.profiles_out)
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    profiles_path.write_text(
        json.dumps(
            {
                "n": len(profiles),
                "seed": args.seed,
                "locale": "hi_IN",
                "profiles": profiles,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote Faker profiles: {profiles_path}")

    # One-line summary, matching the format of scripts/run_eval.py.
    naive, revive = metrics["naive"], metrics["revive"]
    print(
        f"\nEval (Faker, n={args.n} seed={args.seed}):\n"
        f"  naive   : {naive['recovered_inr_major']:.0f} INR ({naive['recovery_rate_pct']}%)\n"
        f"  revive  : {revive['recovered_inr_major']:.0f} INR ({revive['recovery_rate_pct']}%)\n"
        f"  uplift  : {metrics['uplift_pct']:+.1f}%\n"
        f"  contacts: {naive['contacts_per_recovery']} naive vs {revive['contacts_per_recovery']} revive\n"
        f"  vetoes  : {revive['vetoes']}\n"
        f"  llm     : {revive['llm_requests']}"
    )


if __name__ == "__main__":
    main()
