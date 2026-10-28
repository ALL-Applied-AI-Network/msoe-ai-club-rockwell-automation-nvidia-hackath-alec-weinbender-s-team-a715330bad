#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo 'Usage: bash app/backend/scripts/run_benchmark.sh CONFIG OUTPUT [SIM_URL]' >&2
    exit 2
fi

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
printf 'Started UTC: %s\n' "$(date -u +%FT%TZ)"
printf 'CPU thread limits: OMP=2 MKL=2 OPENBLAS=2\n'
runner_exit=0
"$ROOT/.venv/bin/python" app/backend/scripts/benchmark.py "$1" \
    --backend http --sim-url "${3:-http://127.0.0.1:9011}" --output "$2" || runner_exit=$?
printf 'Finished UTC: %s; exit=%s\n' "$(date -u +%FT%TZ)" "$runner_exit"
printf '%s\n' "$runner_exit" > "$2.exit-code"
exit "$runner_exit"
