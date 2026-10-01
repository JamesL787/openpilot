#!/usr/bin/env bash
# Open Google's Desktop Head Unit on this computer and project the comma into it.
#
#   starpilot-auto-dhu [--view car|mirror] [--host comma] [--port 5288] [--dhu PATH] [--synthetic] [--stop-starpilot-auto]
#
# Reuses one shared SSH connection to the comma (opened on first use, kept for
# 30 minutes) and an SSH tunnel already listening on the port. The DHU runs in
# this terminal: type its console commands here (help, screenshot FILE, tap X Y,
# focus video toggle, quit). Closing the DHU window or Ctrl-C stops the comma side.
#
# Defaults can go in ~/.config/starpilot/dhu.env (COMMA_HOST, DHU, DHU_PORT, DHU_VIEW).
# Runbook: docs/how-to/starpilot-auto-desktop-head-unit.md
set -euo pipefail

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/starpilot/dhu.env"
# shellcheck disable=SC1090
[[ -f "$CONFIG" ]] && source "$CONFIG"
HOST="${COMMA_HOST:-comma}"
PORT="${DHU_PORT:-5288}"
VIEW="${DHU_VIEW:-car}"
DHU_BIN="${DHU:-}"
STOP_STARPILOT_AUTO=0
EXTRA=()
while (($#)); do
  case "$1" in
    --view) VIEW="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --dhu) DHU_BIN="$2"; shift 2 ;;
    --synthetic) EXTRA+=(--synthetic); shift ;;
    --stop-starpilot-auto) STOP_STARPILOT_AUTO=1; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;35m[starpilot-auto-dhu]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[starpilot-auto-dhu]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ -z "$DHU_BIN" ]]; then
  for sdk in "${ANDROID_HOME:-}" "${ANDROID_SDK_ROOT:-}" "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
    [[ -n "$sdk" && -x "$sdk/extras/google/auto/desktop-head-unit" ]] && DHU_BIN="$sdk/extras/google/auto/desktop-head-unit" && break
  done
fi
[[ -x "$DHU_BIN" ]] || die "Desktop Head Unit not found; set DHU=/path/to/desktop-head-unit in $CONFIG or pass --dhu"
[[ "$VIEW" == car || "$VIEW" == mirror ]] || die "--view must be car or mirror"

SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-starpilot-%r@%h:%p" -o ControlPersist=30m
          -o ServerAliveInterval=15 -o ConnectTimeout=8)
remote() { ssh "${SSH_OPTS[@]}" "$HOST" "$@"; }
REMOTE_PY='cd /data/openpilot && PYTHONPATH=/data/openpilot /usr/local/venv/bin/python'
# The tool this script starts (always with --port), plus ones started by hand on the default port.
TOOL_MATCH="dhu_[d]evice\.py --port $PORT( |$)"
[[ "$PORT" == 5288 ]] && TOOL_MATCH="dhu_[d]evice\.py( --port 5288( |$)| --view [a-z]+| --synthetic|$)"

# 1. Shared SSH connection.
if ssh "${SSH_OPTS[@]}" -O check "$HOST" 2>/dev/null; then
  say "reusing SSH connection to $HOST"
else
  say "connecting to ${HOST}..."
  remote true || die "cannot reach $HOST over SSH"
fi

