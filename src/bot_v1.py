#!/usr/bin/env python3
"""
Weather Trading Bot v1 — Polymarket
Simple base bot. Finds mispriced temperature markets using NWS forecasts.

Usage:
    python bot_v1.py           # Scan markets and show signals (paper mode)
    python bot_v1.py --live    # Execute trades against virtual $1,000 balance
    python bot_v1.py --reset   # Reset simulation balance
    python bot_v1.py --positions  # Show open positions
"""

import re
import json
import argparse
import requests
from datetime import datetime, timezone, timedelta

# =============================================================================
# CONFIG
# =============================================================================

with open("config.json") as f:
    _cfg = json.load(f)

ENTRY_THRESHOLD = _cfg.get("entry_threshold", 0.15)   # Buy below this price
EXIT_THRESHOLD  = _cfg.get("exit_threshold", 0.45)    # Sell above this price
MAX_TRADES      = _cfg.get("max_trades_per_run", 5)
MIN_HOURS_LEFT  = _cfg.get("min_hours_to_resolution", 2)
POSITION_PCT    = 0.05    # Flat 5% of balance per trade
SIM_BALANCE     = 1000.0  # Starting virtual balance

# Airport coordinates — match the exact stations Polymarket resolves on
LOCATIONS = {
    "nyc":     {"lat": 40.7772, "lon": -73.8726, "name": "New York City"},  # KLGA LaGuardia
    "chicago": {"lat": 41.9742, "lon": -87.9073, "name": "Chicago"},        # KORD O'Hare
    "miami":   {"lat": 25.7959, "lon": -80.2870, "name": "Miami"},          # KMIA
    "dallas":  {"lat": 32.8471, "lon": -96.8518, "name": "Dallas"},         # KDAL Love Field
    "seattle": {"lat": 47.4502, "lon": -122.3088, "name": "Seattle"},       # KSEA Sea-Tac
    "atlanta": {"lat": 33.6407, "lon": -84.4277,  "name": "Atlanta"},       # KATL Hartsfield
}

# NWS hourly endpoints per city
NWS_ENDPOINTS = {
    "nyc":     "https://api.weather.gov/gridpoints/OKX/37,39/forecast/hourly",
    "chicago": "https://api.weather.gov/gridpoints/LOT/66,77/forecast/hourly",
    "miami":   "https://api.weather.gov/gridpoints/MFL/106,51/forecast/hourly",
    "dallas":  "https://api.weather.gov/gridpoints/FWD/87,107/forecast/hourly",
    "seattle": "https://api.weather.gov/gridpoints/SEW/124,61/forecast/hourly",
    "atlanta": "https://api.weather.gov/gridpoints/FFC/50,82/forecast/hourly",
}

# Station IDs for real observations
STATION_IDS = {
    "nyc": "KLGA", "chicago": "KORD", "miami": "KMIA",
    "dallas": "KDAL", "seattle": "KSEA", "atlanta": "KATL",
}

ACTIVE_LOCATIONS = _cfg.get("locations", "nyc,chicago,miami,dallas,seattle,atlanta").split(",")
ACTIVE_LOCATIONS = [l.strip().lower() for l in ACTIVE_LOCATIONS]

MONTHS = ["january","february","march","april","may","june",
          "july","august","september","october","november","december"]

# =============================================================================
# COLORS
# =============================================================================

class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

def ok(msg):   print(f"{C.GREEN}  ✅ {msg}{C.RESET}")
def warn(msg): print(f"{C.YELLOW}  ⚠️  {msg}{C.RESET}")
def info(msg): print(f"{C.CYAN}  {msg}{C.RESET}")
def skip(msg): print(f"{C.GRAY}  ⏸️  {msg}{C.RESET}")

# =============================================================================
# SIMULATION STATE
# =============================================================================

SIM_FILE = "simulation.json"

def load_sim() -> dict:
    try:
        with open(SIM_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "balance": SIM_BALANCE,
            "starting_balance": SIM_BALANCE,
            "positions": {},
            "trades": [],
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "peak_balance": SIM_BALANCE,
        }

