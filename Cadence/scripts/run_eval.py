"""Run the Phase D evaluation: naive baseline vs Revive machinery on one cohort."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revive.sim.experiment import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Revive evaluation experiment.")
    parser.add_argument("--n", type=int, default=500, help="cohort size (default 500)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    parser.add_argument("--out-dir", default="docs", help="output directory (default docs)")
    args = parser.parse_args()

    metrics = run_experiment(n=args.n, seed=args.seed, out_dir=args.out_dir)
    naive, revive = metrics["naive"], metrics["revive"]
    print(
        f"Eval n={args.n} seed={args.seed}: naive {naive['recovered_inr_major']:.0f} INR "
        f"({naive['recovery_rate_pct']}%) vs revive {revive['recovered_inr_major']:.0f} INR "
        f"({revive['recovery_rate_pct']}%) | uplift {metrics['uplift_pct']:+.1f}% | "
        f"contacts/rec {naive['contacts_per_recovery']} vs {revive['contacts_per_recovery']} | "
        f"vetoes {revive['vetoes']} | llm {revive['llm_requests']}"
    )


if __name__ == "__main__":
    main()
