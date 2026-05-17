#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export WEATHERBOT_MODE=paper
export WEATHERBOT_STAGE=paper
export WEATHERBOT_ENABLE_LIVE=false
export WEATHERBOT_CONFIG="${WEATHERBOT_CONFIG:-config/default.paper.json}"
export WEATHERBOT_LEDGER="${WEATHERBOT_LEDGER:-data/paper_trades.jsonl}"
export WEATHERBOT_BANKROLL="${WEATHERBOT_BANKROLL:-10}"
export WEATHERBOT_LOOP_SECONDS="${WEATHERBOT_LOOP_SECONDS:-900}"
export WEATHERBOT_ONCE="${WEATHERBOT_ONCE:-false}"
export WEATHERBOT_LOCK_FILE="${WEATHERBOT_LOCK_FILE:-/tmp/weatherbot-paper.lock}"
export WEATHERBOT_COMMAND="${WEATHERBOT_COMMAND:-python scripts/paper_trade.py --demo --config '$WEATHERBOT_CONFIG' --ledger '$WEATHERBOT_LEDGER' --bankroll '$WEATHERBOT_BANKROLL' --no-telegram}"

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONUNBUFFERED=1

run_once() {
  echo "[$(date --iso-8601=seconds)] weatherbot low-resource paper run starting"
  exec 9>"$WEATHERBOT_LOCK_FILE"
  if ! flock -n 9; then
    echo "[$(date --iso-8601=seconds)] another paper run is active; skipping"
    return 0
  fi
  nice -n 10 ionice -c2 -n7 bash -lc "$WEATHERBOT_COMMAND"
  echo "[$(date --iso-8601=seconds)] weatherbot low-resource paper run finished"
}

if [[ "$WEATHERBOT_ONCE" == "true" ]]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$WEATHERBOT_LOOP_SECONDS"
done
