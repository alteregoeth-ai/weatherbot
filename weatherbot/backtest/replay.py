"""Replay saved weather-market snapshots into resolved backtest trades."""

from __future__ import annotations

from dataclasses import dataclass

from weatherbot.backtest.metrics import BacktestMetrics, BacktestTrade, calculate_backtest_metrics


@dataclass(frozen=True)
class BacktestSnapshot:
    decision_id: str
    market_id: str
    city: str
    source: str
    horizon_hours: int
    probability: float
    price: float
    dollars: float
    bucket_low: float | None
    bucket_high: float | None
    actual_value: float

    def resolved_won(self) -> bool:
        if self.bucket_low is not None and self.actual_value < self.bucket_low:
            return False
        if self.bucket_high is not None and self.actual_value > self.bucket_high:
            return False
        return True

    def to_trade(self) -> BacktestTrade:
        return BacktestTrade(
            decision_id=self.decision_id,
            market_id=self.market_id,
            city=self.city,
            source=self.source,
            horizon_hours=self.horizon_hours,
            probability=self.probability,
            price=self.price,
            dollars=self.dollars,
            won=self.resolved_won(),
        )


@dataclass(frozen=True)
class ReplayResult:
    trades: list[BacktestTrade]
    metrics: BacktestMetrics


def replay_snapshots(snapshots: list[BacktestSnapshot]) -> ReplayResult:
    """Resolve saved snapshots and calculate backtest metrics."""

    trades = [snapshot.to_trade() for snapshot in snapshots]
    return ReplayResult(trades=trades, metrics=calculate_backtest_metrics(trades))
