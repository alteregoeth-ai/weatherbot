import pytest

from weatherbot.execution.orders import Order, OrderSide, OrderStatus, PaperBroker


def test_limit_buy_fills_when_best_ask_is_at_or_below_limit():
    broker = PaperBroker(starting_cash=10.0)
    order = Order(
        decision_id="decision-1",
        market_id="market-1",
        outcome="YES",
        side=OrderSide.BUY,
        limit_price=0.45,
        dollars=1.00,
    )

    fill = broker.submit_limit_order(order, best_bid=0.43, best_ask=0.44)

    assert fill.status == OrderStatus.FILLED
    assert fill.price == pytest.approx(0.44)
    assert fill.shares == pytest.approx(1.0 / 0.44)
    assert broker.cash == pytest.approx(9.0)
    assert broker.position_shares("market-1", "YES") == pytest.approx(1.0 / 0.44)


def test_limit_buy_does_not_fill_when_best_ask_is_above_limit():
    broker = PaperBroker(starting_cash=10.0)
    order = Order("decision-1", "market-1", "YES", OrderSide.BUY, limit_price=0.45, dollars=1.0)

    fill = broker.submit_limit_order(order, best_bid=0.43, best_ask=0.46)

    assert fill.status == OrderStatus.OPEN
    assert fill.shares == 0.0
    assert broker.cash == pytest.approx(10.0)
    assert broker.position_shares("market-1", "YES") == 0.0


def test_limit_buy_rejects_if_cash_is_insufficient():
    broker = PaperBroker(starting_cash=0.50)
    order = Order("decision-1", "market-1", "YES", OrderSide.BUY, limit_price=0.45, dollars=1.0)

    fill = broker.submit_limit_order(order, best_bid=0.43, best_ask=0.44)

    assert fill.status == OrderStatus.REJECTED
    assert "cash" in fill.reason.lower()
    assert broker.cash == pytest.approx(0.50)


def test_limit_sell_fills_when_best_bid_is_at_or_above_limit():
    broker = PaperBroker(starting_cash=10.0)
    buy = Order("decision-1", "market-1", "YES", OrderSide.BUY, limit_price=0.45, dollars=1.0)
    broker.submit_limit_order(buy, best_bid=0.43, best_ask=0.44)
    shares = broker.position_shares("market-1", "YES")
    sell = Order("decision-2", "market-1", "YES", OrderSide.SELL, limit_price=0.50, shares=shares)

    fill = broker.submit_limit_order(sell, best_bid=0.51, best_ask=0.52)

    assert fill.status == OrderStatus.FILLED
    assert fill.price == pytest.approx(0.51)
    assert fill.shares == pytest.approx(shares)
    assert broker.position_shares("market-1", "YES") == pytest.approx(0.0)
    assert broker.cash == pytest.approx(10.0 - 1.0 + shares * 0.51)


def test_limit_sell_does_not_fill_when_best_bid_is_below_limit():
    broker = PaperBroker(starting_cash=10.0)
    broker.submit_limit_order(Order("decision-1", "market-1", "YES", OrderSide.BUY, 0.45, dollars=1.0), best_bid=0.43, best_ask=0.44)
    shares = broker.position_shares("market-1", "YES")

    fill = broker.submit_limit_order(Order("decision-2", "market-1", "YES", OrderSide.SELL, 0.50, shares=shares), best_bid=0.49, best_ask=0.52)

    assert fill.status == OrderStatus.OPEN
    assert broker.position_shares("market-1", "YES") == pytest.approx(shares)


def test_limit_sell_rejects_if_shares_are_insufficient():
    broker = PaperBroker(starting_cash=10.0)
    order = Order("decision-1", "market-1", "YES", OrderSide.SELL, limit_price=0.50, shares=1.0)

    fill = broker.submit_limit_order(order, best_bid=0.51, best_ask=0.52)

    assert fill.status == OrderStatus.REJECTED
    assert "shares" in fill.reason.lower()


def test_rejects_invalid_order_amounts_and_prices():
    with pytest.raises(ValueError, match="limit_price"):
        Order("decision-1", "market-1", "YES", OrderSide.BUY, limit_price=0.0, dollars=1.0)

    with pytest.raises(ValueError, match="exactly one"):
        Order("decision-1", "market-1", "YES", OrderSide.BUY, limit_price=0.45, dollars=1.0, shares=1.0)

    with pytest.raises(ValueError, match="positive"):
        PaperBroker(starting_cash=-1.0)
