#!/usr/bin/env bash
# PhyAuth-RF: start everything with one command.
#
#   ./start.sh          start back-end + dashboard, connect receiver and transmitter
#   ./start.sh stop     stop both servers
#
# Override the detected boards with RX_PORT=/dev/cu.xxx TX_PORT=/dev/cu.yyy ./start.sh
# Logs go to logs/backend.log and logs/frontend.log. Press Ctrl+C to stop everything.

set -u
cd "$(dirname "$0")"

API=http://localhost:8000
UI=http://localhost:3000
LOGS=logs
mkdir -p "$LOGS"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m  xx\033[0m %s\n' "$*"; exit 1; }

stop_all() {
  # whatever is serving the back-end (8000) and dashboard (3000), plus their parents
  for port in 8000 3000; do
    pids=$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null)
    [ -n "$pids" ] && kill $pids 2>/dev/null
  done
  pkill -f -- "-m backend.main" 2>/dev/null
  pkill -f -- "--prefix frontend run dev" 2>/dev/null
  return 0
}

if [ "${1:-}" = "stop" ]; then
  say "Stopping PhyAuth-RF servers"
  stop_all
  ok "stopped"
  exit 0
fi

# ---------------------------------------------------------------- checks
say "Checking the project"
[ -x .venv/bin/python ] || die "Python environment missing (.venv). Create it first."
[ -d frontend/node_modules ] || { warn "installing dashboard packages (first run)"; npm --prefix frontend install >"$LOGS/npm-install.log" 2>&1 || die "npm install failed, see $LOGS/npm-install.log"; }
command -v curl >/dev/null || die "curl not found"
ok "environment ready"

# ---------------------------------------------------------------- boards
say "Looking for the boards"
RX_PORT=${RX_PORT:-$(ls /dev/cu.usbserial-* 2>/dev/null | head -1)}
TX_PORT=${TX_PORT:-$(ls /dev/cu.usbmodem* /dev/cu.wchusbserial* 2>/dev/null | head -1)}
[ -n "$RX_PORT" ] && ok "receiver    $RX_PORT" || warn "receiver (ESP32 + SRX882) not found - plug it in; the dashboard will start anyway"
[ -n "$TX_PORT" ] && ok "transmitter $TX_PORT" || warn "transmitter (ESP32-S3 + STX882) not found - clone demo will be unavailable"

# ---------------------------------------------------------------- servers
say "Stopping any old instances"
stop_all
sleep 1

say "Starting the back-end (port 8000)"
PHYAUTH_AUTO_SIMULATION=0 nohup .venv/bin/python -m backend.main >"$LOGS/backend.log" 2>&1 &
BACK_PID=$!
for _ in $(seq 1 40); do
  curl -s -m 1 "$API/api/hardware/status" >/dev/null 2>&1 && break
  kill -0 $BACK_PID 2>/dev/null || die "back-end crashed, see $LOGS/backend.log"
  sleep 0.5
done
curl -s -m 1 "$API/api/hardware/status" >/dev/null 2>&1 || die "back-end did not start, see $LOGS/backend.log"
ok "back-end running (pid $BACK_PID)"

say "Starting the dashboard (port 3000)"
nohup npm --prefix frontend run dev >"$LOGS/frontend.log" 2>&1 &
FRONT_PID=$!

# ---------------------------------------------------------------- hardware pipeline
post() { curl -s -m 10 -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }

if [ -n "$RX_PORT" ]; then
  say "Connecting the receiver"
  post /api/hardware/connect "{\"port\":\"$RX_PORT\",\"baud\":921600}" >/dev/null
  for _ in $(seq 1 20); do
    MODEL=$(curl -s -m 2 "$API/api/hardware/status" | .venv/bin/python -c \
      "import json,sys; r=json.load(sys.stdin)['receiver']; print((r.get('hello') or {}).get('model') or '')" 2>/dev/null)
    [ -n "$MODEL" ] && break
    sleep 0.5
  done
  if [ -n "${MODEL:-}" ]; then ok "receiver streaming, on-chip model $MODEL"; else warn "receiver connected but silent - press its EN button"; fi
fi

if [ -n "$TX_PORT" ]; then
  say "Connecting the transmitter"
  if post /api/attack/tx/connect "{\"port\":\"$TX_PORT\",\"baud\":115200}" | grep -q '"connected": *true'; then
    post /api/attack/tx/command '{"command":"AUTO 0"}' >/dev/null
    ok "transmitter ready (automatic presses off)"
  else
    warn "transmitter did not connect - try the other USB-C port (COM) or connect it in Attack lab"
  fi
fi

# ---------------------------------------------------------------- summary
say "Waiting for the dashboard"
for _ in $(seq 1 60); do
  curl -s -m 1 -o /dev/null "$UI" && break
  kill -0 $FRONT_PID 2>/dev/null || die "dashboard crashed, see $LOGS/frontend.log"
  sleep 1
done
curl -s -m 2 -o /dev/null "$UI" && ok "dashboard at $UI" || warn "dashboard still compiling - open $UI in a moment"

curl -s -m 3 "$API/api/models/info" "$API/api/lock/status" 2>/dev/null | .venv/bin/python -c '
import json, sys
dec = json.JSONDecoder(); s = sys.stdin.read(); i = 0; out = []
while i < len(s):
    while i < len(s) and s[i].isspace(): i += 1
    if i >= len(s): break
    o, i = dec.raw_decode(s, i); out.append(o)
if len(out) == 2:
    m, l = out[0], (out[1].get("state") or {})
    lock = ("%s, pattern %s presses, %s failures" % (l["state"], l.get("len"), l.get("fails"))
            if l.get("state") else "unknown (receiver not connected)")
    print("  laptop model %s | lock %s" % (m.get("version"), lock))
' 2>/dev/null

command -v open >/dev/null && open "$UI"

printf '\n\033[1mPhyAuth-RF is running.\033[0m  Dashboard: %s   Logs: %s/\n' "$UI" "$LOGS"
printf 'Press Ctrl+C here to stop everything (or run ./start.sh stop).\n\n'

trap 'echo; say "Stopping"; stop_all; ok "stopped"; exit 0' INT TERM
wait
