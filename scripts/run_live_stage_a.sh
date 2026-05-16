#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${WEATHERBOT_CONFIRM_LIVE_STAGE_A:-}" != "YES" ]]; then
  echo "Refusing live Stage A: set WEATHERBOT_CONFIRM_LIVE_STAGE_A=YES after reviewing docs/local-laptop-runbook.md" >&2
  exit 2
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export WEATHERBOT_MODE=live
export WEATHERBOT_STAGE=stage_a
export WEATHERBOT_ENABLE_LIVE=true
export WEATHERBOT_CONFIG="${WEATHERBOT_CONFIG:-config/stage_a.live.json}"
export WEATHERBOT_LOOP_SECONDS="${WEATHERBOT_LOOP_SECONDS:-900}"
export WEATHERBOT_ONCE="${WEATHERBOT_ONCE:-false}"
export WEATHERBOT_COMMAND="${WEATHERBOT_COMMAND:-python -m weatherbot.live_runner --config "$WEATHERBOT_CONFIG"}"

run_once() {
  echo "[$(date --iso-8601=seconds)] weatherbot live Stage A run starting"
  bash -lc "$WEATHERBOT_COMMAND"
  echo "[$(date --iso-8601=seconds)] weatherbot live Stage A run finished"
}

if [[ "$WEATHERBOT_ONCE" == "true" ]]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$WEATHERBOT_LOOP_SECONDS"
done
