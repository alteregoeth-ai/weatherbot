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
export WEATHERBOT_LOOP_SECONDS="${WEATHERBOT_LOOP_SECONDS:-900}"
export WEATHERBOT_ONCE="${WEATHERBOT_ONCE:-false}"
export WEATHERBOT_COMMAND="${WEATHERBOT_COMMAND:-python -m weatherbot.scan_runner --config "$WEATHERBOT_CONFIG"}"

run_once() {
  echo "[$(date --iso-8601=seconds)] weatherbot paper run starting"
  bash -lc "$WEATHERBOT_COMMAND"
  echo "[$(date --iso-8601=seconds)] weatherbot paper run finished"
}

if [[ "$WEATHERBOT_ONCE" == "true" ]]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$WEATHERBOT_LOOP_SECONDS"
done
