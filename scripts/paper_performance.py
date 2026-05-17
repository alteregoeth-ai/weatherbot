#!/usr/bin/env python
"""Measure Weatherbot paper-trading performance from the append-only ledger."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PaperPerformance:
    decisions: int
    approved: int
    rejected: int
    fills: int
    order_rejections: int
    approval_rate: float
    fill_rate: float
    total_staked: float
    average_edge: float
    realized_pnl: float
    open_positions: int


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


def calculate_paper_performance(entries: Iterable[dict[str, Any]]) -> PaperPerformance:
    decisions = 0
    approved = 0
    rejected = 0
    fills = 0
    order_rejections = 0
    total_staked = 0.0
    realized_pnl = 0.0
    edges: list[float] = []
    positions: dict[tuple[str, str], float] = {}

    for entry in entries:
        event_type = str(entry.get("event_type", ""))
        payload = entry.get("payload") or {}
        if event_type == "decision":
            decisions += 1
            edges.append(_float(payload.get("edge")))
            if payload.get("risk_approved") is True:
                approved += 1
            else:
                rejected += 1
        elif event_type == "paper_fill":
            fills += 1
            total_staked += _float(payload.get("dollars"))
            _apply_position_delta(positions, payload)
        elif event_type == "paper_order_rejected":
            order_rejections += 1
        elif event_type == "daily_pnl":
            realized_pnl += _float(payload.get("realized_pnl"))

    approval_rate = approved / decisions if decisions else 0.0
    fill_rate = fills / approved if approved else 0.0
    average_edge = sum(edges) / len(edges) if edges else 0.0
    open_positions = sum(1 for shares in positions.values() if abs(shares) > 1e-12)
    return PaperPerformance(
        decisions=decisions,
        approved=approved,
        rejected=rejected,
        fills=fills,
        order_rejections=order_rejections,
        approval_rate=approval_rate,
        fill_rate=fill_rate,
        total_staked=total_staked,
        average_edge=average_edge,
        realized_pnl=realized_pnl,
        open_positions=open_positions,
    )


def format_paper_performance(performance: PaperPerformance) -> str:
    return "\n".join(
        [
            "Weatherbot Paper Performance",
            f"Decisions: {performance.decisions}",
            f"Approved: {performance.approved}",
            f"Rejected: {performance.rejected}",
            f"Fills: {performance.fills}",
            f"Order rejections: {performance.order_rejections}",
            f"Approval rate: {performance.approval_rate:.2%}",
            f"Fill rate: {performance.fill_rate:.2%}",
            f"Average edge: {performance.average_edge:.2%}",
            f"Total staked: ${performance.total_staked:.2f}",
            f"Realized PnL: ${performance.realized_pnl:.2f}",
            f"Open positions: {performance.open_positions}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="data/paper_trades.jsonl", help="paper-trading JSONL ledger path")
    args = parser.parse_args(argv)

    performance = calculate_paper_performance(read_jsonl_entries(args.ledger))
    print(format_paper_performance(performance))
    return 0


def _apply_position_delta(positions: dict[tuple[str, str], float], payload: dict[str, Any]) -> None:
    market_id = str(payload.get("market_id", ""))
    outcome = str(payload.get("outcome", ""))
    if not market_id or not outcome:
        return
    side = str(payload.get("side", "buy")).lower()
    shares = _float(payload.get("shares"))
    multiplier = -1.0 if side == "sell" else 1.0
    key = (market_id, outcome)
    positions[key] = positions.get(key, 0.0) + multiplier * shares


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
