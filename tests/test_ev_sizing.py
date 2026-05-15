import pytest

from weatherbot.strategy.ev import expected_value_per_share, probability_edge, should_trade_yes
from weatherbot.strategy.sizing import capped_kelly_bet


def test_probability_edge_is_probability_minus_ask_price():
    assert probability_edge(probability=0.62, ask_price=0.45) == pytest.approx(0.17)


def test_expected_value_per_yes_share_accounts_for_binary_payout_cost():
    assert expected_value_per_share(probability=0.62, price=0.45) == pytest.approx(0.17)


def test_should_trade_yes_requires_min_edge_and_valid_price():
    assert should_trade_yes(probability=0.62, ask_price=0.45, min_edge=0.15)
    assert not should_trade_yes(probability=0.58, ask_price=0.45, min_edge=0.15)
    assert not should_trade_yes(probability=0.62, ask_price=0.0, min_edge=0.15)
    assert not should_trade_yes(probability=0.62, ask_price=1.0, min_edge=0.15)


def test_probability_and_price_must_be_between_zero_and_one():
    with pytest.raises(ValueError, match="probability"):
        probability_edge(probability=1.1, ask_price=0.45)
    with pytest.raises(ValueError, match="price"):
        expected_value_per_share(probability=0.62, price=-0.01)


def test_capped_kelly_bet_never_exceeds_max_bet_or_fraction_cap():
    bet = capped_kelly_bet(
        probability=0.62,
        price=0.45,
        bankroll=100.0,
        max_bet=1.0,
        kelly_fraction_cap=0.25,
    )

    assert bet == pytest.approx(1.0)


def test_capped_kelly_bet_returns_zero_for_no_edge_or_invalid_price():
    assert capped_kelly_bet(0.50, 0.55, bankroll=100, max_bet=1, kelly_fraction_cap=0.25) == 0.0
    assert capped_kelly_bet(0.62, 0.0, bankroll=100, max_bet=1, kelly_fraction_cap=0.25) == 0.0
    assert capped_kelly_bet(0.62, 1.0, bankroll=100, max_bet=1, kelly_fraction_cap=0.25) == 0.0


def test_capped_kelly_bet_requires_positive_bankroll_and_limits():
    with pytest.raises(ValueError, match="bankroll"):
        capped_kelly_bet(0.62, 0.45, bankroll=0, max_bet=1, kelly_fraction_cap=0.25)
    with pytest.raises(ValueError, match="max_bet"):
        capped_kelly_bet(0.62, 0.45, bankroll=100, max_bet=-1, kelly_fraction_cap=0.25)
    with pytest.raises(ValueError, match="kelly_fraction_cap"):
        capped_kelly_bet(0.62, 0.45, bankroll=100, max_bet=1, kelly_fraction_cap=1.1)
