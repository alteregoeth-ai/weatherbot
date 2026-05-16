import pytest

from weatherbot.execution.clob import ClobExecutionError, ClobExecutor, ClobOrderResult
from weatherbot.execution.orders import Order, OrderSide
from weatherbot.execution.signer import ClobCredentials
from weatherbot.risk.limits import RiskLimits


class FakeClobClient:
    def __init__(self):
        self.orders = []

    def create_order(self, payload):
        self.orders.append(payload)
        return {"order_id": "remote-123", "status": "submitted", "payload": payload}


def stage_a_limits():
    return RiskLimits(
        max_bet=1.0,
        min_edge=0.15,
        max_spread=0.02,
        min_liquidity_usd=100.0,
        max_daily_loss=5.0,
        max_open_positions=5,
        max_city_exposure=2.0,
        max_event_exposure=1.0,
    )


def buy_order(dollars=1.0, limit_price=0.44):
    return Order(
        decision_id="decision-1",
        market_id="condition-1",
        outcome="YES",
        side=OrderSide.BUY,
        limit_price=limit_price,
        dollars=dollars,
    )


def credentials():
    return ClobCredentials(
        wallet_address="0xabc",
        private_key="super-private-key",
        api_key="api-key",
        api_secret="api-secret",
        api_passphrase="api-passphrase",
    )


def test_live_executor_refuses_to_start_without_explicit_enable_live():
    with pytest.raises(ClobExecutionError, match="enable_live"):
        ClobExecutor(
            enable_live=False,
            dry_run=False,
            credentials=credentials(),
            risk_limits=stage_a_limits(),
            client=FakeClobClient(),
        )


def test_live_executor_refuses_orders_above_stage_a_max_bet():
    executor = ClobExecutor(
        enable_live=True,
        dry_run=True,
        credentials=credentials(),
        risk_limits=stage_a_limits(),
        client=FakeClobClient(),
    )

    with pytest.raises(ClobExecutionError, match="max_bet"):
        executor.submit_order(buy_order(dollars=1.01))


def test_dry_run_returns_exact_payload_without_submitting_to_client():
    client = FakeClobClient()
    executor = ClobExecutor(
        enable_live=True,
        dry_run=True,
        credentials=credentials(),
        risk_limits=stage_a_limits(),
        client=client,
    )

    result = executor.submit_order(buy_order())

    assert isinstance(result, ClobOrderResult)
    assert result.submitted is False
    assert result.dry_run is True
    assert result.payload == {
        "market_id": "condition-1",
        "outcome": "YES",
        "side": "buy",
        "limit_price": 0.44,
        "dollars": 1.0,
        "decision_id": "decision-1",
    }
    assert client.orders == []


def test_live_submit_sends_payload_to_injected_client_when_not_dry_run():
    client = FakeClobClient()
    executor = ClobExecutor(
        enable_live=True,
        dry_run=False,
        credentials=credentials(),
        risk_limits=stage_a_limits(),
        client=client,
    )

    result = executor.submit_order(buy_order())

    assert result.submitted is True
    assert result.remote_order_id == "remote-123"
    assert client.orders == [result.payload]


def test_credentials_repr_and_safe_dict_never_expose_secret_values():
    creds = credentials()

    assert "super-private-key" not in repr(creds)
    assert "api-key" not in repr(creds)
    assert creds.safe_dict() == {"wallet_address": "0xabc"}
