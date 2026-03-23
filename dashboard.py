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
from datetime import datetime
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


def detect_changes(old_markets: dict, new_markets: dict) -> list:
    """
    Compare two market snapshots and generate activity events for:
      - New BUY positions
      - Closed / exited positions
      - Significant forecast shifts
    Returns a list of event dicts.
    """
    events = []
    now_str = datetime.utcnow().isoformat() + "Z"

    for stem, new_data in new_markets.items():
        old_data = old_markets.get(stem, {})
        city = new_data.get("city", stem)
        city_name = new_data.get("city_name", city)
        date = new_data.get("date", "")

        # BUY: position appeared
        old_pos = old_data.get("position")
        new_pos = new_data.get("position")
        if new_pos and not old_pos:
            events.append({
                "ts": now_str,
                "type": "BUY",
                "city": city,
                "city_name": city_name,
                "date": date,
                "detail": new_pos,
            })

        # EXIT: position resolved (pnl populated)
        old_pnl = old_data.get("pnl")
        new_pnl = new_data.get("pnl")
        if new_pnl is not None and old_pnl is None:
            direction = "WIN" if new_pnl > 0 else "LOSS"
            events.append({
                "ts": now_str,
                "type": f"EXIT_{direction}",
                "city": city,
                "city_name": city_name,
                "date": date,
                "pnl": new_pnl,
            })

        # FORECAST: best forecast changed significantly (>= 1 degree)
        old_snaps = old_data.get("forecast_snapshots", [])
        new_snaps = new_data.get("forecast_snapshots", [])
        if old_snaps and new_snaps:
            old_best = old_snaps[-1].get("best")
            new_best = new_snaps[-1].get("best")
            if old_best is not None and new_best is not None and abs(new_best - old_best) >= 1:
                events.append({
                    "ts": now_str,
                    "type": "FORECAST",
                    "city": city,
                    "city_name": city_name,
                    "date": date,
                    "old_best": old_best,
                    "new_best": new_best,
                })

    return events

# =============================================================================
# DASHBOARD AGGREGATION
# =============================================================================


def build_dashboard_data() -> dict:
    """Aggregate state, markets, calibration, and bot status into one payload."""
    state = read_state()
    markets = read_all_markets()
    calibration = read_calibration()
    bot_status = check_bot_status()

    # KPIs
    balance = state.get("balance", 0.0)
    starting_balance = state.get("starting_balance", 0.0)
    pnl = round(balance - starting_balance, 2)
    pnl_pct = round((pnl / starting_balance * 100) if starting_balance else 0.0, 2)

    total_trades = state.get("total_trades", 0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    settled = wins + losses
    win_rate = round((wins / settled * 100) if settled > 0 else 0.0, 1)

    peak_balance = state.get("peak_balance", starting_balance or balance)
    drawdown = round(((peak_balance - balance) / peak_balance * 100) if peak_balance else 0.0, 2)

    # Open positions count
    open_count = sum(
        1 for m in markets.values()
        if m.get("status") == "open" and m.get("position") is not None
    )

    # Track balance history (append if balance changed)
    now_str = datetime.utcnow().isoformat() + "Z"
    if not balance_history or balance_history[-1]["balance"] != balance:
        balance_history.append({"ts": now_str, "balance": balance})
        # Keep last 500 points
        if len(balance_history) > 500:
            del balance_history[:-500]

    return {
        "ts": now_str,
        "state": state,
        "kpis": {
            "balance": balance,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "open_count": open_count,
            "peak_balance": peak_balance,
            "drawdown": drawdown,
        },
        "balance_history": balance_history[-200:],
        "activity_feed": list(activity_feed),
        "markets": markets,
        "calibration": calibration,
        "bot_status": bot_status,
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
    index_file = _templates_dir / "index.html"
    if index_file.exists():
        return templates.TemplateResponse("index.html", {"request": request})
    # Fallback minimal HTML when template not yet created
    return HTMLResponse(
        content="<html><body><h1>WeatherBet Dashboard</h1>"
                "<p>Templates not yet installed. API is live at <a href='/api/dashboard'>/api/dashboard</a>.</p>"
                "</body></html>"
    )


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
