"""Order models and paper broker for safe pre-live execution testing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Order:
    decision_id: str
    market_id: str
    outcome: str
    side: OrderSide
    limit_price: float
    dollars: float | None = None
    shares: float | None = None

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id is required")
        if not self.market_id:
            raise ValueError("market_id is required")
        if not self.outcome:
            raise ValueError("outcome is required")
        if not 0.0 < self.limit_price < 1.0:
            raise ValueError("limit_price must be between 0 and 1")
        has_dollars = self.dollars is not None
        has_shares = self.shares is not None
        if has_dollars == has_shares:
            raise ValueError("provide exactly one of dollars or shares")
        if self.dollars is not None and self.dollars <= 0:
            raise ValueError("dollars must be positive")
        if self.shares is not None and self.shares <= 0:
            raise ValueError("shares must be positive")


@dataclass(frozen=True)
class OrderFill:
    order: Order
    status: OrderStatus
    price: float = 0.0
    shares: float = 0.0
    dollars: float = 0.0
    reason: str = ""


class PaperBroker:
    """Deterministic paper broker using top-of-book bid/ask fill rules."""

    def __init__(self, *, starting_cash: float) -> None:
        if starting_cash < 0:
            raise ValueError("starting_cash must be positive or zero")
        self.cash = float(starting_cash)
        self._positions: dict[tuple[str, str], float] = {}

    def submit_limit_order(self, order: Order, *, best_bid: float, best_ask: float) -> OrderFill:
        _validate_book_price(best_bid, "best_bid")
        _validate_book_price(best_ask, "best_ask")
        if best_bid > best_ask:
            raise ValueError("best_bid cannot exceed best_ask")
        if order.side == OrderSide.BUY:
            return self._submit_buy(order, best_ask=best_ask)
        if order.side == OrderSide.SELL:
            return self._submit_sell(order, best_bid=best_bid)
        raise ValueError(f"unsupported order side: {order.side}")

    def position_shares(self, market_id: str, outcome: str) -> float:
        return self._positions.get((market_id, outcome), 0.0)

    def _submit_buy(self, order: Order, *, best_ask: float) -> OrderFill:
        assert order.dollars is not None
        if best_ask > order.limit_price:
            return OrderFill(order=order, status=OrderStatus.OPEN)
        if self.cash < order.dollars:
            return OrderFill(order=order, status=OrderStatus.REJECTED, reason="insufficient cash")
        shares = order.dollars / best_ask
        self.cash -= order.dollars
        key = (order.market_id, order.outcome)
        self._positions[key] = self._positions.get(key, 0.0) + shares
        return OrderFill(
            order=order,
            status=OrderStatus.FILLED,
            price=best_ask,
            shares=shares,
            dollars=order.dollars,
        )

    def _submit_sell(self, order: Order, *, best_bid: float) -> OrderFill:
        assert order.shares is not None
        if best_bid < order.limit_price:
            return OrderFill(order=order, status=OrderStatus.OPEN)
        key = (order.market_id, order.outcome)
        held = self._positions.get(key, 0.0)
        if held + 1e-12 < order.shares:
            return OrderFill(order=order, status=OrderStatus.REJECTED, reason="insufficient shares")
        proceeds = order.shares * best_bid
        self.cash += proceeds
        remaining = held - order.shares
        self._positions[key] = 0.0 if abs(remaining) < 1e-12 else remaining
        return OrderFill(
            order=order,
            status=OrderStatus.FILLED,
            price=best_bid,
            shares=order.shares,
            dollars=proceeds,
        )


def _validate_book_price(price: float, name: str) -> None:
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