def save_sim(sim: dict):
    with open(SIM_FILE, "w") as f:
        json.dump(sim, f, indent=2)

def reset_sim():
    import os
    if os.path.exists(SIM_FILE):
        os.remove(SIM_FILE)
    print(f"{C.GREEN}  ✅ Simulation reset — balance back to ${SIM_BALANCE:.2f}{C.RESET}")

# =============================================================================
# NWS FORECAST
# =============================================================================

def get_forecast(city_slug: str) -> dict:
    """
    Fetch daily max temperature from NWS.
    Combines real station observations (past hours today) with
    hourly forecast (upcoming hours) to get the true daily maximum.
    """
    forecast_url = NWS_ENDPOINTS.get(city_slug)
    station_id = STATION_IDS.get(city_slug)
    daily_max = {}
    headers = {"User-Agent": "weatherbot/1.0"}

    # Real observations — what already happened today
    try:
        obs_url = f"https://api.weather.gov/stations/{station_id}/observations?limit=48"
        r = requests.get(obs_url, timeout=10, headers=headers)
        for obs in r.json().get("features", []):
            props = obs["properties"]
            time_str = props.get("timestamp", "")[:10]
            temp_c = props.get("temperature", {}).get("value")
            if temp_c is not None:
                temp_f = round(temp_c * 9/5 + 32)
                if time_str not in daily_max or temp_f > daily_max[time_str]:
                    daily_max[time_str] = temp_f
    except Exception as e:
        warn(f"Observations error for {city_slug}: {e}")

    # Hourly forecast — upcoming hours
    try:
        r = requests.get(forecast_url, timeout=10, headers=headers)
        periods = r.json()["properties"]["periods"]
        for p in periods:
            date = p["startTime"][:10]
            temp = p["temperature"]
            if p.get("temperatureUnit") == "C":
                temp = round(temp * 9/5 + 32)
            if date not in daily_max or temp > daily_max[date]:
                daily_max[date] = temp
    except Exception as e:
        warn(f"Forecast error for {city_slug}: {e}")

    return daily_max

# =============================================================================
# POLYMARKET API
# =============================================================================

def get_polymarket_event(city_slug: str, month: str, day: int, year: int):
    """Find a weather market on Polymarket by its URL slug"""
    slug = f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
    except Exception as e:
        warn(f"Polymarket API error: {e}")
    return None

# =============================================================================
# PARSING
# =============================================================================

def parse_temp_range(question: str):
    """Extract temperature range from a market question"""
    if not question:
        return None
    if "or below" in question.lower():
        m = re.search(r'(\d+)°F or below', question, re.IGNORECASE)
        if m: return (-999, int(m.group(1)))
    if "or higher" in question.lower():
        m = re.search(r'(\d+)°F or higher', question, re.IGNORECASE)
        if m: return (int(m.group(1)), 999)
    m = re.search(r'between (\d+)-(\d+)°F', question, re.IGNORECASE)
    if m: return (int(m.group(1)), int(m.group(2)))
    return None

def hours_until_resolution(event: dict) -> float:
    try:
        end_date = event.get("endDate") or event.get("end_date_iso")
        if not end_date: return 999
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        delta = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
        return max(0, delta)
    except Exception:
        return 999

# =============================================================================
# SHOW POSITIONS
# =============================================================================

