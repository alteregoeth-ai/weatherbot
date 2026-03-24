#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py — WeatherBet Operations Center Dashboard Backend
=============================================================
Reads JSON files written by bot_v2.py and serves a real-time UI via
FastAPI REST endpoints, WebSocket push, and a file-watcher background task.

Usage:
    python dashboard.py [--port 8050] [--host 0.0.0.0]
"""

import json
import asyncio
import argparse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

# =============================================================================
# PATH CONSTANTS
# =============================================================================

BASE_DIR         = Path(__file__).parent
DATA_DIR         = BASE_DIR / "data"
STATE_FILE       = DATA_DIR / "state.json"
MARKETS_DIR      = DATA_DIR / "markets"
CALIBRATION_FILE = DATA_DIR / "calibration.json"

# =============================================================================
# LOCATIONS  (mirrored from bot_v2.py)
# =============================================================================

LOCATIONS = {
    "nyc":          {"lat":  40.7772, "lon":  -73.8726, "name": "New York City", "station": "KLGA", "unit": "F", "region": "us"},
    "chicago":      {"lat":  41.9742, "lon":  -87.9073, "name": "Chicago",       "station": "KORD", "unit": "F", "region": "us"},
    "miami":        {"lat":  25.7959, "lon":  -80.2870, "name": "Miami",         "station": "KMIA", "unit": "F", "region": "us"},
    "dallas":       {"lat":  32.8471, "lon":  -96.8518, "name": "Dallas",        "station": "KDAL", "unit": "F", "region": "us"},
    "seattle":      {"lat":  47.4502, "lon": -122.3088, "name": "Seattle",       "station": "KSEA", "unit": "F", "region": "us"},
    "atlanta":      {"lat":  33.6407, "lon":  -84.4277, "name": "Atlanta",       "station": "KATL", "unit": "F", "region": "us"},
    "london":       {"lat":  51.5048, "lon":    0.0495, "name": "London",        "station": "EGLC", "unit": "C", "region": "eu"},
    "paris":        {"lat":  48.9962, "lon":    2.5979, "name": "Paris",         "station": "LFPG", "unit": "C", "region": "eu"},
    "munich":       {"lat":  48.3537, "lon":   11.7750, "name": "Munich",        "station": "EDDM", "unit": "C", "region": "eu"},
    "ankara":       {"lat":  40.1281, "lon":   32.9951, "name": "Ankara",        "station": "LTAC", "unit": "C", "region": "eu"},
    "seoul":        {"lat":  37.4691, "lon":  126.4505, "name": "Seoul",         "station": "RKSI", "unit": "C", "region": "asia"},
    "tokyo":        {"lat":  35.7647, "lon":  140.3864, "name": "Tokyo",         "station": "RJTT", "unit": "C", "region": "asia"},
    "shanghai":     {"lat":  31.1443, "lon":  121.8083, "name": "Shanghai",      "station": "ZSPD", "unit": "C", "region": "asia"},
    "singapore":    {"lat":   1.3502, "lon":  103.9940, "name": "Singapore",     "station": "WSSS", "unit": "C", "region": "asia"},
    "lucknow":      {"lat":  26.7606, "lon":   80.8893, "name": "Lucknow",       "station": "VILK", "unit": "C", "region": "asia"},
    "tel-aviv":     {"lat":  32.0114, "lon":   34.8867, "name": "Tel Aviv",      "station": "LLBG", "unit": "C", "region": "asia"},
    "toronto":      {"lat":  43.6772, "lon":  -79.6306, "name": "Toronto",       "station": "CYYZ", "unit": "C", "region": "ca"},
    "sao-paulo":    {"lat": -23.4356, "lon":  -46.4731, "name": "Sao Paulo",     "station": "SBGR", "unit": "C", "region": "sa"},
    "buenos-aires": {"lat": -34.8222, "lon":  -58.5358, "name": "Buenos Aires",  "station": "SAEZ", "unit": "C", "region": "sa"},
    "wellington":   {"lat": -41.3272, "lon":  174.8052, "name": "Wellington",    "station": "NZWN", "unit": "C", "region": "oc"},
}

# =============================================================================
# IN-MEMORY STATE
# =============================================================================

balance_history: list = []          # [{ts, balance}, ...]
activity_feed: deque = deque(maxlen=100)   # recent events
previous_markets: dict = {}         # last snapshot keyed by stem
connected_clients: set = set()      # active WebSocket connections

# =============================================================================
# DATA READING HELPERS
# =============================================================================


def read_json(path: Path) -> Optional[dict]:
    """Read a JSON file; return None if missing or corrupt."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_state() -> dict:
    """Read state.json with safe defaults."""
    defaults = {
        "balance": 0.0,
        "starting_balance": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "peak_balance": 0.0,
    }
    data = read_json(STATE_FILE)
    if data is None:
        return defaults
    defaults.update(data)
    return defaults


