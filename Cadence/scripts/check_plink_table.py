"""Probe the Supabase cadence_payment_links table so we know whether the V7
migration still needs to be run in Studio. Prints status only, never secrets."""
from cadence.config import load_config
from cadence.cloud.plink_mirror import get_plink_mirror
import httpx

cfg = load_config()
cloud = cfg.cloud
print(f"cloud.is_live      = {cloud.is_live}")
print(f"supabase_url set   = {bool(cloud.supabase_url)}")
print(f"service_key set    = {bool(cloud.supabase_service_key)}")
if not cloud.is_live:
    raise SystemExit(0)

url = f"{cloud.supabase_url}/rest/v1/cadence_payment_links"
headers = {
    "apikey": cloud.supabase_service_key,
    "Authorization": f"Bearer {cloud.supabase_service_key}",
}
r = httpx.get(url, params={"select": "plink_id", "limit": "1"}, headers=headers, timeout=15.0)
print(f"GET cadence_payment_links -> HTTP {r.status_code}")
print(f"body: {r.text[:300]}")
if r.status_code == 200:
    print("TABLE EXISTS")
    mirror = get_plink_mirror(cfg)
    print("rows currently mirrored:", len(mirror.list_plinks(limit=200)))
else:
    print("TABLE MISSING -> run Cadence/supabase/migrations/V7__cadence_payment_links.sql "
          "in Supabase Studio > SQL Editor")
