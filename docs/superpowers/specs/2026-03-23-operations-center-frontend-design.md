# WeatherBet Operations Center — Frontend Design Spec

## Overview

A real-time operations center dashboard for the WeatherBet Polymarket trading bot. Displays all trading data, weather forecasts, market positions, and bot activity in a single-page Bloomberg-style interface.

## Goals

- See all bot data in real-time: positions, forecasts, market prices, P&L, calibration
- Zero changes to `bot_v2.py` — dashboard reads existing JSON files
- Pure Python stack — no Node.js, no build tools
- Single command to start: `python dashboard.py`

## Non-Goals

- Bot control (start/stop/configure) from the dashboard
- Historical backtesting views
- Multi-user authentication
- Mobile-responsive layout (desktop operations center only)

---

## Architecture

### Separation of Concerns

The bot (`bot_v2.py`) and dashboard (`dashboard.py`) run as independent processes. The bot writes JSON files to `data/`. The dashboard reads them. If either crashes, the other continues.

```
bot_v2.py (existing)          dashboard.py (new)
    |                              |
    | writes                       | reads
    v                              v
  data/                     FastAPI + Jinja2
  ├── state.json                   |
  ├── calibration.json       ┌─────┴─────┐
  └── markets/*.json         |           |
                           REST API   WebSocket
                             |           |
                             └─────┬─────┘
                                   |
                              Browser (HTMX)
```

### Tech Stack

**Backend:**
- `fastapi` — web framework with REST + WebSocket support
- `uvicorn` — ASGI server
- `jinja2` — server-side HTML templating
- `watchfiles` — filesystem monitoring for real-time push

**Frontend (CDN, no build):**
- `HTMX` + `htmx-ws` extension — WebSocket-driven partial page updates
- `Chart.js` — balance history line chart
- `Leaflet.js` — interactive world map with custom markers
- CartoDB Dark Matter tiles (free, no API key)

### File Structure

```
weatherbot/
├── dashboard.py              ← FastAPI server (new, ~300 lines)
├── templates/
│   └── index.html            ← Jinja2 template (new, ~400 lines)
├── static/
│   ├── style.css             ← Bloomberg dark theme (new, ~200 lines)
│   └── dashboard.js          ← WebSocket client + chart/map init (new, ~250 lines)
├── bot_v2.py                 ← Untouched
├── data/                     ← Untouched, read-only by dashboard
│   ├── state.json
│   ├── calibration.json
│   └── markets/*.json
```

4 new files. No modifications to existing files.

---

## Backend Design

### REST Endpoints

| Endpoint | Method | Description | Source |
|----------|--------|-------------|--------|
| `/` | GET | Serves the dashboard HTML | `templates/index.html` |
| `/api/state` | GET | Balance, trades, wins/losses | `data/state.json` |
| `/api/markets` | GET | All market data (aggregated) | `data/markets/*.json` |
| `/api/markets/{city}/{date}` | GET | Single market detail | `data/markets/{city}_{date}.json` |
| `/api/calibration` | GET | Sigma data per city/source | `data/calibration.json` |
| `/api/bot-status` | GET | Bot process alive check | Process lookup |

### WebSocket Endpoint

`WS /ws` — real-time push channel.

**Implementation:**
1. On client connect, send full current state (all data)
2. `watchfiles` monitors `data/` directory for file changes
3. On file change: read updated JSON, determine what changed, push delta to all clients
4. Message format:
   ```json
   {
     "type": "state_update" | "market_update" | "calibration_update",
     "data": { ... }
   }
   ```

**Change detection for activity feed:**
- Compare market file snapshots: new `position` field → "BUY" event
- Position `status` changed to "closed" → exit event (with `close_reason`)
- New entry in `forecast_snapshots` → forecast update
- `state.json` balance changed → balance event

### Bot Status Check

Dashboard checks if the bot process is running:
- Look for a python process running `bot_v2.py` via `psutil` or subprocess `pgrep`
- Report: running/stopped, PID, uptime estimate from last file modification

