"""Expected-value helpers for binary prediction-market positions."""

from __future__ import annotations


def probability_edge(probability: float, ask_price: float) -> float:
    """Return YES edge as fair probability minus ask price."""

    _validate_probability(probability)
    _validate_price(ask_price, name="ask_price")
    return float(probability) - float(ask_price)


def expected_value_per_share(probability: float, price: float) -> float:
    """Return expected profit per YES share bought at `price`.

    Binary YES payout is 1.0 if the event resolves true and 0.0 otherwise.
    Expected profit = P(win) * (1 - price) - P(lose) * price, which simplifies
    to P(win) - price.
    """

    _validate_probability(probability)
    _validate_price(price, name="price")
    return float(probability) - float(price)


def should_trade_yes(probability: float, ask_price: float, min_edge: float) -> bool:
    """Return true when a YES buy clears price validity and edge threshold."""

    _validate_probability(probability)
    if not 0.0 < ask_price < 1.0:
        return False
    if min_edge < 0:
        raise ValueError("min_edge must be non-negative")
    return probability_edge(probability, ask_price) >= min_edge


def _validate_probability(probability: float) -> None:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")


def _validate_price(price: float, *, name: str = "price") -> None:
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
