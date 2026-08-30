"""Apply the Cadence mirror schema via the Supabase Management API.

Per the Supabase docs:
- Endpoint: POST https://api.supabase.com/v1/projects/{ref}/database/query
- Auth: Authorization: Bearer <sbp_... Personal Access Token>
- Body: {"query": "<sql>"}
- The PAT must have database_read or database_write permission.

After applying, the engine's cloud mirror (CLOUD_SYNC_ENABLED=true in
.env, 30s tick) will start upserting into webhook_inbox,
journeys_mirror, metrics_daily.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def main() -> int:
    project_ref = os.environ.get("SUPABASE_PROJECT_REF", "vzrasadomyrycafbzdwg")
    pat = os.environ.get("SUPABASE_PAT")
    if not pat:
        print("[error] SUPABASE_PAT not set. Create a Personal Access Token at"
              " https://supabase.com/dashboard/account/tokens and put it in"
              " your shell or Cadence/.env.")
        return 1
    schema_path = Path(__file__).resolve().parents[1] / "supabase" / "schema.sql"

    if not schema_path.is_file():
        print(f"[error] schema not found at {schema_path}")
        return 1
    sql = schema_path.read_text(encoding="utf-8")
    print(f"[ok] loaded schema ({len(sql)} chars) from {schema_path}")

    # 1. Test PAT validity
    print()
    print("[1] Test PAT validity against the Management API...")
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project_ref}",
        headers={"Authorization": f"Bearer {pat}", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
            print(f"     OK: project id={d.get('id')}, name='{d.get('name')}', region='{d.get('region')}'")
    except urllib.error.HTTPError as e:
        print(f"     FAIL: {e.code} {e.read().decode()[:200]}")
        return 2

    # 2. Apply the schema
    print()
    print("[2] Apply the schema...")
    url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    body = json.dumps({"query": sql}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"     OK: status {r.status}")
            data = r.read().decode()
            if data:
                print(f"     response: {data[:500]}")
    except urllib.error.HTTPError as e:
        print(f"     FAIL: {e.code}")
        print(f"     body: {e.read().decode()[:1000]}")
        return 3

    # 3. Verify the 3 tables now exist (use service_role JWT for read)
    print()
    print("[3] Verify the 3 mirror tables exist...")
    sb_url = f"https://{project_ref}.supabase.co"
    sr_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    req = urllib.request.Request(
        f"{sb_url}/rest/v1/?select=*",
        headers={"apikey": sr_key, "Authorization": f"Bearer {sr_key}", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            paths = list(d.get("definitions", {}).keys())
            for t in ("webhook_inbox", "journeys_mirror", "metrics_daily"):
                present = any(t in p for p in paths)
                print(f"     {'OK ' if present else 'MISS'}  table {t}")
    except urllib.error.HTTPError as e:
        print(f"     FAIL: {e.code} {e.read().decode()[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
