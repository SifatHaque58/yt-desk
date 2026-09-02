#!/usr/bin/env bash
# Country-native YouTube desk.
#
#   ./start.sh
#   SCOUT_TUNNEL=1 ./start.sh
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"
STAMP="$VENV/.deps-installed"

if [ ! -d "$VENV" ]; then
  echo "==> creating $VENV"
  "$PY" -m venv "$VENV"
fi

if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "==> installing dependencies"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt
  touch "$STAMP"
fi

if [ "${SCOUT_TUNNEL:-0}" != "0" ]; then
  export SCOUT_PROXY="${SCOUT_PROXY:-http://127.0.0.1:${SCOUT_PROXY_PORT:-8118}}"
  if ! nc -z 127.0.0.1 "${SCOUT_PROXY_PORT:-8118}" 2>/dev/null; then
    echo "==> tunnel proxy on 127.0.0.1:${SCOUT_PROXY_PORT:-8118}"
    "$VENV/bin/python" tools/tun-http-proxy.py --port "${SCOUT_PROXY_PORT:-8118}" &
    PROXY_PID=$!
    trap 'kill "$PROXY_PID" 2>/dev/null || true' EXIT
    for _ in $(seq 1 20); do
      if nc -z 127.0.0.1 "${SCOUT_PROXY_PORT:-8118}" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    if ! nc -z 127.0.0.1 "${SCOUT_PROXY_PORT:-8118}" 2>/dev/null; then
      echo "tunnel proxy did not start listening — not starting a leaked desk" >&2
      exit 1
    fi
  else
    echo "==> tunnel proxy already listening on ${SCOUT_PROXY_PORT:-8118}"
  fi
fi

echo "==> yt-desk on http://127.0.0.1:5056  (Ctrl+C to stop)"
"$VENV/bin/python" app.py
