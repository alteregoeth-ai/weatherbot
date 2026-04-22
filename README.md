# 🌤 WeatherBet — Polymarket Weather Trading Bot

Automated weather market trading bot for Polymarket. Finds mispriced temperature outcomes using real forecast data from multiple sources across 20 cities worldwide.

No SDK. No black box. Pure Python.

---

## Versions

### `bot_v1.py` — Base Bot
The foundation. Scans 6 US cities, fetches forecasts from NWS using airport station coordinates, finds matching temperature buckets on Polymarket, and enters trades when the market price is below the entry threshold.

No math, no complexity. Just the core logic — good for understanding how the system works.

### `bot_v2.py` — Full Bot (current)
Everything in v1, plus:
- **20 cities** across 4 continents (US, Europe, Asia, South America, Oceania)
- **3 forecast sources** — ECMWF (global), HRRR/GFS (US, hourly), METAR (real-time observations)
- **Expected Value** — skips trades where the math doesn't work
- **Kelly Criterion** — sizes positions based on edge strength
- **Stop-loss + trailing stop** — 20% stop, moves to breakeven at +20%
- **Slippage filter** — skips markets with spread > $0.03
- **Self-calibration** — learns forecast accuracy per city over time
- **Full data storage** — every forecast snapshot, trade, and resolution saved to JSON

---

## How It Works

Polymarket runs markets like "Will the highest temperature in Chicago be between 46–47°F on March 7?" These markets are often mispriced — the forecast says 78% likely but the market is trading at 8 cents.

The bot:
1. Fetches forecasts from ECMWF and HRRR via Open-Meteo (free, no key required)
2. Gets real-time observations from METAR airport stations
3. Finds the matching temperature bucket on Polymarket
4. Calculates Expected Value — only enters if the math is positive
5. Sizes the position using fractional Kelly Criterion
6. Monitors stops every 10 minutes, full scan every hour
7. Auto-resolves markets by querying Polymarket API directly

---

## Why Airport Coordinates Matter

Most bots use city center coordinates. That's wrong.

Every Polymarket weather market resolves on a specific airport station. NYC resolves on LaGuardia (KLGA), Dallas on Love Field (KDAL) — not DFW. The difference between city center and airport can be 3–8°F. On markets with 1–2°F buckets, that's the difference between the right trade and a guaranteed loss.

| City | Station | Airport |
|------|---------|---------|
| NYC | KLGA | LaGuardia |
| Chicago | KORD | O'Hare |
| Miami | KMIA | Miami Intl |
| Dallas | KDAL | Love Field |
| Seattle | KSEA | Sea-Tac |
| Atlanta | KATL | Hartsfield |
| London | EGLC | London City |
| Tokyo | RJTT | Haneda |
| ... | ... | ... |

---

## Installation
```bash
git clone https://github.com/alteregoeth-ai/weatherbot
cd weatherbot
chmod +x run.sh
```

`run.sh` is the recommended entrypoint. It loads env vars from `vars.json`, uses `.venv/bin/python`, and auto-repairs/recreates `.venv` if the interpreter link is broken.

If you want to prepare the venv manually:

```bash
python3 -m venv .venv
.venv/bin/pip install requests py-clob-client eth-account
```

Create `config.json` in the project folder:
```json
{
  "balance": 10000.0,
  "max_bet": 20.0,
  "min_ev": 0.05,
  "max_price": 0.45,
  "min_volume": 2000,
  "min_hours": 2.0,
  "max_hours": 72.0,
  "kelly_fraction": 0.25,
  "max_slippage": 0.03,
  "scan_interval": 3600,
  "calibration_min": 30,
  "vc_key": "YOUR_VISUAL_CROSSING_KEY",
  "poly_signature_type": 1,
  "poly_funder": "0xYOUR_PROXY_FUNDER"
}
```

Get a free Visual Crossing API key at visualcrossing.com — used to fetch actual temperatures after market resolution.

For live trading, keep wallet/CLOB secrets in environment variables (not in `config.json`):
```bash
export POLY_PRIVATE_KEY="0x..."
export POLY_FUNDER="0x..."                # required in proxy mode (signature_type=1)
export POLY_SIGNATURE_TYPE="1"            # proxy wallet mode default
# Optional: if omitted, creds are derived at runtime
export POLY_API_KEY="..."
export POLY_SECRET="..."
export POLY_PASSPHRASE="..."
```

### Live trading from `vars.json`

If you keep secrets in a local `vars.json` file (same folder as the bot), generate the exports the bot expects:

```bash
# Load into the current shell (bash/zsh)
eval "$(python3 load_live_env.py)"

# Or point at a custom path
eval "$(python3 load_live_env.py /path/to/vars.json)"
```

Field names `load_live_env.py` accepts (see script docstring): `private_key`, `proxy_key`, `POLY_API_KEY` / `API_KEY`, `POLY_SECRET` / `SECRET`, `POLY_PASSPHRASE` / `Passphrase`, `vc_key` / `VC_KEY` (Visual Crossing), and `signature_type` (`proxy` → `1`).

Validate that required values are present (exits 1 if not):

```bash
python3 load_live_env.py --check
```

**Do not commit `vars.json`** — it contains keys. Add it to `.gitignore` locally or keep it outside the repo.

---

## Usage
```bash
./run.sh preflight   # required before enabling live mode
./run.sh run         # start the bot — scans every hour
./run.sh status      # balance and open positions
./run.sh report      # full breakdown of all resolved markets
./run.sh close-all   # manual close attempt for all open positions
```

Direct execution is also possible:

```bash
.venv/bin/python bot_v2.py [run|status|report|preflight|close-all]
```

### Notifications

`notify` integration is no longer required. Runtime events/errors are shown in console output and written to `bot.log` via the internal tee logger.

---

## Troubleshooting

### `./run.sh: ... .venv/bin/python: No such file or directory`

Cause: stale/broken `.venv` symlink (common after moving/copying the project between machines).

Fix options:

```bash
# Recommended: let run.sh self-heal
./run.sh status

# Manual repair
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install requests py-clob-client eth-account
```

### Preflight fails in live mode

Most common causes are invalid wallet values:
- `POLY_PRIVATE_KEY` must be valid hex private key.
- `POLY_FUNDER` must be a `0x` + 40 hex chars address when proxy mode is enabled.

---

## Data Storage

All data is saved to `data/markets/` — one JSON file per market. Each file contains:
- Hourly forecast snapshots (ECMWF, HRRR, METAR)
- Market price history
- Position details (entry, stop, PnL)
- Final resolution outcome

This data is used for self-calibration — the bot learns forecast accuracy per city over time and adjusts position sizing accordingly.

---

## APIs Used

| API | Auth | Purpose |
|-----|------|---------|
| Open-Meteo | None | ECMWF + HRRR forecasts |
| Aviation Weather (METAR) | None | Real-time station observations |
| Polymarket Gamma | None | Market data |
| Visual Crossing | Free key | Historical temps for resolution |

---

## Disclaimer

This is not financial advice. Prediction markets carry real risk. Run the simulation thoroughly before committing real capital.
