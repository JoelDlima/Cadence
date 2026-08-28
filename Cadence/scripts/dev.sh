#!/usr/bin/env bash
# Cadence one-command dev launcher (POSIX).
# Brings up: FastAPI on :8000, Vite dev server on :3000.
# Press Ctrl+C in this terminal to stop both.
#
# Usage:  ./Cadence/scripts/dev.sh
#    or:  bash Cadence/scripts/dev.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "===================================================="
echo "Cadence dev launcher"
echo "===================================================="
echo "Backend : http://127.0.0.1:8000  (FastAPI + uvicorn)"
echo "Frontend: http://127.0.0.1:3000  (Vite + React)"
echo

# Ensure the venv exists.
if [ ! -x "Cadence/.venv/Scripts/python.exe" ] && [ ! -x "Cadence/.venv/bin/python" ]; then
  echo "[setup] creating Cadence/.venv ..."
  python3 -m venv "Cadence/.venv"
fi

# Pick the right python executable.
if [ -x "Cadence/.venv/Scripts/python.exe" ]; then
  PY="Cadence/.venv/Scripts/python.exe"
elif [ -x "Cadence/.venv/bin/python" ]; then
  PY="Cadence/.venv/bin/python"
else
  echo "[error] no python in Cadence/.venv"
  exit 1
fi

# Ensure the Python package is editable-installed.
echo "[setup] ensuring Cadence is pip-installed (editable) ..."
"$PY" -m pip install -q -e "Cadence.[dev]"

# Ensure a .env exists.
if [ ! -f "Cadence/.env" ]; then
  echo "[setup] copying Cadence/.env.example to Cadence/.env"
  cp -n "Cadence/.env.example" "Cadence/.env" || true
fi

# Make sure the logs dir exists.
mkdir -p "Cadence/logs"

# Start backend in the background.
echo
echo "Starting backend (FastAPI) on :8000 ..."
nohup "$PY" -m uvicorn revive.api.app:app --host 127.0.0.1 --port 8000 --app-dir Cadence > "Cadence/logs/api.out" 2> "Cadence/logs/api.err" &
API_PID=$!

# Start frontend in the background.
echo "Starting frontend (Vite) on :3000 ..."
pushd "Cadence/frontend" >/dev/null
nohup npm run dev -- --host 127.0.0.1 --port 3000 > "../logs/web.out" 2> "../logs/web.err" &
WEB_PID=$!
popd >/dev/null

# Wait for backend to be ready.
echo
echo "Waiting for backend ..."
for i in $(seq 1 30); do
  if curl -s -f -o /dev/null http://127.0.0.1:8000/api/status; then
    break
  fi
  sleep 0.5
done

echo
echo "Cadence is up."
echo "  API PID: $API_PID  (log: Cadence/logs/api.log)"
echo "  Web PID: $WEB_PID  (log: Cadence/logs/web.log)"
echo
echo "Try:"
echo "  curl http://127.0.0.1:8000/api/status"
echo "  open http://127.0.0.1:3000 in your browser"
echo

# Seed a sample journey so the SPA has something to show.
"$PY" "Cadence/scripts/seed.py" || true

# On Ctrl+C, kill both.
trap "echo; echo '==> stopping...'; kill $API_PID $WEB_PID 2>/dev/null || true; wait 2>/dev/null || true" INT TERM
wait
