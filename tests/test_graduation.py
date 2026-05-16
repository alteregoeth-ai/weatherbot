from weatherbot.backtest.metrics import BacktestMetrics
from weatherbot.execution.reconciliation import ReconciliationIssue, ReconciliationReport
from weatherbot.graduation import GraduationThresholds, evaluate_stage_b_graduation


def metrics(
    *,
    trade_count=100,
    realized_pnl=5.0,
    expected_pnl=3.0,
    max_drawdown=1.0,
):
    return BacktestMetrics(
        trade_count=trade_count,
        total_staked=float(trade_count),
        realized_pnl=realized_pnl,
        expected_pnl=expected_pnl,
        realized_minus_expected=realized_pnl - expected_pnl,
        win_rate=0.56,
        roi=realized_pnl / float(trade_count) if trade_count else 0.0,
        max_drawdown=max_drawdown,
        return_stdev=0.5,
        sharpe_like=0.8,
        exposure_by_city={"nyc": 50.0, "miami": 50.0},
        exposure_by_source={"hrrr": 60.0, "ecmwf": 40.0},
        exposure_by_horizon_hours={12: 60.0, 24: 40.0},
    )


def thresholds():
    return GraduationThresholds(min_live_trades=100, max_drawdown=2.0)


def clean_reconciliation():
    return ReconciliationReport(issues=[])


def test_stage_b_graduation_passes_when_all_required_gates_are_met():
    report = evaluate_stage_b_graduation(
        metrics=metrics(),
        reconciliation=clean_reconciliation(),
        thresholds=thresholds(),
        order_fill_logic_proven=True,
    )

    assert report.approved is True
    assert report.failed_gates == []
    assert report.summary["trade_count"] == 100
    assert report.summary["realized_pnl"] == 5.0
    assert report.summary["max_drawdown"] == 1.0


def test_stage_b_graduation_requires_at_least_100_live_trades():
    report = evaluate_stage_b_graduation(
        metrics=metrics(trade_count=99),
        reconciliation=clean_reconciliation(),
        thresholds=thresholds(),
        order_fill_logic_proven=True,
    )

    assert report.approved is False
    assert "min_live_trades" in report.failed_gates


def test_stage_b_graduation_requires_positive_realized_pnl():
    report = evaluate_stage_b_graduation(
        metrics=metrics(realized_pnl=0.0, expected_pnl=3.0),
        reconciliation=clean_reconciliation(),
        thresholds=thresholds(),
        order_fill_logic_proven=True,
    )

    assert report.approved is False
    assert "positive_realized_pnl" in report.failed_gates


def test_stage_b_graduation_requires_drawdown_within_limit():
    report = evaluate_stage_b_graduation(
        metrics=metrics(max_drawdown=2.01),
        reconciliation=clean_reconciliation(),
        thresholds=thresholds(),
        order_fill_logic_proven=True,
    )

    assert report.approved is False
    assert "max_drawdown" in report.failed_gates


def test_stage_b_graduation_requires_clean_reconciliation():
    report = evaluate_stage_b_graduation(
        metrics=metrics(),
        reconciliation=ReconciliationReport(
            issues=[ReconciliationIssue(code="position_mismatch", detail="local shares differ")]
        ),
        thresholds=thresholds(),
        order_fill_logic_proven=True,
    )

    assert report.approved is False
    assert "reconciliation" in report.failed_gates


def test_stage_b_graduation_requires_proven_order_fill_logic():
    report = evaluate_stage_b_graduation(
        metrics=metrics(),
        reconciliation=clean_reconciliation(),
        thresholds=thresholds(),
        order_fill_logic_proven=False,
    )

    assert report.approved is False
    assert "order_fill_logic" in report.failed_gates
