from weatherbot.execution.orders import Order, OrderFill, OrderSide, OrderStatus
from weatherbot.reporting.telegram import TelegramReporter, redact_sensitive_values


class FakeTransport:
    def __init__(self):
        self.calls = []

    def send_message(self, *, bot_token, chat_id, text):
        self.calls.append({"bot_token": bot_token, "chat_id": chat_id, "text": text})
        return {"ok": True, "result": {"message_id": 123}}


def test_redact_sensitive_values_removes_nested_secret_values_without_mutating_input():
    payload = {
        "market": "nyc-70-74",
        "api_key": "abc123",
        "nested": {"private_key": "0xsecret", "safe": "visible"},
        "items": [{"token": "bot-token", "edge": 0.22}],
    }

    redacted = redact_sensitive_values(payload)

    assert redacted == {
        "market": "nyc-70-74",
        "api_key": "[REDACTED]",
        "nested": {"private_key": "[REDACTED]", "safe": "visible"},
        "items": [{"token": "[REDACTED]", "edge": 0.22}],
    }
    assert payload["api_key"] == "abc123"


def test_disabled_reporter_does_not_send_any_messages():
    transport = FakeTransport()
    reporter = TelegramReporter(enabled=False, bot_token="secret-token", chat_id="123", transport=transport)

    result = reporter.send_error_report("paper scan failed", {"token": "secret-token", "reason": "boom"})

    assert result.sent is False
    assert result.reason == "disabled"
    assert transport.calls == []


def test_send_candidate_report_formats_risk_and_never_includes_token():
    transport = FakeTransport()
    reporter = TelegramReporter(enabled=True, bot_token="secret-token", chat_id="123", transport=transport)

    result = reporter.send_candidate_report(
        {
            "market_slug": "nyc-70-74",
            "city": "New York City",
            "event_date": "2026-06-01",
            "outcome": "70-74F",
            "probability": 0.78,
            "edge": 0.19,
            "dollars": 1.0,
            "risk_approved": True,
            "telegram_token": "secret-token",
        }
    )

    assert result.sent is True
    text = transport.calls[0]["text"]
    assert "Candidate" in text
    assert "nyc-70-74" in text
    assert "Probability: 78.0%" in text
    assert "Edge: 19.0%" in text
    assert "Risk: approved" in text
    assert "secret-token" not in text
    assert "[REDACTED]" in text


def test_send_trade_report_formats_fill_status():
    transport = FakeTransport()
    reporter = TelegramReporter(enabled=True, bot_token="secret-token", chat_id="123", transport=transport)
    fill = OrderFill(
        order=Order(
            decision_id="scan-1:m-70-74",
            market_id="m-70-74",
            outcome="Yes",
            side=OrderSide.BUY,
            limit_price=0.45,
            dollars=1.0,
        ),
        status=OrderStatus.FILLED,
        price=0.44,
        shares=2.2727,
        dollars=1.0,
    )

    reporter.send_trade_report(fill, market_slug="nyc-70-74")

    text = transport.calls[0]["text"]
    assert "Paper trade" in text
    assert "Status: filled" in text
    assert "Market: nyc-70-74" in text
    assert "Price: 0.4400" in text
    assert "Shares: 2.2727" in text


def test_send_daily_summary_includes_counts_and_pnl():
    transport = FakeTransport()
    reporter = TelegramReporter(enabled=True, bot_token="secret-token", chat_id="123", transport=transport)

    reporter.send_daily_summary(
        scanned_markets=12,
        matched_markets=8,
        approved_orders=3,
        filled_orders=2,
        rejected_markets=5,
        realized_pnl=1.25,
        open_positions=4,
    )

    text = transport.calls[0]["text"]
    assert "Daily summary" in text
    assert "Scanned: 12" in text
    assert "Matched: 8" in text
    assert "Approved: 3" in text
    assert "Filled: 2" in text
    assert "Rejected: 5" in text
    assert "Realized PnL: $1.25" in text
    assert "Open positions: 4" in text
