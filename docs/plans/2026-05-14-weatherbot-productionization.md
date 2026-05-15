# Weatherbot Productionization Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Convert the public weatherbot prototype into a secret-safe, testable, paper-first Polymarket weather trading system with guarded live execution.

**Architecture:** Keep the original scripts as legacy reference while building a package-oriented system under `weatherbot/`. The first release supports paper trading, calibrated probability/EV, risk checks, immutable logs, Telegram reports, and live-execution interfaces that are disabled until credentials and safety gates are explicitly configured.

**Tech Stack:** Python 3.11+, pytest, requests/httpx, pydantic or jsonschema for config validation, py-clob-client for Polymarket execution, web3/eth-account for wallet/RPC, SQLite/JSONL for local immutable logs, Telegram Bot API for monitoring.

---

## Operating Decision: Desktop vs Laptop

Current Hermes gateway status shows this Telegram chat is connected to the WSL machine named `CptRedd-Bot`, with Telegram home channel configured and the gateway running under systemd. For safest local operation, run Hermes Telegram gateway and the weatherbot on the same physical machine/WSL instance that will run the bot 24/7.

Recommended options:

1. **Best for local laptop trading:** install/configure Hermes gateway on the laptop WSL and make this Telegram bot/chat point to that laptop instance.
2. **Acceptable split-machine mode:** keep Telegram Hermes on the desktop, but the desktop must SSH into the laptop or call a laptop-local API. This adds networking, auth, and reliability risk.
3. **Not recommended:** bot runs on laptop while Telegram/Hermes on desktop with no remote control path. Hermes could advise but not manage or monitor the running bot.

## Safety Policy

- Never paste or commit private keys, API secrets, Telegram tokens, CLOB credentials, or RPC keys.
- `.env` is for secrets and must remain gitignored.
- Live execution remains disabled until paper trading and tests pass.
- No human approval stage is required by user request, but Stage A semi-auto must be tiny and strict: max `$1`, edge >= `15%`, spread <= `2c`, high liquidity, no correlated duplicate exposure.
- LLM/Hermes may recommend config changes and generate reports but must not autonomously increase limits.

---

## Milestone 0: Repo Baseline and Safety Scaffold

### Task 0.1: Preserve legacy scripts and create package scaffold

**Objective:** Keep original scripts untouched and create a modern package structure.

**Files:**
- Create: `weatherbot/__init__.py`
- Create: `weatherbot/strategy/__init__.py`
- Create: `weatherbot/data/__init__.py`
- Create: `weatherbot/execution/__init__.py`
- Create: `weatherbot/risk/__init__.py`
- Create: `weatherbot/reporting/__init__.py`
- Create: `weatherbot/backtest/__init__.py`
- Create: `tests/__init__.py`

**Verification:** `python -m pytest -q` should discover tests once added.

### Task 0.2: Add secret-safe environment template

**Objective:** Document required secrets without exposing values.

**Files:**
- Create: `.env.example`
- Modify: `.gitignore`

**Required variables:**
- `POLYGON_RPC_URL=`
- `WEATHERBOT_WALLET_ADDRESS=`
- `WEATHERBOT_PRIVATE_KEY=`
- `POLYMARKET_API_KEY=`
- `POLYMARKET_API_SECRET=`
- `POLYMARKET_API_PASSPHRASE=`
- `VISUAL_CROSSING_API_KEY=`
- `TELEGRAM_BOT_TOKEN=`
- `TELEGRAM_CHAT_ID=`

**Verification:** `git status --ignored` must show `.env` ignored.

### Task 0.3: Add typed config model and JSON schema

**Objective:** Validate paper/live config before any scan or trade.

**Files:**
- Create: `weatherbot/config.py`
- Create: `config/config.schema.json`
- Create: `config/default.paper.json`
- Test: `tests/test_config.py`

**Tests first:**
- Loading default paper config succeeds.
- Live mode with missing execution settings fails.
- `max_bet` must be <= `1.0` for stage A.
- `min_edge` must be >= `0.15` for stage A.
- `max_spread` must be <= `0.02` for stage A.

---

## Milestone 1: Correct Probability and EV

### Task 1.1: Implement bucket probability with distributions

**Objective:** Replace naïve `forecast inside bucket = 100%` logic.

**Files:**
- Create: `weatherbot/strategy/probability.py`
- Test: `tests/test_probability.py`

**Behaviors:**
- Normal bucket probability is CDF(high + 0.5) - CDF(low - 0.5).
- Edge bucket `<= x` uses CDF(x + 0.5).
- Edge bucket `>= x` uses 1 - CDF(x - 0.5).
- Wider sigma lowers sharp confidence.

### Task 1.2: Implement EV helpers

**Objective:** Calculate fair price, edge, EV, and Kelly safely.

**Files:**
- Create: `weatherbot/strategy/ev.py`
- Create: `weatherbot/strategy/sizing.py`
- Test: `tests/test_ev_sizing.py`

**Behaviors:**
- `edge = probability - ask_price`.
- EV accounts for binary payout cost.
- Kelly is capped by config fraction and max bet.
- No trade if probability/price invalid.

### Task 1.3: Per-city/source calibration store

**Objective:** Track realized forecast errors by city, station, source, and horizon.

**Files:**
- Create: `weatherbot/strategy/calibration.py`
- Test: `tests/test_calibration.py`

**Behaviors:**
- Defaults sigma by unit and horizon.
- Updates sigma from sufficient resolved observations.
- Refuses calibration update below minimum sample size.

---

## Milestone 2: Data Layer and Paper Trading

### Task 2.1: Weather data provider abstraction

**Objective:** Fetch forecasts and actuals behind explicit interfaces.

