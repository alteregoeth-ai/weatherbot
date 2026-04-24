# Weatherbot — Agent Guidelines

## Project Snapshot
Weather-market trading bot for Polymarket. Core file: `bot_v2.py`. Config: `config.json`. State + markets: `data/`. Currently in **paper trading** phase — no real money moves.

## Context-Mode Rules (mandatory)
- Shell output >20 lines → `ctx_batch_execute` + `ctx_search`. Never pipe raw output into context.
- Never use `cat` on logs or large JSON — use `ctx_execute_file` for analysis.
- `Read` is for files you are about to `Edit`. Not for analysis.

## Karpathy Rules
- **Think first:** State assumptions before coding. Ask when unclear — 1 minute of asking saves 20 minutes of rework.
- **Simplicity:** Minimum code that solves the problem. No speculative features, no future-proofing.
- **Surgical:** Touch only lines the task requires. Don't clean up adjacent code. Match existing style.
- **Verify:** Run `python bot_v2.py status` and/or `python bot_v2.py report` after any meaningful change.

## Project Conventions
- **Config:** Read `config.json` before editing. Add new fields at end. Load with `_cfg.get(key, default)` in the CONFIG block (~line 42).
- **State:** Always call `save_state(state)` after mutating the state dict.
- **Markets:** Always call `save_market(mkt)` after mutating a market dict. Files live in `data/markets/`.
- **CSV:** All trades via `log_trade_to_csv()`. Schema: `timestamp, event, city, bucket, entry_price, exit_price, cost, pnl, close_reason, balance, forecast_src`. Adding a column requires updating the header write too.
- **API:** Gamma endpoint `https://gamma-api.polymarket.com/markets/{market_id}`. Timeout `(3, 5)`. Fail gracefully — never crash on connection errors.

## Red Flags — Stop and Ask
- About to write >100 lines without running the code first
- Editing multiple files without reading them first
- Implementing something "for later" or "just in case"
