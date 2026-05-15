"""Read-only paper scan orchestration.

`run_paper_scan` is the first end-to-end loop that joins parsed Polymarket
weather markets to normalized weather forecasts and sends candidates through the
paper trading engine. It has no network or live-trading side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from weatherbot.data.polymarket import ParsedPolymarketMarket
from weatherbot.data.stations import CityStation, get_city_station
from weatherbot.data.weather import ForecastSnapshot, select_best_forecast
from weatherbot.engine import EngineResult, PaperTradingEngine
from weatherbot.execution.orders import OrderStatus, PaperBroker
from weatherbot.ledger import ImmutableLedger
from weatherbot.risk.exposure import ExposureBook
from weatherbot.risk.kill_switch import KillSwitch
from weatherbot.risk.limits import RiskLimits
from weatherbot.strategy.calibration import CalibrationKey, CalibrationStore


@dataclass(frozen=True)
class PaperScanResult:
    scanned_markets: int
    matched_markets: int
    skipped_markets: int
    approved_orders: int
    filled_orders: int
    rejected_markets: int
    results: list[EngineResult]


def run_paper_scan(
    *,
    run_id: str,
    config_hash: str,
    parsed_markets: Sequence[ParsedPolymarketMarket],
    forecasts: Sequence[ForecastSnapshot],
    calibration_store: CalibrationStore,
    broker: PaperBroker,
    ledger: ImmutableLedger,
    risk_limits: RiskLimits,
    exposure_book: ExposureBook,
    kill_switch: KillSwitch,
    bankroll: float,
    kelly_fraction_cap: float,
    realized_daily_pnl: float,
) -> PaperScanResult:
    """Evaluate parsed markets against forecasts using the paper engine."""

    engine = PaperTradingEngine(
        run_id=run_id,
        config_hash=config_hash,
        broker=broker,
        ledger=ledger,
        risk_limits=risk_limits,
        exposure_book=exposure_book,
        kill_switch=kill_switch,
        bankroll=bankroll,
        kelly_fraction_cap=kelly_fraction_cap,
        realized_daily_pnl=realized_daily_pnl,
    )

    results: list[EngineResult] = []
    matched_markets = 0
    skipped_markets = 0
    approved_orders = 0
    filled_orders = 0
    rejected_markets = 0

    forecasts_by_city_date = _group_forecasts_by_city_date(forecasts)

    for market in parsed_markets:
        station = _station_for_market(market)
        matching_forecasts = forecasts_by_city_date.get((station.slug, market.event_date), [])
        best_forecast = select_best_forecast(matching_forecasts, station=station)
        if best_forecast is None:
            skipped_markets += 1
            continue

        matched_markets += 1
        sigma = calibration_store.sigma_for(_calibration_key(station, best_forecast))
        candidate = market.to_market_candidate(
            decision_id=f"{run_id}:{market.market_id}",
            forecast_value=best_forecast.high_temperature,
            sigma=sigma,
        )
        result = engine.evaluate_and_trade(candidate)
        results.append(result)
        if result.approved:
            approved_orders += 1
            if result.order_fill is not None and result.order_fill.status == OrderStatus.FILLED:
                filled_orders += 1
        else:
            rejected_markets += 1

    return PaperScanResult(
        scanned_markets=len(parsed_markets),
        matched_markets=matched_markets,
        skipped_markets=skipped_markets,
        approved_orders=approved_orders,
        filled_orders=filled_orders,
        rejected_markets=rejected_markets,
        results=results,
    )


def _group_forecasts_by_city_date(
    forecasts: Sequence[ForecastSnapshot],
) -> dict[tuple[str, str], list[ForecastSnapshot]]:
    grouped: dict[tuple[str, str], list[ForecastSnapshot]] = {}
    for snapshot in forecasts:
        grouped.setdefault((snapshot.city_slug, snapshot.forecast_date), []).append(snapshot)
    return grouped


def _station_for_market(market: ParsedPolymarketMarket) -> CityStation:
    return get_city_station(_city_slug_from_market_city(market.city))


def _city_slug_from_market_city(city: str) -> str:
    normalized = city.strip().lower().replace(" ", "-")
    aliases = {
        "new-york-city": "nyc",
        "new-york": "nyc",
    }
    return aliases.get(normalized, normalized)


def _calibration_key(station: CityStation, forecast: ForecastSnapshot) -> CalibrationKey:
    unit = "fahrenheit" if forecast.unit == "F" else "celsius"
    horizon_hours = max(1, round(forecast.horizon_days * 24))
    return CalibrationKey(
        city=station.slug,
        station=station.station,
        source=forecast.source,
        unit=unit,
        horizon_hours=horizon_hours,
    )
