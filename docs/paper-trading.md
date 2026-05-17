# Weatherbot Paper Trading Setup

This runbook keeps execution in **paper** mode only. It writes simulated decisions and fills to `data/paper_trades.jsonl` so we can test the full risk/strategy/order path and measure performance before any live trading.

## Safety settings

Use `config/default.paper.json` for paper runs:

- `mode`: `paper`
- `execution.enable_live`: `false`
- `execution.dry_run`: `true`
- `trading.max_bet`: `$1.00`
- `trading.min_edge`: `15%`
- `trading.max_spread`: `$0.02`

Do not put private keys, API secrets, or wallet seed material in the paper ledger.

## Run a local demo paper trade

From the repo root:

```bash
python scripts/paper_trade.py --demo --ledger data/paper_trades.jsonl --bankroll 10 --no-telegram
```

Expected output includes:

- `Weatherbot Paper Trading Run`
- `Scanned`
- `Matched`
- `Approved`
- `Filled`
- the path to `data/paper_trades.jsonl`

The demo uses an in-memory NYC weather market and forecast, then appends a `decision` and `paper_fill` event to the ledger.

## Measure paper performance

```bash
python scripts/paper_performance.py --ledger data/paper_trades.jsonl
```

This reports:

- decisions
- approved / rejected counts
- fills and order rejections
- approval rate
- fill rate
- average modeled edge
- total paper stake
- realized PnL, when `daily_pnl` events exist
- open paper positions

## Daily monitoring

The existing daily monitor can also read the same paper ledger:

```bash
python scripts/daily_report.py --ledger data/paper_trades.jsonl --no-telegram
```

For Telegram delivery, configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then run without `--no-telegram` and with `--telegram`.

## Promotion rule

Stay in paper mode until the ledger shows enough sample size to judge:

- stable approval/fill rate
- no unexpected order rejections
- no secret-like fields in ledger output
- acceptable drawdown and realized PnL once markets resolve
- operator kill switch tested

Only after paper results are reviewed should any config move toward live; `execution.enable_live` must remain `false` for all paper testing.