def show_positions():
    sim = load_sim()
    positions = sim["positions"]
    print(f"\n{C.BOLD}📊 Open Positions:{C.RESET}")
    if not positions:
        print("  No open positions")
        return

    total_pnl = 0
    for mid, pos in positions.items():
        try:
            url = f"https://gamma-api.polymarket.com/markets/{mid}"
            r = requests.get(url, timeout=5)
            prices = json.loads(r.json().get("outcomePrices", "[0.5,0.5]"))
            current_price = float(prices[0])
        except Exception:
            current_price = pos["entry_price"]

        pnl = (current_price - pos["entry_price"]) * pos["shares"]
        total_pnl += pnl
        pnl_str = f"{C.GREEN}+${pnl:.2f}{C.RESET}" if pnl >= 0 else f"{C.RED}-${abs(pnl):.2f}{C.RESET}"
        print(f"\n  • {pos['question'][:65]}...")
        print(f"    Entry: ${pos['entry_price']:.3f} | Now: ${current_price:.3f} | "
              f"Shares: {pos['shares']:.1f} | PnL: {pnl_str}")
        print(f"    Cost: ${pos['cost']:.2f}")

    print(f"\n  Balance:      ${sim['balance']:.2f}")
    pnl_color = C.GREEN if total_pnl >= 0 else C.RED
    print(f"  Open PnL:     {pnl_color}{'+'if total_pnl>=0 else ''}{total_pnl:.2f}{C.RESET}")
    print(f"  Total trades: {sim['total_trades']} | W/L: {sim['wins']}/{sim['losses']}")

# =============================================================================
# MAIN STRATEGY
# =============================================================================

