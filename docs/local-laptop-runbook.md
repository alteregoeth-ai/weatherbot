# Local Laptop Runbook

This runbook keeps Weatherbot local-first while paper trading and Stage A safety gates are proven. It assumes WSL on a Windows laptop or desktop.

## Safety rules

- Never paste private keys, API credentials, Telegram tokens, RPC keys, or wallet seed phrases into chat, docs, shell history, or committed files.
- Put local secrets only in `.env`; keep `.env` gitignored.
- Start with paper mode. Do not use live Stage A until paper trading, tests, reconciliation, and graduation gates are acceptable.
- Live Stage A remains tiny-capital only: max `$1`, edge >= `15%`, spread <= `2c`, and strict reconciliation.

## Keep WSL awake

If the bot runs inside WSL, Windows sleep or hibernation will stop the process. Before unattended runs:

1. Plug in the laptop.
2. Open Windows Power & battery settings.
3. Set sleep to **Never** while plugged in.
4. Disable hibernation for the run window if needed.
5. Keep the WSL terminal, `tmux`, or service session active.

For true 24/7 operation, move to a VPS later.

## Paper runner

Use paper mode first:

```bash
chmod +x scripts/run_paper.sh scripts/run_live_stage_a.sh
WEATHERBOT_ONCE=true scripts/run_paper.sh
```

Continuous local loop:

```bash
WEATHERBOT_LOOP_SECONDS=900 scripts/run_paper.sh
```

The script exports:

- `WEATHERBOT_MODE=paper`
- `WEATHERBOT_ENABLE_LIVE=false`
- `WEATHERBOT_CONFIG=config/default.paper.json` by default

Until a dedicated live market scan runner is wired in, the default low-resource command runs the deterministic paper-trading demo and appends to `data/paper_trades.jsonl`. You can override the command explicitly:

```bash
WEATHERBOT_COMMAND='python scripts/paper_trade.py --demo --ledger data/paper_trades.jsonl --bankroll 10 --no-telegram' WEATHERBOT_ONCE=true scripts/run_paper.sh
```

The runner uses `flock`, `nice -n 10`, `ionice -c2 -n7`, and single-threaded BLAS environment variables so it avoids overlapping or parallel-heavy work.

## Live Stage A runner

Live Stage A requires an explicit acknowledgement every time:

```bash
WEATHERBOT_CONFIRM_LIVE_STAGE_A=YES WEATHERBOT_ONCE=true scripts/run_live_stage_a.sh
```

The script refuses to start without:

```bash
WEATHERBOT_CONFIRM_LIVE_STAGE_A=YES
```

It exports:

- `WEATHERBOT_MODE=live`
- `WEATHERBOT_STAGE=stage_a`
- `WEATHERBOT_ENABLE_LIVE=true`
- `WEATHERBOT_CONFIG=config/stage_a.live.json` by default

## Recommended operating pattern

1. Pull latest repo changes.
2. Run `python -m pytest -q`.
3. Review `.env` locally without printing secrets.
4. Run one paper cycle with `WEATHERBOT_ONCE=true scripts/run_paper.sh`.
5. Run continuous paper mode in `tmux` only after the one-shot succeeds.
6. Review ledger, Telegram reports, and reconciliation before any live Stage A run.
7. For live Stage A, run one cycle first with `WEATHERBOT_CONFIRM_LIVE_STAGE_A=YES WEATHERBOT_ONCE=true scripts/run_live_stage_a.sh`.

## Stop procedure

- Press `Ctrl+C` in the runner terminal, or stop the `tmux`/service session.
- Create the configured kill-switch file before restarting if trading must remain disabled.
- Verify no new trades are opened after a reconciliation error.
