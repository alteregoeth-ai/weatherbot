"""Position sizing helpers for tiny, risk-capped trading stages."""

from __future__ import annotations

from weatherbot.strategy.ev import expected_value_per_share


def capped_kelly_bet(
    probability: float,
    price: float,
    *,
    bankroll: float,
    max_bet: float,
    kelly_fraction_cap: float,
) -> float:
    """Return a dollar bet size using fractional Kelly capped by hard limits.

    For a binary YES share bought at `price`, a stake of $S buys S/price shares.
    Kelly fraction for net odds b=(1-price)/price is `(b*p - q) / b`, which
    simplifies to `(p - price) / (1 - price)` for valid 0 < price < 1.
    """

    _validate_sizing_inputs(bankroll, max_bet, kelly_fraction_cap)
    if not 0.0 < price < 1.0:
        return 0.0
    edge = expected_value_per_share(probability, price)
    if edge <= 0:
        return 0.0

    full_kelly_fraction = edge / (1.0 - price)
    capped_fraction = min(full_kelly_fraction, kelly_fraction_cap)
    return round(min(bankroll * capped_fraction, max_bet), 10)


def _validate_sizing_inputs(bankroll: float, max_bet: float, kelly_fraction_cap: float) -> None:
    if bankroll <= 0:
        raise ValueError("bankroll must be positive")
    if max_bet < 0:
        raise ValueError("max_bet must be non-negative")
    if not 0.0 <= kelly_fraction_cap <= 1.0:
        raise ValueError("kelly_fraction_cap must be between 0 and 1")
