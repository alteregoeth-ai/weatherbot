import json

from weatherbot.data.polymarket import parse_gamma_event_markets
from weatherbot.data.stations import get_city_station
from weatherbot.data.weather import ForecastSnapshot
from weatherbot.execution.orders import PaperBroker
from weatherbot.ledger import ImmutableLedger
from weatherbot.risk.exposure import ExposureBook
from weatherbot.risk.kill_switch import KillSwitch
from weatherbot.risk.limits import RiskLimits
from weatherbot.scan import PaperScanResult, run_paper_scan
from weatherbot.strategy.calibration import CalibrationKey, CalibrationStore, ForecastObservation


def gamma_event():
    return {
        "id": "event-1",
        "slug": "highest-temperature-in-nyc-on-june-1-2026",
        "title": "Highest temperature in New York City on June 1, 2026?",
        "markets": [
            {
                "id": "m-70-74",
                "slug": "nyc-70-74",
                "question": "Will the highest temperature in New York City be between 70-74°F on June 1?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.44", "0.56"]',
                "clobTokenIds": '["yes-token", "no-token"]',
                "conditionId": "0xabc",
                "volume": "500",
                "liquidity": "250",
                "active": True,
                "closed": False,
            }
        ],
    }


def forecast(*, date="2026-06-01", high=72.0, source="ecmwf"):
    station = get_city_station("nyc")
    return ForecastSnapshot(
        city_slug=station.slug,
        city_name=station.name,
        station=station.station,
        source=source,
        forecast_date=date,
        fetched_at="2026-05-31T12:00:00+00:00",
        high_temperature=high,
        unit=station.temperature_unit,
        horizon_days=1.0,
        metadata={"provider": "open-meteo"},
    )


def parsed_markets():
    return parse_gamma_event_markets(
        gamma_event(),
        books_by_yes_token={"yes-token": {"bids": [{"price": "0.43", "size": "100"}], "asks": [{"price": "0.44", "size": "80"}]}},
        min_liquidity_usd=100,
    )


def read_ledger(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def stage_a_limits():
    return RiskLimits(
        max_bet=1.0,
        min_edge=0.15,
        max_spread=0.02,
        min_liquidity_usd=100.0,
        max_daily_loss=5.0,
        max_open_positions=10,
        max_city_exposure=2.0,
        max_event_exposure=1.0,
    )


def calibrated_store(source="ecmwf"):
    key = CalibrationKey(city="nyc", station="KLGA", source=source, unit="fahrenheit", horizon_hours=24)
    store = CalibrationStore(min_samples=1)
    store.add_observation(ForecastObservation(key=key, forecast_value=70.0, actual_value=72.0))
    store.add_observation(ForecastObservation(key=key, forecast_value=74.0, actual_value=72.0))
    return store


def test_run_paper_scan_matches_market_to_forecast_and_records_fill(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    broker = PaperBroker(starting_cash=10.0)

    result = run_paper_scan(
        run_id="scan-1",
        config_hash="cfg123",
        parsed_markets=parsed_markets(),
        forecasts=[forecast()],
        calibration_store=calibrated_store(),
        broker=broker,
        ledger=ImmutableLedger(ledger_path),
        risk_limits=stage_a_limits(),
        exposure_book=ExposureBook(),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH"),
        bankroll=10.0,
        kelly_fraction_cap=0.25,
        realized_daily_pnl=0.0,
    )

    assert isinstance(result, PaperScanResult)
    assert result.scanned_markets == 1
    assert result.matched_markets == 1
    assert result.approved_orders == 1
    assert result.filled_orders == 1
    assert result.rejected_markets == 0
    assert result.skipped_markets == 0
    assert broker.cash == 9.0

    entries = read_ledger(ledger_path)
    assert [entry["event_type"] for entry in entries] == ["decision", "paper_fill"]
    assert entries[0]["decision_id"] == "scan-1:m-70-74"
    assert entries[0]["payload"]["market_slug"] == "nyc-70-74"
    assert entries[0]["payload"]["risk_approved"] is True


def test_run_paper_scan_skips_markets_without_matching_forecast(tmp_path):
    result = run_paper_scan(
        run_id="scan-1",
        config_hash="cfg123",
        parsed_markets=parsed_markets(),
        forecasts=[forecast(date="2026-06-02")],
        calibration_store=calibrated_store(),
        broker=PaperBroker(starting_cash=10.0),
        ledger=ImmutableLedger(tmp_path / "ledger.jsonl"),
        risk_limits=stage_a_limits(),
        exposure_book=ExposureBook(),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH"),
        bankroll=10.0,
        kelly_fraction_cap=0.25,
        realized_daily_pnl=0.0,
    )

    assert result.scanned_markets == 1
    assert result.matched_markets == 0
    assert result.skipped_markets == 1
    assert result.approved_orders == 0


def test_run_paper_scan_rejects_low_edge_candidate_and_counts_rejection(tmp_path):
    result = run_paper_scan(
        run_id="scan-1",
        config_hash="cfg123",
        parsed_markets=parsed_markets(),
        forecasts=[forecast(high=60.0)],
        calibration_store=calibrated_store(),
        broker=PaperBroker(starting_cash=10.0),
        ledger=ImmutableLedger(tmp_path / "ledger.jsonl"),
        risk_limits=stage_a_limits(),
        exposure_book=ExposureBook(),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH"),
        bankroll=10.0,
        kelly_fraction_cap=0.25,
        realized_daily_pnl=0.0,
    )

    assert result.scanned_markets == 1
    assert result.matched_markets == 1
    assert result.approved_orders == 0
    assert result.filled_orders == 0
    assert result.rejected_markets == 1
    assert "min_edge" in result.results[0].reasons


def test_run_paper_scan_uses_hrrr_short_horizon_over_ecmwf(tmp_path):
    result = run_paper_scan(
        run_id="scan-1",
        config_hash="cfg123",
        parsed_markets=parsed_markets(),
        forecasts=[forecast(high=60.0, source="ecmwf"), forecast(high=72.0, source="hrrr")],
        calibration_store=calibrated_store("hrrr"),
        broker=PaperBroker(starting_cash=10.0),
        ledger=ImmutableLedger(tmp_path / "ledger.jsonl"),
        risk_limits=stage_a_limits(),
        exposure_book=ExposureBook(),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH"),
        bankroll=10.0,
        kelly_fraction_cap=0.25,
        realized_daily_pnl=0.0,
    )

    assert result.approved_orders == 1
    assert result.results[0].order_fill is not None
