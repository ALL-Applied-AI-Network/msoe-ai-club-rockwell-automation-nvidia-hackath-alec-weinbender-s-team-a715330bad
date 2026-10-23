#!/usr/bin/env bash
# Host the app on the MSOE GB10 for the whole team: one app and one database, next to the sim server. Run from Git Bash
# (or any bash), on the MSOE VPN, with your SSH key on the team account (SETUP.md):
#
#   app/deploy/gb10.sh deploy            build the new UI, ship HEAD (commit first), install it and restart the app
#   app/deploy/gb10.sh connect [port]    open the hosted app at http://localhost:<port>/app.html (default 8080)
#   app/deploy/gb10.sh status | logs | restart | stop
#
# connect is plain ssh, so teammates without the repo run it from any shell (PowerShell too):
#   ssh -N -L 8080:/home/hackathon11/autograsp/app.sock hackathon11@spark1.ai.msoe.edu
# The GB10 side is serve.sh, run there from the deployed copy; its header has the layout.
set -euo pipefail
HOST="${GB10_HOST:-hackathon11@spark1.ai.msoe.edu}"
SOCK=/home/hackathon11/autograsp/app.sock
SERVE="bash ~/autograsp/src/app/deploy/serve.sh"
cd "$(dirname "$0")/../.."

remote() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" "$@"; }

deploy() {
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo "Uncommitted changes aren't deployed: shipping HEAD, $(git log -1 --format='%h %s')" >&2
    fi
    (cd app/frontend && { [ -d node_modules ] || npm ci; } && npm run build)
    local tmp
    tmp="$(mktemp -d)"
    trap "rm -rf '$tmp'" EXIT  # expanded now: tmp is gone by the time the trap runs
    git archive --format=tar -o "$tmp/app.tar" HEAD
    tar -rf "$tmp/app.tar" app/frontend/dist  # gitignored: the build above
    git log -1 --format='%h %s (%cs)' > "$tmp/DEPLOYED"
    tar -rf "$tmp/app.tar" -C "$tmp" DEPLOYED
    remote 'rm -rf ~/autograsp/src.new && mkdir -p ~/autograsp/src.new && tar -xf - -C ~/autograsp/src.new' < "$tmp/app.tar"
    remote 'bash ~/autograsp/src.new/app/deploy/serve.sh install'
}

connect() {
    local port="${1:-8080}"
    echo "The hosted app: http://localhost:$port/app.html (the old UI at /). Keep this running; Ctrl+C closes it."
    exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L "$port:$SOCK" "$HOST"
}

case "${1:-}" in
    deploy) deploy ;;
    connect) connect "${2:-}" ;;
    status | logs | restart | stop) remote "$SERVE $1" ;;
    *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
