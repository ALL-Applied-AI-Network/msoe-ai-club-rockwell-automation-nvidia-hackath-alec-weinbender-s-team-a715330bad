#!/usr/bin/env bash
# The hosted app on the MSOE GB10, run there as hackathon11. gb10.sh calls it over ssh; on the GB10 you can too:
#   bash ~/autograsp/src/app/deploy/serve.sh status | logs | start | stop | restart
#
# ~/autograsp/
#   src/       the deployed commit (DEPLOYED says which); src.old/ the one before, for going back by hand
#   venv/      its Python environment (uv, backend only)
#   data/      DATA_DIR: database, uploads, outputs and the logs. Kept across deploys
#   app.env    the app's settings, written on the first install. Edit them there, then restart
#   app.sock   where the API listens. Not a TCP port: other teams can reach every 127.0.0.1 port here, but home is 0700,
#              so only this account can open the socket. Teammates reach it through ssh -L (gb10.sh connect)
#
# The GPU page's GB10 session runs here too, unchanged: it reaches this machine by ssh to 127.0.0.1 with a key of its own,
# starts the sim server in ~/repo if it isn't running (port 9011, the same one laptops' sessions use) and forwards it to
# SIM_URL's port. Someone connects it once on the GPU page; it stays connected until someone disconnects it.
set -euo pipefail
ROOT="$HOME/autograsp"
SOCK="$ROOT/app.sock"
PID="$ROOT/app.pid"
LOG="$ROOT/data/api.log"
SELF_KEY="$HOME/.ssh/autograsp_self"
export PATH="$HOME/.local/bin:$PATH" UV_PROJECT_ENVIRONMENT="$ROOT/venv"

healthy() { curl -sf -m 5 --unix-socket "$SOCK" http://app/health > /dev/null 2>&1; }
running() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2> /dev/null; }

install() {  # gb10.sh has extracted the new commit into src.new
    rm -rf "$ROOT/src.old"
    if [ -d "$ROOT/src" ]; then mv "$ROOT/src" "$ROOT/src.old"; fi
    mv "$ROOT/src.new" "$ROOT/src"
    mkdir -p "$ROOT/data"
    (cd "$ROOT/src" && uv sync --frozen --no-dev --package backend)  # after the move: the install points at src/
    self_key
    [ -f "$ROOT/app.env" ] || write_env
    restart
}

self_key() {  # the GPU session's ssh to this machine; the key only works from here
    [ -f "$SELF_KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "autograsp app on spark1, to itself" -f "$SELF_KEY"
    grep -qF "$(cut -d' ' -f2 "$SELF_KEY.pub")" "$HOME/.ssh/authorized_keys" ||
        echo "from=\"127.0.0.1,::1\" $(cat "$SELF_KEY.pub")" >> "$HOME/.ssh/authorized_keys"
    ssh -i "$SELF_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new 127.0.0.1 true
}

write_env() {
    cat > "$ROOT/app.env" << EOF
# The hosted app's settings (every variable: .env.example). Restart after editing: bash $ROOT/src/app/deploy/serve.sh restart
DATA_DIR=$ROOT/data
SIM_BACKEND=http
SIM_URL=http://127.0.0.1:19011
COMPUTE_BACKENDS=gb10
COMPUTE_GB10_HOST=127.0.0.1
COMPUTE_SSH="ssh -i $SELF_KEY"
EOF
}

start() {
    if running && healthy; then echo "Already running (pid $(cat "$PID"))"; return; fi
    rm -f "$SOCK"
    (
        cd "$ROOT/src"
        set -a
        . "$ROOT/app.env"
        set +a
        setsid nohup "$ROOT/venv/bin/uvicorn" api.main:app --uds "$SOCK" < /dev/null >> "$LOG" 2>&1 &
        echo $! > "$PID"
    )
    for _ in $(seq 60); do
        if healthy; then status; return; fi
        running || break
        sleep 1
    done
    echo "The app didn't start; the end of $LOG:" >&2
    tail -n 30 "$LOG" >&2
    exit 1
}

stop() {  # the API only: job workers and the GPU session are their own processes and carry on (the API picks them up)
    running || { rm -f "$PID"; return; }
    local pid
    pid="$(cat "$PID")"
    kill "$pid"
    for _ in $(seq 15); do kill -0 "$pid" 2> /dev/null || break; sleep 1; done
    kill -KILL "$pid" 2> /dev/null || true
    rm -f "$PID" "$SOCK"
}

restart() { stop; start; }

status() {
    echo "Deployed: $(cat "$ROOT/src/DEPLOYED" 2> /dev/null || echo nothing)"
    if running && healthy; then echo "Running (pid $(cat "$PID")) on $SOCK"; else echo "Not running"; fi
    curl -sf -m 5 --unix-socket "$SOCK" http://app/api/compute/sessions?limit=1 2> /dev/null | head -c 400 && echo || true
}

logs() { tail -n "${1:-60}" "$LOG"; }

case "${1:-}" in
    install | start | stop | restart | status | logs) "$@" ;;
    *) sed -n '2,3p' "$0"; exit 2 ;;
esac
