# Weatherbot Monitoring

Use this guide to produce local daily summaries and optional Telegram notifications without exposing secrets.

## Daily report script

Generate a local stdout report from the JSONL ledger:

```bash
python scripts/daily_report.py --ledger data/trades.jsonl --no-telegram
```

Send the summary to Telegram only when local `.env` provides credentials:

```bash
set -a
source .env
set +a
python scripts/daily_report.py --ledger data/trades.jsonl --telegram
```

Required Telegram environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Never paste Telegram tokens, private keys, API credentials, RPC URLs with keys, or wallet seed phrases into chat, docs, shell history, or committed files.

## Cron example

Run once a day from WSL with cron:

```cron
5 23 * * * cd /home/cptre/weatherbot-prod && /usr/bin/env bash -lc 'set -a; [ -f .env ] && source .env; set +a; python scripts/daily_report.py --ledger data/trades.jsonl --telegram >> logs/daily_report.log 2>&1'
```

If using Windows Task Scheduler instead, run WSL with an equivalent command and ensure Windows sleep is disabled during the scheduled window.

## Error summaries

The daily report includes:

- scanned and matched decision counts
- approved and rejected candidate counts
- filled order count
- broker/live order rejection count
- realized PnL from `daily_pnl` ledger entries
- estimated open positions from fill events
- error count and the first few redacted error messages

Error payloads are passed through secret redaction before formatting. Secret-like keys such as `token`, `api_key`, `private_key`, `secret`, and `passphrase` must never appear in report output.

## Operational checks

Before trusting a scheduled report:

1. Run `python -m pytest -q`.
2. Run `python scripts/daily_report.py --ledger data/trades.jsonl --no-telegram`.
3. Confirm the report has no secrets.
4. Confirm Telegram delivery with a small test ledger before enabling cron.
5. Verify the kill-switch path and reconciliation status before any live Stage A session.

## Failure response

If the report shows errors, reconciliation problems, or unexpected fills:

1. Stop the runner.
2. Create the kill-switch file configured for the bot.
3. Do not start new trades.
4. Inspect the ledger locally.
5. Resume only after the error and reconciliation state are clean.