def read_all_markets() -> dict:
    """Read all data/markets/*.json; keyed by file stem (e.g. 'nyc_2026-03-24')."""
    markets = {}
    if not MARKETS_DIR.exists():
        return markets
    for path in sorted(MARKETS_DIR.glob("*.json")):
        data = read_json(path)
        if data is not None:
            markets[path.stem] = data
    return markets


def read_calibration() -> Optional[dict]:
    """Read calibration.json; return None if missing."""
    return read_json(CALIBRATION_FILE)


def check_bot_status() -> dict:
    """Return running/stopped status by scanning processes for bot_v2.py."""
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_info", "create_time"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if any("bot_v2.py" in arg for arg in cmdline):
                mem_mb = round(proc.info["memory_info"].rss / 1024 / 1024, 1) if proc.info.get("memory_info") else 0
                uptime_s = int(datetime.now().timestamp() - proc.info.get("create_time", 0))
                return {
                    "running": True,
                    "pid": proc.info["pid"],
                    "cpu_percent": proc.info.get("cpu_percent", 0.0),
                    "memory_mb": mem_mb,
                    "uptime_seconds": uptime_s,
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"running": False, "pid": None, "cpu_percent": 0.0, "memory_mb": 0.0, "uptime_seconds": 0}

# =============================================================================
# ACTIVITY RECONSTRUCTION
# =============================================================================


def detect_changes(old_markets: dict, new_markets: dict) -> list[dict]:
    """Compare market snapshots and generate activity feed events."""
    events = []
    now = datetime.now(timezone.utc).isoformat()

    for key, new_data in new_markets.items():
        old_data = old_markets.get(key)
        city = new_data.get("city_name", key)

        if old_data is None:
            events.append({"ts": now, "type": "scan", "msg": f"SCAN New market: {city} {new_data.get('date', '')}"})
            continue

        old_pos = old_data.get("position")
        new_pos = new_data.get("position")

        # New position opened
        if old_pos is None and new_pos is not None:
            bucket = f"{new_pos.get('bucket_low')}-{new_pos.get('bucket_high')}{new_data.get('unit', '')}"
            events.append({
                "ts": now, "type": "buy",
                "msg": f"BUY {city} ${new_pos.get('cost', 0):.0f} @ {new_pos.get('entry_price', 0):.3f} bucket {bucket} (EV +{new_pos.get('ev', 0):.2f})"
            })

        # Position closed
        if old_pos and new_pos and old_pos.get("status") == "open" and new_pos.get("status") == "closed":
            reason = new_pos.get("close_reason", "unknown")
            pnl = new_pos.get("pnl", 0) or 0
            sign = "+" if pnl >= 0 else ""
            events.append({
                "ts": now, "type": "stop" if pnl < 0 else "resolved",
                "msg": f"EXIT {city} {reason} @ {new_pos.get('exit_price', 0):.3f} ({sign}${pnl:.2f})"
            })

        # New forecast snapshot
        old_snaps = len(old_data.get("forecast_snapshots", []))
        new_snaps = len(new_data.get("forecast_snapshots", []))
        if new_snaps > old_snaps:
            latest = new_data["forecast_snapshots"][-1]
            events.append({
                "ts": now, "type": "monitor",
                "msg": f"FORECAST {city} {latest.get('best_source', '').upper()} {latest.get('best')}°"
            })

    return events

# =============================================================================
# DASHBOARD AGGREGATION
# =============================================================================


