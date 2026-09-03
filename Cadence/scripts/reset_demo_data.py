"""Sweep the demo data clean, e.g. after rotating Razorpay keys.

Why you need this: payment links live in ONE Razorpay account. Rotate
RZP_KEY_ID and every `plink_...` the old account created becomes unfetchable,
so the Dashboard would show rows the new account has never heard of. This
clears the recovery data so the next demo starts from a clean ledger.

DESTRUCTIVE. It deletes rows from the local recovery tables (and, with
--cloud, from the Supabase mirror). It always copies the SQLite file to a
timestamped .bak first, so it is reversible.

What it clears:
    events, journeys, task_queue, webhook_dedupe, llm_spend,
    checkout_sessions, b2b_invoices, b2b_orgs
What it keeps:
    meta (migration bookkeeping -- deleting it would re-run migrations),
    system_flags (kill switch), customer_preferences, dnd_list,
    policy_circulars (ingested regulation, not demo data)

    .venv\\Scripts\\python.exe scripts\\reset_demo_data.py            # dry run
    .venv\\Scripts\\python.exe scripts\\reset_demo_data.py --yes      # local only
    .venv\\Scripts\\python.exe scripts\\reset_demo_data.py --yes --cloud

Safe to run while the engine is up: the API holds no cached state, every
request reads SQLite. Reload the SPA afterwards.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx

from cadence.config import load_config

# Order matters: children before parents, in case foreign keys are enforced.
CLEAR_TABLES = [
    "task_queue",
    "webhook_dedupe",
    "events",
    "journeys",
    "llm_spend",
    "checkout_sessions",
    "b2b_invoices",
    "b2b_orgs",
]
KEEP_TABLES = [
    "meta", "system_flags", "customer_preferences", "dnd_list", "policy_circulars",
]
# Supabase mirror tables, cleared only with --cloud.
CLOUD_TABLES = ["cadence_payment_links", "journeys_mirror", "metrics_daily"]

CONFIRM = "--yes" in sys.argv
WITH_CLOUD = "--cloud" in sys.argv


def counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    present = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    return {
        t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        for t in tables if t in present
    }


def clear_cloud(cfg) -> None:
    cloud = cfg.cloud
    if not cloud.is_live:
        print("\ncloud: not configured (skipping)")
        return
    headers = {
        "apikey": cloud.supabase_service_key,
        "Authorization": f"Bearer {cloud.supabase_service_key}",
        "Prefer": "return=minimal",
    }
    print("\ncloud: clearing Supabase mirror tables")
    for table in CLOUD_TABLES:
        url = f"{cloud.supabase_url}/rest/v1/{table}"
        try:
            # PostgREST refuses an unfiltered DELETE, so match every row on a
            # column that is always present.
            key = "plink_id" if table == "cadence_payment_links" else (
                "day" if table == "metrics_daily" else "journey_id"
            )
            resp = httpx.delete(url, params={key: "not.is.null"},
                                headers=headers, timeout=20.0)
            print(f"  {table:26s} HTTP {resp.status_code}"
                  + ("" if resp.is_success else f"  {resp.text[:120]}"))
        except httpx.HTTPError as exc:
            print(f"  {table:26s} FAILED {exc}")


def main() -> int:
    cfg = load_config()
    db_path = Path(cfg.db_path)
    if not db_path.is_file():
        print(f"[ok] no database at {db_path} -- already clean")
        return 0

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    before = counts(conn, CLEAR_TABLES)
    total = sum(before.values())
    print(f"db: {db_path}")
    print(f"razorpay key: {cfg.razorpay.key_id or '(keyless)'}")
    print("\nrows that would be deleted:")
    for table, n in before.items():
        print(f"  {table:26s} {n}")
    print(f"  {'TOTAL':26s} {total}")
    print("\nkept: " + ", ".join(KEEP_TABLES))

    if not CONFIRM:
        print("\nDRY RUN. Nothing was deleted. Re-run with --yes to apply"
              " (add --cloud to also clear the Supabase mirror).")
        return 0

    backup = db_path.with_name(
        f"{db_path.stem}.{datetime.now():%Y%m%d-%H%M%S}.bak")
    shutil.copy2(db_path, backup)
    print(f"\n[ok] backup written: {backup.name}")

    conn.execute("PRAGMA foreign_keys=OFF")
    for table in before:
        conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        # The running engine holds a WAL reader; reclaiming pages can wait.
        print(f"[note] VACUUM skipped ({exc}); rows are still deleted")

    after = counts(conn, CLEAR_TABLES)
    print("[ok] cleared. remaining rows: " + str(sum(after.values())))
    for table, n in after.items():
        if n:
            print(f"  WARNING {table} still has {n} rows")

    if WITH_CLOUD:
        clear_cloud(cfg)
    else:
        print("\ncloud: left untouched (pass --cloud to clear the Supabase mirror)")

    print("\nDone. Reload the SPA; the Dashboard should show zero payment links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
