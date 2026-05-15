import pytest

from weatherbot.risk.exposure import ExposureBook, PositionExposure, TradeCandidate
from weatherbot.risk.limits import RiskDecision, RiskLimits, evaluate_trade_risk


def candidate(**overrides):
    base = {
        "decision_id": "decision-1",
        "market_id": "market-1",
        "city": "New York",
        "event_date": "2026-06-01",
        "outcome": "YES",
        "dollars": 1.0,
        "edge": 0.15,
        "spread": 0.02,
        "liquidity_usd": 250.0,
    }
    base.update(overrides)
    return TradeCandidate(**base)


def limits(**overrides):
    base = {
        "max_bet": 1.0,
        "min_edge": 0.15,
        "max_spread": 0.02,
        "min_liquidity_usd": 100.0,
        "max_daily_loss": 5.0,
        "max_open_positions": 5,
        "max_city_exposure": 3.0,
        "max_event_exposure": 1.0,
    }
    base.update(overrides)
    return RiskLimits(**base)


def test_accepts_candidate_that_meets_stage_a_limits():
    decision = evaluate_trade_risk(candidate(), limits(), ExposureBook(), realized_daily_pnl=0.0)

    assert decision == RiskDecision(approved=True, reasons=[])


def test_rejects_bet_over_one_dollar():
    decision = evaluate_trade_risk(candidate(dollars=1.01), limits(), ExposureBook(), realized_daily_pnl=0.0)

    assert not decision.approved
    assert "max_bet" in decision.reasons


def test_rejects_edge_below_fifteen_percent():
    decision = evaluate_trade_risk(candidate(edge=0.149), limits(), ExposureBook(), realized_daily_pnl=0.0)

    assert not decision.approved
    assert "min_edge" in decision.reasons


def test_rejects_spread_over_two_cents():
    decision = evaluate_trade_risk(candidate(spread=0.021), limits(), ExposureBook(), realized_daily_pnl=0.0)

    assert not decision.approved
    assert "max_spread" in decision.reasons


def test_rejects_low_liquidity_market():
    decision = evaluate_trade_risk(candidate(liquidity_usd=99.99), limits(), ExposureBook(), realized_daily_pnl=0.0)

    assert not decision.approved
    assert "min_liquidity_usd" in decision.reasons


def test_rejects_when_daily_loss_limit_is_hit():
    decision = evaluate_trade_risk(candidate(), limits(max_daily_loss=5.0), ExposureBook(), realized_daily_pnl=-5.0)

    assert not decision.approved
    assert "max_daily_loss" in decision.reasons


def test_rejects_when_max_open_positions_reached():
    book = ExposureBook([
        PositionExposure("m1", "New York", "2026-06-01", "YES", dollars=1.0),
        PositionExposure("m2", "Boston", "2026-06-01", "YES", dollars=1.0),
    ])

    decision = evaluate_trade_risk(candidate(market_id="m3", city="Chicago"), limits(max_open_positions=2), book, realized_daily_pnl=0.0)

    assert not decision.approved
    assert "max_open_positions" in decision.reasons


def test_rejects_duplicate_city_date_exposure():
    book = ExposureBook([PositionExposure("other-market", "New York", "2026-06-01", "NO", dollars=0.5)])

    decision = evaluate_trade_risk(candidate(), limits(), book, realized_daily_pnl=0.0)

    assert not decision.approved
    assert "duplicate_city_date" in decision.reasons


def test_rejects_city_exposure_limit_after_new_trade():
    book = ExposureBook([PositionExposure("m1", "New York", "2026-05-31", "YES", dollars=2.5)])

    decision = evaluate_trade_risk(candidate(dollars=0.6), limits(max_city_exposure=3.0), book, realized_daily_pnl=0.0)

    assert not decision.approved
    assert "max_city_exposure" in decision.reasons


def test_rejects_event_exposure_limit_after_new_trade():
    book = ExposureBook([PositionExposure("market-1", "New York", "2026-06-01", "NO", dollars=0.5)])

    decision = evaluate_trade_risk(candidate(dollars=0.6), limits(max_event_exposure=1.0), book, realized_daily_pnl=0.0)

    assert not decision.approved
    assert "max_event_exposure" in decision.reasons


def test_rejects_invalid_candidate_values():
    with pytest.raises(ValueError, match="dollars"):
        candidate(dollars=0)
    with pytest.raises(ValueError, match="spread"):
        candidate(spread=-0.01)
