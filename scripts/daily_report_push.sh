#!/usr/bin/env bash
# Cron schedule: 5 0 * * * /home/cptre/weatherbot-prod/scripts/daily_report_push.sh
# Generates the previous UTC day's paper-performance report at 00:05 UTC and pushes it to GitHub.
# Core commands: performance_report.py --period daily ; git push fork HEAD:prod-safety-refactor

set -euo pipefail

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONUNBUFFERED=1

ROOT_DIR="${WEATHERBOT_ROOT:-/home/cptre/weatherbot-prod}"
LEDGER="${WEATHERBOT_LEDGER:-data/paper_trades.jsonl}"
OUTPUT_DIR="${WEATHERBOT_REPORT_DIR:-reports/performance}"
REMOTE="${WEATHERBOT_GIT_REMOTE:-fork}"
BRANCH="${WEATHERBOT_GIT_BRANCH:-prod-safety-refactor}"
LOCK_FILE="${WEATHERBOT_LOCK_FILE:-/tmp/weatherbot-daily-report.lock}"

cd "$ROOT_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another Weatherbot daily report job is already running; exiting."
  exit 0
fi

report_path=$(nice -n 10 ionice -c2 -n7 python scripts/performance_report.py \
  --period daily \
  --ledger "$LEDGER" \
  --output-dir "$OUTPUT_DIR")

echo "Generated $report_path"
git add "$report_path"
if git diff --cached --quiet; then
  echo "No report changes to commit"
  exit 0
fi

git commit -m "chore(reports): add daily weatherbot performance report"
git push "$REMOTE" HEAD:"$BRANCH"
