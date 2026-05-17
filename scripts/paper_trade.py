#!/usr/bin/env python
"""Run Weatherbot in paper mode and append decisions/fills to a local ledger."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from weatherbot.config import WeatherbotConfig, load_config
from weatherbot.data.polymarket import parse_gamma_event_markets
from weatherbot.data.stations import get_city_station
from weatherbot.data.weather import ForecastSnapshot
from weatherbot.execution.orders import PaperBroker
from weatherbot.ledger import ImmutableLedger
from weatherbot.risk.exposure import ExposureBook
from weatherbot.risk.kill_switch import KillSwitch
from weatherbot.risk.limits import RiskLimits
from weatherbot.scan import PaperScanResult, run_paper_scan
from weatherbot.strategy.calibration import CalibrationStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="run a deterministic one-market demo paper trade")
    parser.add_argument("--config", default="config/default.paper.json", help="paper config JSON path")
    parser.add_argument("--ledger", default="data/paper_trades.jsonl", help="append-only paper ledger path")
    parser.add_argument("--bankroll", type=float, default=10.0, help="paper bankroll/cash balance")
    parser.add_argument("--kelly-fraction-cap", type=float, default=0.25)
    parser.add_argument("--kill-switch", default="KILL_SWITCH", help="path to operator kill-switch file")
    parser.add_argument("--no-telegram", action="store_true", help="reserved; this runner prints locally only")
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error("only --demo is currently wired; live market fetch is intentionally not enabled here")

    cfg = load_config(args.config)
    if cfg.mode != "paper" or cfg.execution.enable_live:
        parser.error("paper runner requires mode='paper' and execution.enable_live=false")

    result = run_demo_paper_trade(
        cfg=cfg,
        config_path=Path(args.config),
        ledger_path=Path(args.ledger),
        bankroll=args.bankroll,
        kelly_fraction_cap=args.kelly_fraction_cap,
        kill_switch_path=Path(args.kill_switch),
    )
    print(format_scan_summary(result, ledger_path=Path(args.ledger)))
    return 0


def run_demo_paper_trade(
    *,
    cfg: WeatherbotConfig,
    config_path: Path,
    ledger_path: Path,
    bankroll: float,
    kelly_fraction_cap: float,
    kill_switch_path: Path,
) -> PaperScanResult:
    station = get_city_station("nyc")
    fetched_at = datetime.now(timezone.utc).isoformat()
    event_date = "2026-06-01"
    gamma_event = {
        "id": "demo-event-1",
        "slug": "highest-temperature-in-nyc-on-june-1-2026",
        "title": "Highest temperature in New York City on June 1, 2026?",
        "markets": [
            {
                "id": "demo-m-68-76",
                "slug": "demo-nyc-68-76",
                "question": "Will the highest temperature in New York City be between 68-76°F on June 1?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.44", "0.56"]',
                "clobTokenIds": '["yes-token", "no-token"]',
                "conditionId": "demo-condition",
                "volume": "500",
                "liquidity": "250",
                "active": True,
                "closed": False,
            }
        ],
    }
    parsed_markets = parse_gamma_event_markets(
        gamma_event,
        books_by_yes_token={"yes-token": {"bids": [{"price": "0.43", "size": "100"}], "asks": [{"price": "0.44", "size": "80"}]}},
        min_liquidity_usd=cfg.trading.min_liquidity_usd,
    )
    forecasts = [
        ForecastSnapshot(
            city_slug=station.slug,
            city_name=station.name,
            station=station.station,
            source="ecmwf",
            forecast_date=event_date,
            fetched_at=fetched_at,
            high_temperature=72.0,
            unit=station.temperature_unit,
            horizon_days=1.0,
            metadata={"provider": "demo"},
        )
    ]

    return run_paper_scan(
        run_id=f"paper-demo-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        config_hash=_file_sha256(config_path),
        parsed_markets=parsed_markets,
        forecasts=forecasts,
        calibration_store=CalibrationStore(),
        broker=PaperBroker(starting_cash=bankroll),
        ledger=ImmutableLedger(ledger_path),
        risk_limits=_risk_limits_from_config(cfg),
        exposure_book=ExposureBook(),
        kill_switch=KillSwitch(kill_switch_path),
        bankroll=bankroll,
        kelly_fraction_cap=kelly_fraction_cap,
        realized_daily_pnl=0.0,
    )


def format_scan_summary(result: PaperScanResult, *, ledger_path: Path) -> str:
    return "\n".join(
        [
            "Weatherbot Paper Trading Run",
            f"Ledger: {ledger_path}",
            f"Scanned: {result.scanned_markets}",
            f"Matched: {result.matched_markets}",
            f"Skipped: {result.skipped_markets}",
            f"Approved: {result.approved_orders}",
            f"Filled: {result.filled_orders}",
            f"Rejected: {result.rejected_markets}",
            "Measure: python scripts/paper_performance.py --ledger " + str(ledger_path),
        ]
    )


def _risk_limits_from_config(cfg: WeatherbotConfig) -> RiskLimits:
    return RiskLimits(
        max_bet=cfg.trading.max_bet,
        min_edge=cfg.trading.min_edge,
        max_spread=cfg.trading.max_spread,
        min_liquidity_usd=cfg.trading.min_liquidity_usd,
        max_daily_loss=cfg.risk.max_daily_loss,
        max_open_positions=cfg.risk.max_open_positions,
        max_city_exposure=cfg.risk.max_city_exposure,
        max_event_exposure=cfg.risk.max_event_exposure,
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
