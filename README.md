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
pip install requests
```

`config.json` is tracked with placeholders only. Keep real keys in `config.local.json` (ignored by git) or environment variables.

`config.json`:
```json
{
  "balance": 10000.0,
  "max_bet": 20.0,
  "min_ev": 0.1,
  "max_price": 0.45,
  "min_volume": 500,
  "min_hours": 2.0,
  "max_hours": 72.0,
  "kelly_fraction": 0.25,
  "scan_interval": 3600,
  "calibration_min": 30,
  "vc_key": "YOUR_KEY_HERE",
  "max_slippage": 0.03,
  "poly_api_key": "YOUR_POLY_API_KEY_HERE",
  "poly_secret": "YOUR_POLY_SECRET_HERE",
  "poly_passphrase": "YOUR_POLY_PASSPHRASE_HERE",
  "take_profit_pct": null
}
```

`config.local.json` example:
```json
{
  "vc_key": "REAL_VISUAL_CROSSING_KEY",
  "poly_api_key": "REAL_POLY_API_KEY",
  "poly_secret": "REAL_POLY_SECRET",
  "poly_passphrase": "REAL_POLY_PASSPHRASE"
}
```

Environment variables override both files:
`VC_KEY`, `POLY_API_KEY`, `POLY_SECRET`, `POLY_PASSPHRASE`.

---

## Usage
```bash
python bot_v2.py run        # start the bot — scans every hour
python bot_v2.py status     # balance and open positions
python bot_v2.py report     # report + extended metrics
python bot_v2.py close-all  # manually close all open positions
```

Dashboard JSON export:
```bash
python export_simulation_json.py
```

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

Never commit real API keys, secrets, passphrases, or private keys to git.
