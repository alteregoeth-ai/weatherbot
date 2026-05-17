# Weatherbot Performance Reporting

Weatherbot uses standard Markdown reports for **Daily**, **Weekly**, and **Monthly** paper-trading reviews. The reports are generated from the append-only paper ledger and committed to GitHub for easy review over time.

## Schedule and UTC policy

- Daily report schedule: **00:05 UTC** every day.
- Daily report window: previous day from **00:00 UTC to 23:59 UTC**.
- Example: the 17 May 2026 daily report is generated and pushed at 00:05 UTC on 18 May 2026.
- Cron expression: `5 0 * * * /home/cptre/weatherbot-prod/scripts/daily_report_push.sh`.

The push target is Patrick's GitHub fork:

```bash
git push fork HEAD:prod-safety-refactor
```

## Low resource execution

The scheduled push script runs with a low resource profile:

- serial execution; no parallel test or report work
- `flock` prevents overlapping report jobs
- `nice -n 10` lowers CPU priority
- `ionice -c2 -n7` lowers disk I/O priority
- BLAS/threading environment variables are pinned to `1`

## Commands

Generate the previous daily report manually:

```bash
python scripts/performance_report.py --period daily --ledger data/paper_trades.jsonl --output-dir reports/performance
```

Generate weekly and monthly reports manually:

```bash
python scripts/performance_report.py --period weekly --ledger data/paper_trades.jsonl --output-dir reports/performance
python scripts/performance_report.py --period monthly --ledger data/paper_trades.jsonl --output-dir reports/performance
```

Run the low-resource daily generation + GitHub push script:

```bash
scripts/daily_report_push.sh
```

## Standard report template

Each Daily, Weekly, and Monthly report uses the same sections so performance is easy to compare:

1. Title and UTC period window
2. Mode and resource profile
3. Executive Summary
   - decisions
   - approved
   - rejected
   - fills
   - order rejections
   - errors
4. Performance Metrics
   - approval rate
   - fill rate
   - average edge
   - total staked
   - realized PnL
   - open positions
5. Exposure by City
6. Review Notes

## Review cadence

- **Daily**: check bot health, fills, rejections, and errors.
- **Weekly**: compare approval/fill rates and exposure concentration.
- **Monthly**: decide whether to keep paper sizing, tighten rules, or prepare for the next graduation gate.
