import json

import pytest

from weatherbot.engine import MarketCandidate, PaperTradingEngine
from weatherbot.execution.orders import OrderStatus, PaperBroker
from weatherbot.ledger import ImmutableLedger
from weatherbot.risk.exposure import ExposureBook
from weatherbot.risk.kill_switch import KillSwitch
from weatherbot.risk.limits import RiskLimits
from weatherbot.strategy.probability import Bucket


def engine(tmp_path, *, kill_switch_path=None, starting_cash=10.0):
    return PaperTradingEngine(
        run_id="run-1",
        config_hash="hash-1",
        broker=PaperBroker(starting_cash=starting_cash),
        ledger=ImmutableLedger(tmp_path / "trades.jsonl"),
        risk_limits=RiskLimits(
            max_bet=1.0,
            min_edge=0.15,
            max_spread=0.02,
            min_liquidity_usd=100.0,
            max_daily_loss=5.0,
            max_open_positions=5,
            max_city_exposure=3.0,
            max_event_exposure=1.0,
        ),
        exposure_book=ExposureBook(),
        kill_switch=KillSwitch(kill_switch_path or tmp_path / "KILL_SWITCH"),
        bankroll=100.0,
        kelly_fraction_cap=0.25,
        realized_daily_pnl=0.0,
    )


def candidate(**overrides):
    base = {
        "decision_id": "decision-1",
        "market_id": "market-1",
        "market_slug": "weather-nyc-jun-1",
        "city": "New York",
        "event_date": "2026-06-01",
        "outcome": "YES",
        "forecast_value": 72.0,
        "sigma": 2.0,
        "bucket": Bucket.closed(70, 74),
        "best_bid": 0.43,
        "best_ask": 0.44,
        "liquidity_usd": 250.0,
    }
    base.update(overrides)
    return MarketCandidate(**base)


def ledger_entries(tmp_path):
    path = tmp_path / "trades.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_approved_candidate_places_paper_buy_and_logs_decision_and_fill(tmp_path):
    bot = engine(tmp_path)

    result = bot.evaluate_and_trade(candidate())

    assert result.approved
    assert result.order_fill is not None
    assert result.order_fill.status == OrderStatus.FILLED
    assert result.order_fill.dollars == pytest.approx(1.0)
    assert bot.broker.cash == pytest.approx(9.0)
    assert bot.broker.position_shares("market-1", "YES") > 0

    entries = ledger_entries(tmp_path)
    assert [entry["event_type"] for entry in entries] == ["decision", "paper_fill"]
    assert entries[0]["payload"]["probability"] == pytest.approx(0.7887, abs=0.001)
    assert entries[0]["payload"]["risk_approved"] is True
    assert entries[1]["payload"]["status"] == "filled"


def test_candidate_below_min_edge_is_rejected_and_logged_without_order(tmp_path):
    bot = engine(tmp_path)

    result = bot.evaluate_and_trade(candidate(best_ask=0.70))

    assert not result.approved
    assert "min_edge" in result.reasons
    assert result.order_fill is None
    assert bot.broker.cash == pytest.approx(10.0)

    entries = ledger_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["event_type"] == "decision"
    assert entries[0]["payload"]["risk_approved"] is False
    assert "min_edge" in entries[0]["payload"]["risk_reasons"]


def test_kill_switch_blocks_new_trade_before_order_and_logs_rejection(tmp_path):
    kill_path = tmp_path / "KILL_SWITCH"
    kill_path.write_text("operator stop")
    bot = engine(tmp_path, kill_switch_path=kill_path)

    result = bot.evaluate_and_trade(candidate())

    assert not result.approved
    assert result.reasons == ["kill_switch"]
    assert result.order_fill is None

    entries = ledger_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["payload"]["kill_switch_reason"] == "operator stop"


def test_rejected_paper_order_is_logged_when_broker_rejects_after_risk_approval(tmp_path):
    bot = engine(tmp_path, starting_cash=0.50)

    result = bot.evaluate_and_trade(candidate())

    assert result.approved
    assert result.order_fill is not None
    assert result.order_fill.status == OrderStatus.REJECTED
    assert bot.broker.cash == pytest.approx(0.50)

    entries = ledger_entries(tmp_path)
    assert [entry["event_type"] for entry in entries] == ["decision", "paper_order_rejected"]


def test_rejects_invalid_market_candidate_prices():
    with pytest.raises(ValueError, match="best_ask"):
        candidate(best_ask=1.01)
    with pytest.raises(ValueError, match="liquidity_usd"):
        candidate(liquidity_usd=-1)
