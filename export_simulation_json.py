#!/usr/bin/env python3
"""Build simulation.json for sim_dashboard_repost.html from bot_v2 state + data/markets/."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "state.json"
MARKETS_DIR = ROOT / "data" / "markets"
OUT = ROOT / "simulation.json"


def _current_price(mkt: dict, pos: dict) -> float:
    mid = str(pos.get("market_id", ""))
    for o in mkt.get("all_outcomes", []):
        if str(o.get("market_id")) == mid:
            return float(o.get("price", pos.get("entry_price", 0)))
    return float(pos.get("entry_price", 0))


def _unrealized_pnl(mkt: dict, pos: dict) -> float:
    px = _current_price(mkt, pos)
    shares = float(pos.get("shares", 0))
    cost = float(pos.get("cost", 0))
    return round(shares * px - cost, 2)


def main() -> None:
    if not STATE_FILE.exists():
        raise SystemExit(f"Missing {STATE_FILE}")

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    markets = []
    for p in sorted(MARKETS_DIR.glob("*.json")):
        try:
            markets.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    positions = {}
    trades = []

    for mkt in markets:
        pos = mkt.get("position")
        if not pos:
            continue
        pid = f"{mkt.get('city', '')}_{mkt.get('date', '')}"
        kelly = float(pos.get("kelly", 0))
        ev = float(pos.get("ev", 0))
        p_model = float(pos.get("p", 0))
        q = pos.get("question", "")
        loc = mkt.get("city_name", mkt.get("city", ""))
        dt = mkt.get("date", "")

        entry_trade = {
            "type": "entry",
            "opened_at": pos.get("opened_at", ""),
            "question": q,
            "cost": float(pos.get("cost", 0)),
            "kelly_pct": kelly,
            "ev": ev,
            "location": loc,
            "date": dt,
            "entry_price": float(pos.get("entry_price", 0)),
            "our_prob": p_model,
        }
        trades.append(entry_trade)

        st = pos.get("status")
        if st == "open":
            u = _unrealized_pnl(mkt, pos)
            positions[pid] = {
                "question": q,
                "pnl": u,
                "current_price": _current_price(mkt, pos),
                "entry_price": float(pos.get("entry_price", 0)),
                "location": loc,
                "kelly_pct": kelly,
                "ev": ev,
                "cost": float(pos.get("cost", 0)),
            }
        elif st == "closed" and pos.get("closed_at"):
            pnl = float(pos.get("pnl") or 0)
            trades.append(
                {
                    "type": "exit",
                    "closed_at": pos.get("closed_at", ""),
                    "opened_at": pos.get("opened_at", ""),
                    "question": q,
                    "pnl": pnl,
                    "kelly_pct": kelly,
                    "ev": ev,
                    "location": loc,
                    "date": dt,
                }
            )

    def _ts(t: dict) -> str:
        if t["type"] == "entry":
            return t.get("opened_at") or ""
        return t.get("closed_at") or t.get("opened_at") or ""

    trades.sort(key=_ts)

    out = {
        "balance": float(state.get("balance", 0)),
        "starting_balance": float(state.get("starting_balance", 1000)),
        "total_trades": int(state.get("total_trades", 0)),
        "wins": int(state.get("wins", 0)),
        "losses": int(state.get("losses", 0)),
        "peak_balance": float(state.get("peak_balance", state.get("balance", 0))),
        "positions": positions,
        "trades": trades,
    }

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT} ({len(positions)} open, {len(trades)} trade rows)")


if __name__ == "__main__":
    main()
