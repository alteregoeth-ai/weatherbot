"""Backtest trade metrics for replayed weather market decisions."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import fmean, pstdev


@dataclass(frozen=True)
class BacktestTrade:
    decision_id: str
    market_id: str
    city: str
    source: str
    horizon_hours: int
    probability: float
    price: float
    dollars: float
    won: bool

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id is required")
        if not self.market_id:
            raise ValueError("market_id is required")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be between 0 and 1")
        if not 0.0 < self.price < 1.0:
            raise ValueError("price must be between 0 and 1")
        if self.dollars <= 0:
            raise ValueError("dollars must be positive")
        if self.horizon_hours < 0:
            raise ValueError("horizon_hours must be non-negative")

    @property
    def shares(self) -> float:
        return self.dollars / self.price

    @property
    def realized_pnl(self) -> float:
        payout = self.shares if self.won else 0.0
        return payout - self.dollars

    @property
    def expected_pnl(self) -> float:
        return self.probability * self.shares - self.dollars

    @property
    def return_on_stake(self) -> float:
        return self.realized_pnl / self.dollars


@dataclass(frozen=True)
class BacktestMetrics:
    trade_count: int
    total_staked: float
    realized_pnl: float
    expected_pnl: float
    realized_minus_expected: float
    win_rate: float
    roi: float
    max_drawdown: float
    return_stdev: float
    sharpe_like: float
    exposure_by_city: dict[str, float]
    exposure_by_source: dict[str, float]
    exposure_by_horizon_hours: dict[int, float]


def calculate_backtest_metrics(trades: list[BacktestTrade]) -> BacktestMetrics:
    """Calculate aggregate replay metrics from resolved backtest trades."""

    if not trades:
        return BacktestMetrics(
            trade_count=0,
            total_staked=0.0,
            realized_pnl=0.0,
            expected_pnl=0.0,
            realized_minus_expected=0.0,
            win_rate=0.0,
            roi=0.0,
            max_drawdown=0.0,
            return_stdev=0.0,
            sharpe_like=0.0,
            exposure_by_city={},
            exposure_by_source={},
            exposure_by_horizon_hours={},
        )

    total_staked = sum(trade.dollars for trade in trades)
    realized_pnl = sum(trade.realized_pnl for trade in trades)
    expected_pnl = sum(trade.expected_pnl for trade in trades)
    returns = [trade.return_on_stake for trade in trades]
    return_mean = fmean(returns)
    return_stdev = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe_like = return_mean / return_stdev if return_stdev > 0 else 0.0

    return BacktestMetrics(
        trade_count=len(trades),
        total_staked=total_staked,
        realized_pnl=realized_pnl,
        expected_pnl=expected_pnl,
        realized_minus_expected=realized_pnl - expected_pnl,
        win_rate=sum(1 for trade in trades if trade.won) / len(trades),
        roi=realized_pnl / total_staked if total_staked > 0 else 0.0,
        max_drawdown=_max_drawdown([trade.realized_pnl for trade in trades]),
        return_stdev=return_stdev,
        sharpe_like=sharpe_like if math.isfinite(sharpe_like) else 0.0,
        exposure_by_city=_exposure_by(trades, "city"),
        exposure_by_source=_exposure_by(trades, "source"),
        exposure_by_horizon_hours=_exposure_by(trades, "horizon_hours"),
    )


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def _exposure_by(trades: list[BacktestTrade], field_name: str) -> dict:
    exposure: dict = {}
    for trade in trades:
        key = getattr(trade, field_name)
        exposure[key] = exposure.get(key, 0.0) + trade.dollars
    return exposure