---

## Frontend Design

### Visual Direction

Bloomberg Professional / GitHub Dark aesthetic:
- Background: `#1a1d23` (main), `#21262d` (panels), `#30363d` (borders)
- Text: `#e1e4e8` (primary), `#8b949e` (secondary), `#c9d1d9` (data)
- Accent colors: `#58a6ff` (blue/charts), `#3fb950` (green/profit), `#f85149` (red/loss), `#d29922` (yellow/warning)
- Font: system sans-serif for UI, monospace for data values and activity feed
- No decorative effects (no scanlines, no glow, no animations beyond transitions)

### Layout

Single page, no routing. Grid-based layout:

```
┌──────────────────────────────────────────────────┐
│ Status Bar: [WeatherBet] [LIVE] [Last scan] [Next scan] [Bot PID] │
├──────────────────────────────────────────────────┤
│ KPI Strip: Balance | P&L | Open Positions | Win Rate | Peak | Drawdown │
├──────────────┬───────────────────┬───────────────┤
│              │                   │               │
│  World Map   │  Balance Chart    │  Forecast     │
│  (Leaflet)   │  (Chart.js)       │  Comparison   │
│              │                   │  Table        │
│  City Cards  │  Positions Table  │               │
│  (scrollable)│                   │  Calibration  │
│              │  Activity Feed    │  Sigma Bars   │
│              │  (live log)       │               │
└──────────────┴───────────────────┴───────────────┘
```

Column proportions: `1fr 1.5fr 1fr`

### Panel Details

#### Status Bar
- Left: "WeatherBet" brand + live/polling/offline indicator (pulsing dot)
- Right: Last scan time (relative, e.g., "2m ago"), next scan countdown, bot PID

#### KPI Strip
6 metric cards in a horizontal row:
- **Balance** — current balance from `state.json`
- **Total P&L** — `balance - starting_balance`, colored red/green
- **Open Positions** — count of markets with `position.status == "open"`
- **Win Rate** — `wins / (wins + losses)` or "—" if no resolved trades
- **Peak Balance** — from `state.json`
- **Drawdown** — `(balance - peak_balance) / peak_balance` as percentage

#### World Map (Left Panel)
- **Tiles:** CartoDB Dark Matter (free, dark theme, no API key)
- **Markers:** Custom `DivIcon` HTML markers per city showing:
  - City code (3 letters)
  - Best forecast temperature
  - EV of active position (green/red colored)
  - Status dot: green (profitable position), red (losing), gray (no position)
- **Popups:** On hover, expanded card with:
  - Full city name, target date, horizon (D+0/D+1/D+2)
  - All forecast sources (ECMWF, HRRR, METAR) with best highlighted
  - Market bucket, entry price, current market price
  - Position P&L, Kelly fraction, sigma used
- **Bounds:** Auto-fit to show all 20 cities on load
- **Coordinates:** From `LOCATIONS` dict in `bot_v2.py` (airport lat/lon)
- **Below map:** Scrollable grid of mini city cards (2 columns), each showing city code, forecast, bucket, price. Left border colored by position status.

#### Balance Chart (Center Top)
- Chart.js line chart
- X-axis: time (from trade timestamps)
- Y-axis: balance
- Blue line (`#58a6ff`) with subtle fill
- Horizontal reference lines at starting balance and current balance
- Tooltip on hover showing exact balance and timestamp

#### Positions Table (Center Middle)
- Sortable table columns: City, Bucket, Entry Price, EV, Kelly, P&L
- Rows colored subtly by P&L direction
- Click row to expand full position detail (forecast source, sigma, stop levels, hours to close)
- Shows all open positions, scrollable if > 8 rows

#### Activity Feed (Center Bottom)
- Monospace terminal-style log
- Color-coded entries:
  - Green (`#3fb950`): BUY entries
  - Red (`#f85149`): STOP/LOSS exits
  - Yellow (`#d29922`): MONITOR/SKIP events
  - Blue (`#58a6ff`): SCAN cycle markers
  - White (`#e1e4e8`): RESOLVED outcomes