# 2. The comma must not be projecting to a car at the same time.
state=$(remote "$REMOTE_PY -c '
from openpilot.starpilot.system.starpilot_auto.protocol import StarpilotAutoClient
from openpilot.common.params import Params
s = StarpilotAutoClient().status()
print(\"running\" if s.get(\"running\") else \"idle\", \"onroad\" if Params().get_bool(\"IsOnroad\") else \"offroad\")'" 2>/dev/null) \
  || die "could not read the comma's Starpilot Auto status"
if [[ "$state" == running* ]]; then
  ((STOP_STARPILOT_AUTO)) || die "Starpilot Auto is projecting to a car; stop it in settings or rerun with --stop-starpilot-auto"
  say "stopping the comma's Starpilot Auto session"
  remote "$REMOTE_PY -c 'from openpilot.starpilot.system.starpilot_auto.protocol import StarpilotAutoClient; StarpilotAutoClient().stop()'"
fi
[[ "$state" == *onroad ]] && say "note: the comma is onroad; the car layout ignores touch until it is offroad"

# 3. Replace any earlier DHU session on this port, then start the comma side.
remote "pkill -TERM -f '$TOOL_MATCH'; for i in \$(seq 1 20); do pgrep -f '$TOOL_MATCH' >/dev/null || exit 0; sleep 0.25; done; pkill -KILL -f '$TOOL_MATCH'; true"
# The car layout has one renderer and one frame buffer on the comma: a second car-view
# session (another port) would steal it and knock the first one back to mirror.
if [[ "$VIEW" == car ]] && remote "for i in \$(seq 1 20); do pgrep -f 'starpilot_auto\.car_[u]i' >/dev/null || exit 1; sleep 0.25; done"; then
  die "another car-view session is running on the comma; stop it first or use --view mirror"
fi
LOG="$(mktemp "${TMPDIR:-/tmp}/starpilot-auto-dhu.XXXXXX")"
remote "$REMOTE_PY -u tools/starpilot_auto/dhu_device.py --port $PORT --view $VIEW ${EXTRA[*]:-}" >"$LOG" 2>&1 &
TOOL_PID=$!
FORWARDED=0

cleanup() {
  trap - EXIT INT TERM
  remote "pkill -TERM -f '$TOOL_MATCH'" 2>/dev/null || true
  kill "$TOOL_PID" 2>/dev/null || true
  if ((FORWARDED)); then ssh "${SSH_OPTS[@]}" -O cancel -L "$PORT:127.0.0.1:$PORT" "$HOST" 2>/dev/null || true; fi
  last=$(grep '^{"state"' "$LOG" | tail -1 || true)  # the tool's 5-second status lines
  if [[ -n "$last" ]]; then
    say "last status: $(grep -o '"fps": [0-9.]*' <<<"$last" | tail -1 | cut -d' ' -f2) fps, $(grep -o '"frames_sent": [0-9]*' <<<"$last" | cut -d' ' -f2) frames sent"
  fi
  # Closing the DHU ends the session with "Head unit disconnected"; anything else is worth showing.
  error=$(grep -o '"error": "[^"]*"' "$LOG" | tail -1 | cut -d'"' -f4 || true)
  [[ -n "$error" && "$error" != *"Head unit disconnected"* ]] && say "comma side ended with: $error"
  say "stopped (comma log: $LOG)"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

for _ in $(seq 1 60); do
  grep -q "waiting for the DHU" "$LOG" && break
  kill -0 "$TOOL_PID" 2>/dev/null || { cat "$LOG" >&2; die "the comma side exited"; }
  sleep 0.5
done
grep -q "waiting for the DHU" "$LOG" || { cat "$LOG" >&2; die "the comma side did not start"; }
say "$(head -1 "$LOG")"

# 4. Tunnel: reuse an SSH forward already on the port, else add one to the shared connection.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q '^ssh'; then
  say "reusing the SSH tunnel on port $PORT"
elif lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  die "port $PORT is taken by something other than ssh; use --port"
else
  ssh "${SSH_OPTS[@]}" -O forward -L "$PORT:127.0.0.1:$PORT" "$HOST" >/dev/null || die "could not open the tunnel on port $PORT"
  FORWARDED=1
fi

# 5. The DHU, in this terminal.
say "opening the Desktop Head Unit ($VIEW view); live stats: tail -f $LOG"
cd "$(dirname "$DHU_BIN")"
./desktop-head-unit --adb="127.0.0.1:$PORT" || true