def run(dry_run: bool = True):
    print(f"\n{C.BOLD}{C.CYAN}🌤  Weather Trading Bot v1{C.RESET}")
    print("=" * 50)

    sim = load_sim()
    balance = sim["balance"]
    positions = sim["positions"]
    trades_executed = 0
    exits_found = 0

    mode = f"{C.YELLOW}PAPER MODE{C.RESET}" if dry_run else f"{C.GREEN}LIVE MODE{C.RESET}"
    starting = sim["starting_balance"]
    total_return = (balance - starting) / starting * 100
    return_str = f"{C.GREEN}+{total_return:.1f}%{C.RESET}" if total_return >= 0 else f"{C.RED}{total_return:.1f}%{C.RESET}"

    print(f"\n  Mode:            {mode}")
    print(f"  Virtual balance: {C.BOLD}${balance:.2f}{C.RESET} (started ${starting:.2f}, {return_str})")
    print(f"  Position size:   {POSITION_PCT:.0%} of balance per trade")
    print(f"  Entry threshold: below ${ENTRY_THRESHOLD:.2f}")
    print(f"  Exit threshold:  above ${EXIT_THRESHOLD:.2f}")
    print(f"  Trades W/L:      {sim['wins']}/{sim['losses']}")

    # --- CHECK EXITS ---
    print(f"\n{C.BOLD}📤 Checking exits...{C.RESET}")
    for mid, pos in list(positions.items()):
        try:
            url = f"https://gamma-api.polymarket.com/markets/{mid}"
            r = requests.get(url, timeout=5)
            prices = json.loads(r.json().get("outcomePrices", "[0.5,0.5]"))
            current_price = float(prices[0])
        except Exception:
            continue

        if current_price >= EXIT_THRESHOLD:
            exits_found += 1
            pnl = (current_price - pos["entry_price"]) * pos["shares"]
            ok(f"EXIT: {pos['question'][:50]}...")
            info(f"Price ${current_price:.3f} >= exit ${EXIT_THRESHOLD:.2f} | PnL: +${pnl:.2f}")

            if not dry_run:
                balance += pos["cost"] + pnl
                sim["wins"] += 1 if pnl > 0 else 0
                sim["losses"] += 1 if pnl <= 0 else 0
                sim["trades"].append({
                    "type": "exit",
                    "question": pos["question"],
                    "entry_price": pos["entry_price"],
                    "exit_price": current_price,
                    "pnl": round(pnl, 2),
                    "cost": pos["cost"],
                    "closed_at": datetime.now().isoformat(),
                })
                del positions[mid]
                ok(f"Closed — PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
            else:
                skip("Paper mode — not selling")

    if exits_found == 0:
        skip("No exit opportunities")

    # --- SCAN ENTRIES ---
    print(f"\n{C.BOLD}🔍 Scanning for entry signals...{C.RESET}")

    for city_slug in ACTIVE_LOCATIONS:
        if city_slug not in LOCATIONS:
            warn(f"Unknown location: {city_slug}")
            continue

        loc_data = LOCATIONS[city_slug]
        forecast = get_forecast(city_slug)
        if not forecast:
            continue

        for i in range(0, 4):
            date = datetime.now() + timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            month = MONTHS[date.month - 1]
            day = date.day
            year = date.year

            forecast_temp = forecast.get(date_str)
            if forecast_temp is None:
                continue

            event = get_polymarket_event(city_slug, month, day, year)
            if not event:
                continue

            hours_left = hours_until_resolution(event)

            print(f"\n{C.BOLD}📍 {loc_data['name']} — {date_str}{C.RESET}")
            info(f"Forecast: {forecast_temp}°F | Resolves in: {hours_left:.0f}h")

            if hours_left < MIN_HOURS_LEFT:
                skip(f"Resolves in {hours_left:.0f}h — too soon")
                continue

            # Find matching temperature bucket
            matched = None
            for market in event.get("markets", []):
                question = market.get("question", "")
                rng = parse_temp_range(question)
                if rng and rng[0] <= forecast_temp <= rng[1]:
                    try:
                        prices = json.loads(market.get("outcomePrices", "[0.5,0.5]"))
                        yes_price = float(prices[0])
                    except Exception:
                        continue
                    matched = {
                        "market": market,
                        "question": question,
                        "price": yes_price,
                        "range": rng
                    }
                    break

            if not matched:
                skip(f"No bucket found for {forecast_temp}°F")
                continue

            price = matched["price"]
            market_id = matched["market"].get("id", "")
            question = matched["question"]

            info(f"Bucket: {question[:60]}")
            info(f"Market price: ${price:.3f}")

            if price >= ENTRY_THRESHOLD:
                skip(f"Price ${price:.3f} above threshold ${ENTRY_THRESHOLD:.2f}")
                continue

            position_size = round(balance * POSITION_PCT, 2)
            shares = position_size / price

            ok(f"SIGNAL — buying {shares:.1f} shares @ ${price:.3f} = ${position_size:.2f}")

            if market_id in positions:
                skip("Already in this market")
                continue

            if trades_executed >= MAX_TRADES:
                skip(f"Max trades ({MAX_TRADES}) reached")
                continue

            if position_size < 0.50:
                skip(f"Position size ${position_size:.2f} too small")
                continue

            if not dry_run:
                balance -= position_size
                positions[market_id] = {
                    "question": question,
                    "entry_price": price,
                    "shares": shares,
                    "cost": position_size,
                    "date": date_str,
                    "location": city_slug,
                    "forecast_temp": forecast_temp,
                    "opened_at": datetime.now().isoformat(),
                }
                sim["total_trades"] += 1
                sim["trades"].append({
                    "type": "entry",
                    "question": question,
                    "entry_price": price,
                    "shares": shares,
                    "cost": position_size,
                    "opened_at": datetime.now().isoformat(),
                })
                trades_executed += 1
                ok(f"Position opened — ${position_size:.2f} deducted from balance")
            else:
                skip("Paper mode — not buying")
                trades_executed += 1

    # Save state
    if not dry_run:
        sim["balance"] = round(balance, 2)
        sim["positions"] = positions
        sim["peak_balance"] = max(sim.get("peak_balance", balance), balance)
        save_sim(sim)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"{C.BOLD}📊 Summary:{C.RESET}")
    info(f"Balance:         ${balance:.2f}")
    info(f"Trades this run: {trades_executed}")
    info(f"Exits found:     {exits_found}")

    if dry_run:
        print(f"\n  {C.YELLOW}[PAPER MODE — use --live to simulate trades]{C.RESET}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weather Trading Bot v1")
    parser.add_argument("--live", action="store_true", help="Execute trades (updates simulation balance)")
    parser.add_argument("--positions", action="store_true", help="Show open positions")
    parser.add_argument("--reset", action="store_true", help="Reset simulation to $1000")
    args = parser.parse_args()

    if args.reset:
        reset_sim()
    elif args.positions:
        show_positions()
    else:
        run(dry_run=not args.live)
