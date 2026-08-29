"""Hit the live merchant summary endpoint and pretty-print."""
import urllib.request
import json
import sys

try:
    with urllib.request.urlopen('http://127.0.0.1:8000/api/merchant/summary', timeout=10) as r:
        d = json.loads(r.read())
    print('total:', d['total_journeys'], 'recovered:', d['total_recovered'], 'rate:', d['recovery_rate_pct'], '%')
    print('rec INR:', d['recovered_amount_inr'])
    print('--- top root causes ---')
    for c in d['top_root_causes'][:5]:
        print(' ', c)
    print('--- state dist ---')
    print(' ', d['state_distribution'])
    print('--- intervention performance ---')
    for i in d['intervention_performance'][:5]:
        print(' ', i)
    print('--- avg time to recover (min) ---')
    print(' ', d['avg_time_to_recover_minutes'])
except Exception as e:
    print('ERROR:', e)
    sys.exit(1)
