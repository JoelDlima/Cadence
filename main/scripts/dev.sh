#!/usr/bin/env bash
# Cadence one-command dev environment.
# Usage:  ./main/scripts/dev.sh   (or:  bash main/scripts/dev.sh)
#
# Brings up:  FastAPI on :8000, Vite dev server on :3000
# Requires:   Python 3.12+, Node 20+, pip, npm
# Side effects: creates main/.venv, main/data/, frontend/node_modules on first run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT/main"

if [ ! -d ".venv" ]; then
  echo "==> creating venv (.venv)"
  python3.12 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -e ".[dev]"

if [ ! -f ".env" ]; then
  echo "==> creating default .env (no real keys; DEMO mode)"
  cp -n .env.example .env 2>/dev/null || true
fi

# Start API
echo "==> starting FastAPI on http://127.0.0.1:8000"
mkdir -p data logs
nohup python -m uvicorn revive.api.app:app --port 8000 --host 127.0.0.1 > logs/api.log 2>&1 &
API_PID=$!
echo "    API PID: $API_PID  (log: main/logs/api.log)"

# Wait for API to be ready
for i in $(seq 1 30); do
  if curl -s -f -o /dev/null http://127.0.0.1:8000/api/metrics; then
    echo "    API ready"
    break
  fi
  sleep 0.5
done

# Start frontend
cd "$REPO_ROOT/main/frontend"
if [ ! -d "node_modules" ]; then
  echo "==> installing frontend deps (this can take a minute)"
  npm install
fi
echo "==> starting Vite on http://127.0.0.1:3000"
nohup npm run dev -- --host 127.0.0.1 --port 3000 > "$REPO_ROOT/main/logs/web.log" 2>&1 &
WEB_PID=$!
echo "    Web PID: $WEB_PID  (log: main/logs/web.log)"

cat <<EOF

================================================================
 Cadence is up.

   API  : http://127.0.0.1:8000/console
   Web  : http://127.0.0.1:3000
   API logs : main/logs/api.log
   Web logs : main/logs/web.log

   Cadence is running in DEMO mode (no Razorpay keys needed).
   Add keys to main/.env to switch to LIVE mode.

 Try a synthetic failure:

   curl -X POST http://127.0.0.1:8000/api/test/inject \\
        -H "Content-Type: application/json" \\
        -d '{"subscription_id":"sub_demo","customer_id":"cust_demo",
             "failure_code":"insufficient_funds","amount_minor":49900,
             "error_description":"Simulated from dev.sh"}'

 Press Ctrl+C to stop.
================================================================
EOF

trap "echo; echo '==> stopping...'; kill $API_PID $WEB_PID 2>/dev/null || true; wait 2>/dev/null || true" INT TERM
wait
