"""Stage B graduation gates for controlled autonomous mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weatherbot.backtest.metrics import BacktestMetrics
from weatherbot.execution.reconciliation import ReconciliationReport


@dataclass(frozen=True)
class GraduationThresholds:
    min_live_trades: int = 100
    max_drawdown: float = 0.0

    def __post_init__(self) -> None:
        if self.min_live_trades < 0:
            raise ValueError("min_live_trades must be non-negative")
        if self.max_drawdown < 0:
            raise ValueError("max_drawdown must be non-negative")


@dataclass(frozen=True)
class GraduationReport:
    approved: bool
    failed_gates: list[str]
    summary: dict[str, Any]


def evaluate_stage_b_graduation(
    *,
    metrics: BacktestMetrics,
    reconciliation: ReconciliationReport,
    thresholds: GraduationThresholds,
    order_fill_logic_proven: bool,
) -> GraduationReport:
    """Evaluate whether Stage B autonomous mode may be enabled.

    This report is intentionally conservative: any failed gate blocks
    graduation, and callers must not auto-raise limits based on this result.
    """

    failed_gates: list[str] = []
    if metrics.trade_count < thresholds.min_live_trades:
        failed_gates.append("min_live_trades")
    if metrics.realized_pnl <= 0:
        failed_gates.append("positive_realized_pnl")
    if metrics.max_drawdown > thresholds.max_drawdown:
        failed_gates.append("max_drawdown")
    if not reconciliation.ok:
        failed_gates.append("reconciliation")
    if not order_fill_logic_proven:
        failed_gates.append("order_fill_logic")

    return GraduationReport(
        approved=not failed_gates,
        failed_gates=failed_gates,
        summary={
            "trade_count": metrics.trade_count,
            "min_live_trades": thresholds.min_live_trades,
            "realized_pnl": metrics.realized_pnl,
            "expected_pnl": metrics.expected_pnl,
            "realized_minus_expected": metrics.realized_minus_expected,
            "max_drawdown": metrics.max_drawdown,
            "max_drawdown_limit": thresholds.max_drawdown,
            "reconciliation_ok": reconciliation.ok,
            "reconciliation_issue_count": len(reconciliation.issues),
            "order_fill_logic_proven": order_fill_logic_proven,
        },
    )
