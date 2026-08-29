"""Final-state verification: hit every PHASE endpoint, summarize."""
import urllib.request
import json
import time

endpoints = [
    ("/api/status", "Status (LIVE/DEMO + key flags)"),
    ("/api/merchant/summary", "PHASE 10 - Merchant Summary"),
    ("/api/cloud/status", "PHASE 9 - Cloud sync state"),
    ("/api/journeys", "PHASE 1 - Journeys (bandit wired)"),
    ("/api/bandit/ranked?limit=3", "PHASE 1 - Bandit ranked"),
    ("/api/metrics", "PHASE 5 - Metrics incl. RBI 18h"),
    ("/api/guardian-stats", "PHASE 5 - Guardian vetoes"),
    ("/api/eval/agent-compare?n=20&seed=42", "PHASE 2 - Agent vs Naive"),
    ("/api/flags/kill-switch", "PHASE 4 - Kill switch state"),
    ("/api/audit/verify", "PHASE 3 - Audit chain verify"),
]

print(f"{'Endpoint':<45} {'HTTP':<6} {'Sniff'}")
print("-" * 80)
for path, label in endpoints:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:8000{path}', timeout=8) as r:
            body = r.read()
            sniff = body[:120].decode("utf-8", errors="ignore").replace("\n", " ")
            print(f"{label[:43]:<45} {r.status:<6} {sniff}")
    except urllib.error.HTTPError as e:
        print(f"{label[:43]:<45} {e.code:<6} {e.reason}")
    except Exception as e:
        print(f"{label[:43]:<45} {'ERR':<6} {e}")
