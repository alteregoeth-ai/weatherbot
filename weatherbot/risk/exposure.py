"""Exposure models for preventing duplicate/correlated weather trades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TradeCandidate:
    decision_id: str
    market_id: str
    city: str
    event_date: str
    outcome: str
    dollars: float
    edge: float
    spread: float
    liquidity_usd: float

    def __post_init__(self) -> None:
        for name in ("decision_id", "market_id", "city", "event_date", "outcome"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.dollars <= 0:
            raise ValueError("dollars must be positive")
        if self.edge < 0:
            raise ValueError("edge must be non-negative")
        if self.spread < 0:
            raise ValueError("spread must be non-negative")
        if self.liquidity_usd < 0:
            raise ValueError("liquidity_usd must be non-negative")


@dataclass(frozen=True)
class PositionExposure:
    market_id: str
    city: str
    event_date: str
    outcome: str
    dollars: float

    def __post_init__(self) -> None:
        if self.dollars < 0:
            raise ValueError("dollars must be non-negative")


class ExposureBook:
    """Current open exposure by market, city, and event date."""

    def __init__(self, positions: Iterable[PositionExposure] | None = None) -> None:
        self.positions = list(positions or [])

    def open_position_count(self) -> int:
        return sum(1 for position in self.positions if position.dollars > 0)

    def city_exposure(self, city: str) -> float:
        return sum(position.dollars for position in self.positions if position.city == city)

    def event_exposure(self, market_id: str) -> float:
        return sum(position.dollars for position in self.positions if position.market_id == market_id)

    def has_city_date_exposure(self, city: str, event_date: str) -> bool:
        return any(
            position.dollars > 0 and position.city == city and position.event_date == event_date
            for position in self.positions
        )
