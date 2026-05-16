#!/usr/bin/env python
"""Generate secret-safe Weatherbot daily monitoring reports."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from weatherbot.reporting.telegram import TelegramReporter, redact_sensitive_values


@dataclass(frozen=True)
class DailyReportSummary:
    scanned_markets: int = 0
    matched_markets: int = 0
    approved_orders: int = 0
    filled_orders: int = 0
    rejected_markets: int = 0
    order_rejections: int = 0
    error_count: int = 0
    realized_pnl: float = 0.0
    open_positions: int = 0
    error_messages: list[str] = field(default_factory=list)


def read_jsonl_entries(path: str | Path) -> list[dict[str, Any]]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                entries.append(json.loads(stripped))
    return entries


def build_daily_summary(entries: Iterable[dict[str, Any]]) -> DailyReportSummary:
    scanned_markets = 0
    matched_markets = 0
    approved_orders = 0
    rejected_markets = 0
    filled_orders = 0
    order_rejections = 0
    error_count = 0
    realized_pnl = 0.0
    positions: dict[tuple[str, str], float] = {}
    error_messages: list[str] = []

    for entry in entries:
        event_type = str(entry.get("event_type", ""))
        payload = entry.get("payload") or {}
        if event_type == "decision":
            scanned_markets += 1
            matched_markets += 1
            if payload.get("risk_approved") is True:
                approved_orders += 1
            else:
                rejected_markets += 1
        elif event_type in ("paper_fill", "live_fill"):
            filled_orders += 1
            _apply_position_delta(positions, payload)
        elif event_type in ("paper_order_rejected", "live_order_rejected"):
            order_rejections += 1
        elif event_type == "error":
            error_count += 1
            safe_payload = redact_sensitive_values(payload)
            message = str(safe_payload.get("message", safe_payload))
            if _contains_redaction(safe_payload):
                message = f"{message} {json.dumps(safe_payload, sort_keys=True)}"
            error_messages.append(message)
        elif event_type == "daily_pnl":
            realized_pnl += _float(payload.get("realized_pnl"))

    open_positions = sum(1 for shares in positions.values() if abs(shares) > 1e-12)
    return DailyReportSummary(
        scanned_markets=scanned_markets,
        matched_markets=matched_markets,
        approved_orders=approved_orders,
        filled_orders=filled_orders,
        rejected_markets=rejected_markets,
        order_rejections=order_rejections,
        error_count=error_count,
        realized_pnl=realized_pnl,
        open_positions=open_positions,
        error_messages=error_messages,
    )


def format_daily_report(summary: DailyReportSummary) -> str:
    lines = [
        "Weatherbot Daily Report",
        f"Scanned: {summary.scanned_markets}",
        f"Matched: {summary.matched_markets}",
        f"Approved: {summary.approved_orders}",
        f"Filled: {summary.filled_orders}",
        f"Rejected: {summary.rejected_markets}",
        f"Order rejections: {summary.order_rejections}",
        f"Errors: {summary.error_count}",
        f"Realized PnL: ${summary.realized_pnl:.2f}",
        f"Open positions: {summary.open_positions}",
    ]
    if summary.error_messages:
        lines.append("Error summary:")
        lines.extend(f"- {message}" for message in summary.error_messages[:5])
    return "\n".join(lines)


def send_telegram_summary(summary: DailyReportSummary) -> None:
    reporter = TelegramReporter(
        enabled=True,
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
    )
    reporter.send_daily_summary(
        scanned_markets=summary.scanned_markets,
        matched_markets=summary.matched_markets,
        approved_orders=summary.approved_orders,
        filled_orders=summary.filled_orders,
        rejected_markets=summary.rejected_markets,
        realized_pnl=summary.realized_pnl,
        open_positions=summary.open_positions,
    )
    if summary.error_messages:
        reporter.send_error_report("daily report error summary", {"errors": summary.error_messages[:5]})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=os.environ.get("WEATHERBOT_LEDGER", "data/trades.jsonl"))
    parser.add_argument("--telegram", action="store_true", help="send report to Telegram using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    parser.add_argument("--no-telegram", action="store_true", help="force local stdout only")
    args = parser.parse_args(argv)

    summary = build_daily_summary(read_jsonl_entries(args.ledger))
    print(format_daily_report(summary))
    if args.telegram and not args.no_telegram:
        send_telegram_summary(summary)
    return 0


def _apply_position_delta(positions: dict[tuple[str, str], float], payload: dict[str, Any]) -> None:
    market_id = str(payload.get("market_id", ""))
    outcome = str(payload.get("outcome", ""))
    if not market_id or not outcome:
        return
    shares = _float(payload.get("shares"))
    side = str(payload.get("side", "buy")).lower()
    multiplier = -1.0 if side == "sell" else 1.0
    key = (market_id, outcome)
    positions[key] = positions.get(key, 0.0) + multiplier * shares


def _contains_redaction(value: Any) -> bool:
    if value == "[REDACTED]":
        return True
    if isinstance(value, dict):
        return any(_contains_redaction(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_redaction(child) for child in value)
    return False


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