- **Data source:** Reconstructed from JSON file diffs — dashboard compares latest market file snapshots with previous state to detect new trades, exits, and forecast changes. No dependency on `nohup.out` or stdout.
- Auto-scrolls to newest entry
- Persists last ~100 events in memory

#### Forecast Comparison Table (Right Top)
- Grid: City | ECMWF | HRRR | METAR | Best
- Best source highlighted in green
- HRRR shows "—" for non-US cities
- METAR shows "—" for D+1/D+2 (only available for D+0)
- Scrollable for all 20 cities
- Sorted by date (D+0 first), then city name

#### Calibration Sigma Bars (Right Bottom)
- Per city/source sigma values as horizontal bars
- Color intensity by sigma value: green (low σ = accurate), yellow (medium), red (high σ = uncertain)
- Shows sample count (n) next to each bar
- Only shows entries with `n >= 10`

---

## Real-Time Update Flow

### Primary: WebSocket Push

1. `bot_v2.py` writes JSON files during scan/monitor cycles
2. `dashboard.py` uses `watchfiles` to monitor `data/` directory
3. On file change → read updated file → determine change type → push via WebSocket
4. Client receives message → HTMX swaps only the affected panel(s)

### Fallback: REST Polling

If WebSocket disconnects:
1. Client detects disconnection, status bar changes to "POLLING" (yellow)
2. Falls back to polling all REST endpoints every 30 seconds
3. On reconnect, switches back to WebSocket, status returns to "LIVE" (green)

### Connection States

| State | Indicator | Behavior |
|-------|-----------|----------|
| LIVE | Green pulsing dot | WebSocket connected, real-time push |
| POLLING | Yellow steady dot | WebSocket disconnected, polling every 30s |
| OFFLINE | Red dot | Both failed, last data shown with stale warning |

---

## Data Reading Strategy

The dashboard reads bot's JSON files as read-only. No file locking needed — JSON writes from the bot are atomic (write to temp file + rename).

### State (`data/state.json`)
- Read on initial load and on file change
- Fields: `balance`, `starting_balance`, `total_trades`, `wins`, `losses`, `peak_balance`

### Markets (`data/markets/*.json`)
- Read all files on initial load, index by `{city}_{date}`
- On file change, re-read only the changed file
- Extract: position data, forecast snapshots, market snapshots, outcomes

### Calibration (`data/calibration.json`)
- Read on initial load and on file change
- Fields per entry: `sigma`, `n`, `updated_at`

### Activity Reconstruction
- Dashboard maintains in-memory state of last-seen market data
- On market file update, diff against previous state:
  - New `position` field → generate BUY event
  - `position.status` changed → generate exit event
  - New `forecast_snapshots` entry → generate forecast update event
  - New `market_snapshots` entry → generate market price event
- Events stored in a deque (max 100) for the activity feed

---

## Startup

```bash
# Terminal 1: Bot (already running)
nohup python bot_v2.py &

# Terminal 2: Dashboard
python dashboard.py
# → Serving at http://localhost:8050
```

Dashboard defaults to port 8050 (configurable via `--port` flag). Opens and reads `data/` directory on startup, serves the UI, begins watching for changes.

---

## Error Handling

- **Bot not running:** Dashboard still works — shows last known data with "Bot: STOPPED" in status bar
- **No data files yet:** Shows empty state with "Waiting for first scan..." message
- **Corrupt JSON:** Skip the file, log warning, show last valid state
- **WebSocket disconnect:** Auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s)
- **Multiple browser tabs:** All tabs receive the same WebSocket updates independently

---

## Dependencies

Add to project (no `requirements.txt` exists yet — create one):

```
fastapi>=0.115.0
uvicorn>=0.30.0
jinja2>=3.1.0
watchfiles>=0.20.0
```

Existing dependency (`requests`) remains for the bot. No conflicts.
