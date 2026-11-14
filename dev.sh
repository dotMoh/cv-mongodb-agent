#!/usr/bin/env bash
# One command to run the whole app locally: backend on :8000, frontend on :5500.
#   ./dev.sh            mock data + rule planner (no Atlas, no Ollama, instant)
#   ./dev.sh live       uses .env (Atlas + Ollama)
#   ./dev.sh test       fast test suite, then the cross-track checks
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "test" ]]; then
  python3 -m pytest
  echo "--- cross-track checks (data vs backend vs frontend) ---"
  python3 -m pytest -m crosstrack || echo "Cross-track mismatches above: fix before the 2pm merge."
  exit 0
fi

if [[ "${1:-}" == "live" ]]; then
  [[ -f .env ]] || { echo "No .env. Copy .env.example to .env and fill in MONGODB_URI."; exit 1; }
  set -a; source .env; set +a
else
  export DATA_SOURCE=mock LLM_MODE="${LLM_MODE:-fallback}"
fi

trap 'kill 0' EXIT INT TERM
(cd backend && python3 -m uvicorn main:app --reload --port 8000) &
(cd frontend && python3 -m http.server 5500 >/dev/null 2>&1) &
sleep 2
echo
echo "Backend  http://localhost:8000/docs   (DATA_SOURCE=${DATA_SOURCE:-mock}, LLM_MODE=${LLM_MODE:-auto})"
echo "Frontend http://localhost:5500        (set API_BASE in frontend/app.js line 3 to talk to the backend)"
echo "Ctrl-C stops both."
wait
