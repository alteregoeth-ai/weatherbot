"""Risk limit evaluation for Stage A tiny-capital paper/live trading."""

from __future__ import annotations

from dataclasses import dataclass

from weatherbot.risk.exposure import ExposureBook, TradeCandidate


@dataclass(frozen=True)
class RiskLimits:
    max_bet: float
    min_edge: float
    max_spread: float
    min_liquidity_usd: float
    max_daily_loss: float
    max_open_positions: int
    max_city_exposure: float
    max_event_exposure: float

    def __post_init__(self) -> None:
        for name in (
            "max_bet",
            "min_edge",
            "max_spread",
            "min_liquidity_usd",
            "max_daily_loss",
            "max_city_exposure",
            "max_event_exposure",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be non-negative")


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: list[str]


def evaluate_trade_risk(
    candidate: TradeCandidate,
    limits: RiskLimits,
    exposure_book: ExposureBook,
    *,
    realized_daily_pnl: float,
) -> RiskDecision:
    """Evaluate a candidate against Stage A hard safety gates."""

    reasons: list[str] = []

    if candidate.dollars > limits.max_bet:
        reasons.append("max_bet")
    if candidate.edge < limits.min_edge:
        reasons.append("min_edge")
    if candidate.spread > limits.max_spread:
        reasons.append("max_spread")
    if candidate.liquidity_usd < limits.min_liquidity_usd:
        reasons.append("min_liquidity_usd")
    if realized_daily_pnl <= -limits.max_daily_loss:
        reasons.append("max_daily_loss")
    if exposure_book.open_position_count() >= limits.max_open_positions:
        reasons.append("max_open_positions")
    if exposure_book.has_city_date_exposure(candidate.city, candidate.event_date):
        reasons.append("duplicate_city_date")
    if exposure_book.city_exposure(candidate.city) + candidate.dollars > limits.max_city_exposure:
        reasons.append("max_city_exposure")
    if exposure_book.event_exposure(candidate.market_id) + candidate.dollars > limits.max_event_exposure:
        reasons.append("max_event_exposure")

    return RiskDecision(approved=not reasons, reasons=reasons)
