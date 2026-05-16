"""Secret-safe Telegram reporting helpers for paper/live monitoring."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib import request

from weatherbot.execution.orders import OrderFill


_SECRET_KEY_FRAGMENTS = (
    "secret",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "password",
    "passphrase",
    "token",
    "mnemonic",
    "seed",
)


@dataclass(frozen=True)
class TelegramSendResult:
    sent: bool
    reason: str = ""
    response: dict[str, Any] | None = None


class TelegramTransport(Protocol):
    def send_message(self, *, bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
        """Send text through Telegram and return the decoded API response."""


class UrlLibTelegramTransport:
    """Small stdlib Telegram Bot API transport.

    The bot token is only used in the request URL and must never be included in
    report text, logs, ledgers, or exceptions surfaced to users.
    """

    api_base = "https://api.telegram.org"

    def send_message(self, *, bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
        url = f"{self.api_base}/bot{bot_token}/sendMessage"
        body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        api_request = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(api_request, timeout=15) as response:  # nosec B310 - Telegram API URL is fixed.
            return json.loads(response.read().decode("utf-8"))


class TelegramReporter:
    """Format and send monitoring reports to Telegram.

    Set ``enabled=False`` for local-only dry runs. Disabled reporters return a
    structured result and perform no network side effects.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        bot_token: str | None,
        chat_id: str | None,
        transport: TelegramTransport | None = None,
    ) -> None:
        self.enabled = enabled
        self.bot_token = bot_token or ""
        self.chat_id = chat_id or ""
        self.transport = transport or UrlLibTelegramTransport()

    def send_candidate_report(self, candidate_payload: dict[str, Any]) -> TelegramSendResult:
        safe = redact_sensitive_values(candidate_payload)
        risk = "approved" if safe.get("risk_approved") else "rejected"
        lines = [
            "Weatherbot Candidate",
            f"Market: {_value(safe, 'market_slug')}",
            f"City/date: {_value(safe, 'city')} / {_value(safe, 'event_date')}",
            f"Outcome: {_value(safe, 'outcome')}",
            f"Probability: {_percent(safe.get('probability'))}",
            f"Edge: {_percent(safe.get('edge'))}",
            f"Size: ${_float(safe.get('dollars')):.2f}",
            f"Risk: {risk}",
        ]
        redacted_lines = _redacted_detail_lines(safe)
        if redacted_lines:
            lines.extend(redacted_lines)
        return self._send("\n".join(lines))

    def send_trade_report(self, fill: OrderFill, *, market_slug: str) -> TelegramSendResult:
        lines = [
            "Weatherbot Paper trade",
            f"Market: {market_slug}",
            f"Decision: {fill.order.decision_id}",
            f"Side: {fill.order.side.value}",
            f"Outcome: {fill.order.outcome}",
            f"Status: {fill.status.value}",
            f"Limit: {fill.order.limit_price:.4f}",
            f"Price: {fill.price:.4f}",
            f"Shares: {fill.shares:.4f}",
            f"Dollars: ${fill.dollars:.2f}",
        ]
        if fill.reason:
            lines.append(f"Reason: {fill.reason}")
        return self._send("\n".join(lines))

    def send_error_report(self, message: str, context: dict[str, Any] | None = None) -> TelegramSendResult:
        lines = ["Weatherbot Error", f"Message: {message}"]
        safe_context = redact_sensitive_values(context or {})
        for key, value in safe_context.items():
            lines.append(f"{key}: {value}")
        return self._send("\n".join(lines))

    def send_daily_summary(
        self,
        *,
        scanned_markets: int,
        matched_markets: int,
        approved_orders: int,
        filled_orders: int,
        rejected_markets: int,
        realized_pnl: float,
        open_positions: int,
    ) -> TelegramSendResult:
        lines = [
            "Weatherbot Daily summary",
            f"Scanned: {scanned_markets}",
            f"Matched: {matched_markets}",
            f"Approved: {approved_orders}",
            f"Filled: {filled_orders}",
            f"Rejected: {rejected_markets}",
            f"Realized PnL: ${realized_pnl:.2f}",
            f"Open positions: {open_positions}",
        ]
        return self._send("\n".join(lines))

    def _send(self, text: str) -> TelegramSendResult:
        if not self.enabled:
            return TelegramSendResult(sent=False, reason="disabled")
        if not self.bot_token or not self.chat_id:
            return TelegramSendResult(sent=False, reason="missing_config")
        response = self.transport.send_message(bot_token=self.bot_token, chat_id=self.chat_id, text=text)
        return TelegramSendResult(sent=True, response=response)


def redact_sensitive_values(value: Any) -> Any:
    """Return a copy with values redacted below secret-like key names."""

    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, child in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive_values(child)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_values(child) for child in value]
    return value


def _value(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or value == "":
        return "n/a"
    return str(value)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _percent(value: Any) -> str:
    return f"{_float(value) * 100:.1f}%"


def _redacted_detail_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in payload.items():
        if value == "[REDACTED]":
            lines.append(f"{key}: [REDACTED]")
        elif isinstance(value, dict):
            for child in _redacted_detail_lines(value):
                lines.append(f"{key}.{child}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, dict):
                    for child_line in _redacted_detail_lines(child):
                        lines.append(f"{key}[{index}].{child_line}")
    return lines
