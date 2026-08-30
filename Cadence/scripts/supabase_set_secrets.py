"""Set Supabase Edge Function secrets from the local .env file.

Reads RAZORPAY_*, GROQ_API_KEY, RESEND_API_KEY, etc. from Cadence/.env
and pushes them to Supabase secrets via the management API so the Edge
Functions (webhook-collector, cadence-llm-summary) can read them at
runtime.

Usage:
  python Cadence/scripts/supabase_set_secrets.py --project-ref vzrasadomyrycafbzdwg \\
      --supabase-pat sbp_...

Requires:
  - supabase management API token (Personal Access Token from
    https://supabase.com/dashboard/account/tokens)
  - a local Cadence/.env with the keys you want to push

SECRETS: never printed, only their NAMES are echoed.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PROJECT = "vzrasadomyrycafbzdwg"
# Edge Functions on the cadence project
DEFAULT_FUNCTIONS = ["webhook-collector", "cadence-llm-summary"]
# S2: aligned with the names read by src/revive/config.py. The previous
# list used RAZORPAY_* but Cadence reads RZP_* (and SUPABASE_SERVICE_KEY
# not SUPABASE_SERVICE_ROLE_KEY), so every Razorpay + Supabase secret
# was silently skipped on a stock .env.
KEY_NAMES = [
    "RZP_KEY_ID", "RZP_KEY_SECRET", "RZP_WEBHOOK_SECRET",
    "GROQ_API_KEY", "OPENROUTER_API_KEY", "SARVAM_API_KEY",
    "GEMINI_API_KEY",
    "RESEND_API_KEY", "EMAIL_FROM",
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
    "CADENCE_ENGINE_URL", "CADENCE_ENGINE_TOKEN",
]


def _load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            out[k] = v
    return out


def _set_secret(pat: str, project: str, name: str, value: str) -> tuple[int, str]:
    url = f"https://api.supabase.com/v1/projects/{project}/secrets"
    payload = [{"name": name, "value": value}].__class__
    import json
    req = urllib.request.Request(
        url, data=json.dumps([{"name": name, "value": value}]).encode(),
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project-ref", default=DEFAULT_PROJECT)
    p.add_argument("--supabase-pat", required=True)
    p.add_argument("--env-file", default="Cadence/.env")
    p.add_argument("--functions", nargs="*", default=DEFAULT_FUNCTIONS)
    p.add_argument("--only", nargs="*", default=None,
                   help="restrict to these key names (defaults to all of KEY_NAMES)")
    args = p.parse_args()

    env_path = Path(args.env_file)
    env = _load_env(env_path)
    if not env:
        print(f"ERROR: no env vars loaded from {env_path}")
        return 1

    chosen = args.only or KEY_NAMES
    pushed = 0
    failed: list[tuple[str, str]] = []
    for key in chosen:
        value = env.get(key)
        if not value:
            print(f"skip {key} (empty)")
            continue
        status, body = _set_secret(args.supabase_pat, args.project_ref, key, value)
        if 200 <= status < 300:
            print(f"  set {key}  ({len(value)} chars)")
            pushed += 1
        else:
            print(f"  FAIL {key} -> HTTP {status} {body[:80]}")
            failed.append((key, f"HTTP {status}"))

    # Tell Supabase to restart the listed Edge Functions so the secrets
    # are picked up immediately.
    if pushed > 0 and args.functions:
        import json
        url = f"https://api.supabase.com/v1/projects/{args.project_ref}/functions/restart"
        for fn in args.functions:
            req = urllib.request.Request(
                url, data=json.dumps({"functions": [fn]}).encode(),
                headers={"Authorization": f"Bearer {args.supabase_pat}",
                          "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    print(f"  restart {fn} -> HTTP {r.status}")
            except urllib.error.HTTPError as e:
                print(f"  restart {fn} FAILED -> HTTP {e.code}")

    print(f"Done. {pushed} secrets pushed. {len(failed)} failed.")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
