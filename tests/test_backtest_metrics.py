import pytest

from weatherbot.backtest.metrics import BacktestTrade, calculate_backtest_metrics
from weatherbot.backtest.replay import BacktestSnapshot, replay_snapshots


def trade(
    *,
    decision_id="decision-1",
    city="nyc",
    source="hrrr",
    horizon_hours=12,
    probability=0.60,
    price=0.40,
    dollars=1.0,
    won=True,
):
    return BacktestTrade(
        decision_id=decision_id,
        market_id=f"market-{decision_id}",
        city=city,
        source=source,
        horizon_hours=horizon_hours,
        probability=probability,
        price=price,
        dollars=dollars,
        won=won,
    )


def test_calculates_realized_vs_expected_ev_win_rate_roi_and_drawdown():
    metrics = calculate_backtest_metrics(
        [
            trade(decision_id="one", probability=0.60, price=0.40, won=True),
            trade(decision_id="two", probability=0.50, price=0.70, won=False),
            trade(decision_id="three", probability=0.40, price=0.25, won=True),
        ]
    )

    assert metrics.trade_count == 3
    assert metrics.realized_pnl == pytest.approx(3.50)
    assert metrics.expected_pnl == pytest.approx(0.8142857)
    assert metrics.realized_minus_expected == pytest.approx(2.6857143)
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.roi == pytest.approx(3.50 / 3.0)
    assert metrics.max_drawdown == pytest.approx(1.00)
    assert metrics.return_stdev > 0
    assert metrics.sharpe_like > 0


def test_calculates_exposure_by_city_source_and_horizon():
    metrics = calculate_backtest_metrics(
        [
            trade(decision_id="one", city="nyc", source="hrrr", horizon_hours=12, dollars=1.0),
            trade(decision_id="two", city="nyc", source="ecmwf", horizon_hours=24, dollars=2.0),
            trade(decision_id="three", city="miami", source="hrrr", horizon_hours=12, dollars=3.0),
        ]
    )

    assert metrics.exposure_by_city == {"nyc": 3.0, "miami": 3.0}
    assert metrics.exposure_by_source == {"hrrr": 4.0, "ecmwf": 2.0}
    assert metrics.exposure_by_horizon_hours == {12: 4.0, 24: 2.0}


def test_empty_metrics_are_zero_and_safe():
    metrics = calculate_backtest_metrics([])

    assert metrics.trade_count == 0
    assert metrics.realized_pnl == 0.0
    assert metrics.expected_pnl == 0.0
    assert metrics.win_rate == 0.0
    assert metrics.roi == 0.0
    assert metrics.max_drawdown == 0.0
    assert metrics.sharpe_like == 0.0


def test_replay_snapshots_converts_resolved_snapshots_to_backtest_trades():
    snapshots = [
        BacktestSnapshot(
            decision_id="decision-1",
            market_id="market-1",
            city="nyc",
            source="hrrr",
            horizon_hours=12,
            probability=0.60,
            price=0.40,
            dollars=1.0,
            bucket_low=70.0,
            bucket_high=74.0,
            actual_value=72.0,
        ),
        BacktestSnapshot(
            decision_id="decision-2",
            market_id="market-2",
            city="nyc",
            source="ecmwf",
            horizon_hours=24,
            probability=0.50,
            price=0.70,
            dollars=1.0,
            bucket_low=70.0,
            bucket_high=74.0,
            actual_value=80.0,
        ),
    ]

    result = replay_snapshots(snapshots)

    assert [trade.won for trade in result.trades] == [True, False]
    assert result.metrics.trade_count == 2
    assert result.metrics.realized_pnl == pytest.approx(0.50)