def build_dashboard_data() -> dict:
    """Build the complete dashboard payload."""
    state = read_state()
    markets = read_all_markets()
    calibration = read_calibration()
    bot_status = check_bot_status()

    # Compute derived KPIs
    open_positions = []
    closed_positions = []
    forecasts = []
    for key, m in markets.items():
        pos = m.get("position")
        if pos and pos.get("status") == "open":
            # Calculate unrealized PnL using bid price (what you'd actually sell at)
            entry_price = pos.get("entry_price", 0)
            shares = pos.get("shares", 0)
            current_price = entry_price  # fallback
            market_id = pos.get("market_id")
            if market_id:
                for o in m.get("all_outcomes", []):
                    if o.get("market_id") == market_id:
                        # Use bid (sell price), fall back to price
                        current_price = o.get("bid", o.get("price", entry_price))
                        break
            unrealized_pnl = round((current_price - entry_price) * shares, 2)

            open_positions.append({
                "city": m["city"],
                "city_name": m.get("city_name", m["city"]),
                "date": m["date"],
                "unit": m.get("unit", "F"),
                "bucket_low": pos.get("bucket_low"),
                "bucket_high": pos.get("bucket_high"),
                "entry_price": entry_price,
                "current_price": current_price,
                "ev": pos.get("ev"),
                "kelly": pos.get("kelly"),
                "cost": pos.get("cost"),
                "pnl": unrealized_pnl,
                "forecast_src": pos.get("forecast_src"),
                "sigma": pos.get("sigma"),
            })
        elif pos and pos.get("status") == "closed":
            closed_positions.append({
                "city": m["city"],
                "city_name": m.get("city_name", m["city"]),
                "date": m["date"],
                "unit": m.get("unit", "F"),
                "bucket_low": pos.get("bucket_low"),
                "bucket_high": pos.get("bucket_high"),
                "entry_price": pos.get("entry_price"),
                "exit_price": pos.get("exit_price"),
                "pnl": pos.get("pnl", 0),
                "cost": pos.get("cost"),
                "close_reason": pos.get("close_reason", "unknown"),
                "closed_at": pos.get("closed_at"),
            })

        # Latest forecast
        snaps = m.get("forecast_snapshots", [])
        if snaps:
            latest = snaps[-1]
            forecasts.append({
                "city": m["city"],
                "city_name": m.get("city_name", m["city"]),
                "date": m["date"],
                "unit": m.get("unit", "F"),
                "horizon": latest.get("horizon"),
                "ecmwf": latest.get("ecmwf"),
                "hrrr": latest.get("hrrr"),
                "metar": latest.get("metar"),
                "best": latest.get("best"),
                "best_source": latest.get("best_source"),
            })

    # Sort closed positions by closed_at descending (most recent first)
    closed_positions.sort(key=lambda x: x.get("closed_at") or "", reverse=True)

    # Calculate real balance by replaying all trades from market files
    starting = state.get("starting_balance", 1000.0)
    all_costs = sum(p.get("cost", 0) for p in open_positions)  # open position costs
    all_costs += sum(p.get("cost", 0) for p in closed_positions)  # closed position costs
    returned = sum(p.get("cost", 0) + p.get("pnl", 0) for p in closed_positions)
    real_balance = starting - all_costs + returned

    # Replay events chronologically to find peak balance
    events = []
    for key, m in markets.items():
        pos = m.get("position")
        if not pos:
            continue
        events.append(("buy", pos.get("opened_at", ""), -pos.get("cost", 0)))
        if pos.get("status") == "closed":
            events.append(("close", pos.get("closed_at", ""), pos.get("cost", 0) + (pos.get("pnl", 0) or 0)))
    events.sort(key=lambda x: x[1])
    replay_balance = starting
    peak = starting
    for _, _, amount in events:
        replay_balance += amount
        if replay_balance > peak:
            peak = replay_balance

    drawdown = ((real_balance - peak) / peak * 100) if peak > 0 else 0

    # Win rate from closed trades
    wins = sum(1 for p in closed_positions if p.get("pnl", 0) > 0)
    total_closed = len(closed_positions)
    win_rate = (wins / total_closed * 100) if total_closed > 0 else None

    realized_pnl = round(sum(p["pnl"] for p in closed_positions), 2)
    unrealized_pnl = round(sum(p["pnl"] for p in open_positions), 2)
    open_cost = round(sum(p.get("cost", 0) for p in open_positions), 2)
    cash = round(starting + realized_pnl - open_cost, 2)

    # Track balance history
    now_str = datetime.now(timezone.utc).isoformat()
    if not balance_history or balance_history[-1]["balance"] != cash:
        balance_history.append({"ts": now_str, "balance": cash})

    return {
        "state": state,
        "kpi": {
            "starting_balance": starting,
            "open_cost": open_cost,
            "realized_pnl": realized_pnl,
            "cash": cash,
            "unrealized_pnl": unrealized_pnl,
            "open_count": len(open_positions),
            "win_rate": round(win_rate, 1) if win_rate is not None else None,
            "drawdown": round(drawdown, 1),
        },
        "open_positions": open_positions,
        "closed_positions": closed_positions,
        "forecasts": forecasts,
        "calibration": calibration,
        "bot_status": bot_status,
        "balance_history": balance_history,
        "activity": list(activity_feed),
        "locations": LOCATIONS,
    }

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="WeatherBet Operations Center", version="1.0.0")

