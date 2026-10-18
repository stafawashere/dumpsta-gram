#!/bin/bash
# Run the engine gates in parallel, one log each under engine/logs/, print exit codes and timings.
# Usage: client-app/scripts/engine-gates.sh [tag]
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${1:-gates}"
cd "$ROOT/engine" || exit 2
mkdir -p logs
run() { # name, command...
   local name="$1"; shift
   local start=$SECONDS
   "$@" > "logs/$name-$TAG.log" 2>&1
   echo "$name exit $? in $((SECONDS - start))s" >> "logs/gates-$TAG.summary"
}
: > "logs/gates-$TAG.summary"
run pytest uv run pytest -q &
run mypy uv run mypy &
run ruff-check uv run ruff check &
run ruff-format uv run ruff format --check &
run provenance bash -c "cd '$ROOT' && uv run --no-project python skills/reverse-engineer/scripts/check_provenance.py" &
wait
cat "logs/gates-$TAG.summary"
for n in pytest mypy ruff-check ruff-format provenance; do
   echo "-- $n: $(tail -1 "logs/$n-$TAG.log")"
done
