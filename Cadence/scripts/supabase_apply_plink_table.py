"""Apply V7__cadence_payment_links.sql to Supabase (Phase 4).

Two paths, in order of preference:

1. Automatic, if SUPABASE_PAT is set (a Personal Access Token from
   https://supabase.com/dashboard/account/tokens with database_write):
       .venv\\Scripts\\python.exe scripts\\supabase_apply_plink_table.py
   PostgREST cannot run DDL, so the Management API's /database/query endpoint
   is the only key-based way to create a table -- same approach as
   scripts/supabase_apply_schema.py.

2. Manual, if you have no PAT: the script prints the SQL and the Studio URL.
   Paste it into Supabase Studio -> SQL Editor and hit Run. The migration is
   idempotent (CREATE TABLE IF NOT EXISTS), so re-running is safe.

Either way the engine keeps working without the table: the mirror logs the
failure and every recovery drill still succeeds. GET /api/cloud/plinks then
reports `last_read_error` telling you the migration is missing.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

UA = "cadence-migrate/1.0"
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase" / "migrations" / "V7__cadence_payment_links.sql"
)


def _project_ref() -> str:
    explicit = os.environ.get("SUPABASE_PROJECT_REF", "").strip()
    if explicit:
        return explicit
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    # https://<ref>.supabase.co -> <ref>
    return url.split("//")[-1].split(".")[0] if url else ""


def _table_exists(project_ref: str, service_key: str) -> bool | None:
    """True/False, or None when the check itself could not run."""
    if not service_key:
        return None
    req = urllib.request.Request(
        f"https://{project_ref}.supabase.co/rest/v1/cadence_payment_links"
        "?select=plink_id&limit=1",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}",
                 "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 400):
            return False
        print(f"[warn] table check returned HTTP {exc.code}")
        return None
    except OSError as exc:
        print(f"[warn] table check failed: {exc}")
        return None


def main() -> int:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            break

    if not MIGRATION.is_file():
        print(f"[error] migration not found at {MIGRATION}")
        return 1
    sql = MIGRATION.read_text(encoding="utf-8")
    project_ref = _project_ref()
    if not project_ref:
        print("[error] SUPABASE_URL (or SUPABASE_PROJECT_REF) is not set in .env")
        return 1
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    print(f"[ok] project ref: {project_ref}")
    print(f"[ok] migration:   {MIGRATION.name} ({len(sql)} chars)")

    before = _table_exists(project_ref, service_key)
    print(f"[ok] cadence_payment_links exists already: {before}")
    if before is True:
        print("\nNothing to do.")
        return 0

    pat = os.environ.get("SUPABASE_PAT", "").strip()
    if not pat:
        print("\n[manual] SUPABASE_PAT is not set, so this script cannot run DDL for you.")
        print("Open the SQL editor and run the statement below:")
        print(f"  https://supabase.com/dashboard/project/{project_ref}/sql/new")
        print("-" * 72)
        print(sql)
        print("-" * 72)
        print("Then re-run this script (or scripts/check_plink_table.py) to confirm.")
        return 2

    print("\n[1] applying via the Management API...")
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project_ref}/database/query",
        data=json.dumps({"query": sql}).encode("utf-8"),
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json",
                 "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"    OK: HTTP {resp.status} {resp.read().decode()[:300]}")
    except urllib.error.HTTPError as exc:
        print(f"    FAIL: HTTP {exc.code} {exc.read().decode()[:600]}")
        return 3

    print("\n[2] verifying...")
    after = _table_exists(project_ref, service_key)
    print(f"    cadence_payment_links exists: {after}")
    return 0 if after is not False else 4


if __name__ == "__main__":
    sys.exit(main())