**Files:**
- Create: `weatherbot/data/weather.py`
- Create: `weatherbot/data/stations.py`
- Test: `tests/test_weather_parsing.py`

**Behaviors:**
- Station coordinates are explicit.
- Forecast source metadata is stored with each observation.
- Visual Crossing key is read from env/config but never logged.

### Task 2.2: Polymarket data client

**Objective:** Read Gamma/CLOB data without trading.

**Files:**
- Create: `weatherbot/data/polymarket.py`
- Test: `tests/test_polymarket_parsing.py`

**Behaviors:**
- Parse weather event slugs.
- Parse outcome buckets.
- Extract best bid/ask and spread.
- Reject markets missing liquidity or dates.

### Task 2.3: Immutable trade log

**Objective:** Store every decision and simulated/live order append-only.

**Files:**
- Create: `weatherbot/ledger.py`
- Test: `tests/test_ledger.py`

**Behaviors:**
- JSONL append-only log.
- Each entry has timestamp, run_id, decision_id, config hash.
- No secret fields permitted.

### Task 2.4: Paper broker

**Objective:** Simulate orders and fills before live trading.

**Files:**
- Create: `weatherbot/execution/orders.py`
- Test: `tests/test_paper_broker.py`

**Behaviors:**
- Limit buy fills only if ask <= limit.
- Limit sell fills only if bid >= limit.
- Tracks cash, shares, and realized/unrealized PnL.

---

## Milestone 3: Risk and Monitoring

### Task 3.1: Risk limits

**Objective:** Enforce Stage A semi-auto limits.

**Files:**
- Create: `weatherbot/risk/limits.py`
- Create: `weatherbot/risk/exposure.py`
- Test: `tests/test_risk_limits.py`

**Behaviors:**
- Max bet <= `$1`.
- Edge >= `15%`.
- Spread <= `2c`.
- Max daily loss.
- Max open positions.
- No duplicate city/date exposure.

### Task 3.2: Kill switch

**Objective:** Permit immediate stop from local file/env/Telegram command later.

**Files:**
- Create: `weatherbot/risk/kill_switch.py`
- Test: `tests/test_kill_switch.py`

**Behaviors:**
- If kill-switch file exists, no new trades.
- Existing positions can still be reconciled/reported.

### Task 3.3: Telegram reporter

**Objective:** Send reports without exposing secrets.

**Files:**
- Create: `weatherbot/reporting/telegram.py`
- Test: `tests/test_telegram_reporting.py`

**Behaviors:**
- Redacts sensitive values.
- Sends candidate/trade/error/daily summary messages.
- Can be disabled for local-only runs.

---

## Milestone 4: Live Execution Interfaces

### Task 4.1: CLOB execution wrapper

**Objective:** Add py-clob-client integration behind safety gates.

**Files:**
- Create: `weatherbot/execution/clob.py`
- Create: `weatherbot/execution/signer.py`
- Test: `tests/test_clob_safety.py`

**Behaviors:**
- Live mode refuses to start without explicit `enable_live=true`.
- Refuses orders above Stage A limits.
- Never logs private keys or API credentials.
- Dry-run mode shows exact order payload without signing.

### Task 4.2: Reconciliation

**Objective:** Compare local ledger, CLOB orders, positions, and wallet balances.

**Files:**
- Create: `weatherbot/execution/reconciliation.py`
- Test: `tests/test_reconciliation.py`

**Behaviors:**
- Detects missing fills.
- Detects local/remote position mismatch.
- Blocks new trades on reconciliation error.

---

## Milestone 5: Backtesting and Graduation Gates

### Task 5.1: Replay backtester

**Objective:** Replay saved market/weather snapshots and evaluate strategy.

**Files:**
- Create: `weatherbot/backtest/replay.py`
- Create: `weatherbot/backtest/metrics.py`
- Test: `tests/test_backtest_metrics.py`

**Metrics:**
- Realized EV vs expected EV
- Win rate
- ROI
- Max drawdown
- Sharpe-like return/stdev
- Exposure by city/source/horizon

### Task 5.2: Stage B graduation report

**Objective:** Prevent controlled autonomous mode until objective thresholds are met.

**Files:**
- Create: `weatherbot/graduation.py`
- Test: `tests/test_graduation.py`

**Required gates:**
- 100+ live trades.
- Positive realized EV.
- Drawdown within configured limit.
- No reconciliation errors.
- Order fill logic proven.

---

## Local Laptop Deployment Plan

### Task 6.1: Local service runner

**Objective:** Run continuously on laptop without VPS.

**Files:**
- Create: `scripts/run_paper.sh`
- Create: `scripts/run_live_stage_a.sh`
- Create: `docs/local-laptop-runbook.md`

**Windows/WSL note:** If running inside WSL on a laptop, WSL must stay awake. Configure Windows power settings so sleep does not kill the bot. For true 24/7, use a VPS later.

### Task 6.2: Monitoring cron/report

**Objective:** Send daily reports and error summaries.

**Files:**
- Create: `scripts/daily_report.py`
- Create: `docs/monitoring.md`

---

## Commit Plan

1. `docs: add weatherbot productionization plan`
2. `chore: add package scaffold and secret-safe env template`
3. `feat: add config validation for paper and stage-a live modes`
4. `feat: add calibrated probability and ev modules`
5. `feat: add paper broker and immutable ledger`
6. `feat: add risk limits and kill switch`
7. `feat: add telegram reporting`
8. `feat: add guarded clob execution interface`
9. `feat: add reconciliation and backtesting`
10. `docs: add local laptop runbook`

## Immediate Next Step

Implement Milestone 0 using strict TDD where production code is involved. Do not implement live execution yet. Do not request or store real secrets yet.