# Mount static files if the directory exists
_static_dir = BASE_DIR / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Jinja2 templates
_templates_dir = BASE_DIR / "templates"
_templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# HTTP Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main dashboard page."""
    data = build_dashboard_data()
    return templates.TemplateResponse(request=request, name="index.html", context={"data": data})


@app.get("/api/state")
async def api_state():
    return read_state()


@app.get("/api/markets")
async def api_markets():
    return read_all_markets()


@app.get("/api/markets/{city}/{date}")
async def api_market_detail(city: str, date: str):
    stem = f"{city}_{date}"
    path = MARKETS_DIR / f"{stem}.json"
    data = read_json(path)
    if data is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Market {stem} not found")
    return data


@app.get("/api/calibration")
async def api_calibration():
    return read_calibration() or {}


@app.get("/api/bot-status")
async def api_bot_status():
    return check_bot_status()


@app.get("/api/dashboard")
async def api_dashboard():
    return build_dashboard_data()

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def broadcast(payload: dict):
    """Push JSON payload to all connected WebSocket clients."""
    message = json.dumps(payload)
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    connected_clients.difference_update(dead)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        # Send full state on connect
        data = build_dashboard_data()
        await websocket.send_text(json.dumps({"type": "full_update", "data": data}))
        # Keep alive — receive messages (ping/close) until disconnect
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a heartbeat ping
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)

# ---------------------------------------------------------------------------
# File-watcher background task
# ---------------------------------------------------------------------------


async def watch_data_directory():
    """Monitor data/ directory with watchfiles and push updates to clients."""
    global previous_markets

    try:
        from watchfiles import awatch
    except ImportError:
        # watchfiles not available — fall back to polling every 10 s
        while True:
            await asyncio.sleep(10)
            new_markets = read_all_markets()
            events = detect_changes(previous_markets, new_markets)
            for ev in events:
                activity_feed.appendleft(ev)
            previous_markets = new_markets
            if connected_clients:
                data = build_dashboard_data()
                await broadcast({"type": "full_update", "data": data})
            return

    previous_markets = read_all_markets()

    async for changes in awatch(str(DATA_DIR)):
        new_markets = read_all_markets()
        events = detect_changes(previous_markets, new_markets)
        for ev in events:
            activity_feed.appendleft(ev)
        previous_markets = new_markets
        if connected_clients:
            data = build_dashboard_data()
            await broadcast({"type": "full_update", "data": data})


@app.on_event("startup")
async def startup_event():
    """Launch the file-watcher as a background task on app startup."""
    asyncio.create_task(watch_data_directory())

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WeatherBet Dashboard Server")
    parser.add_argument("--port", type=int, default=8050, help="Port to listen on (default: 8050)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    args = parser.parse_args()

    uvicorn.run("dashboard:app", host=args.host, port=args.port, reload=False)
