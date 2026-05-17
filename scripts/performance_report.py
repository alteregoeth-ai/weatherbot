#!/usr/bin/env python
"""Generate standard Weatherbot daily, weekly, and monthly performance reports."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Literal

Period = Literal["daily", "weekly", "monthly"]


@dataclass(frozen=True)
class ReportWindow:
    period: Period
    label: str
    title_label: str
    start: datetime
    end: datetime
    output_subdir: str
    output_name: str


@dataclass(frozen=True)
class ReportMetrics:
    decisions: int
    approved: int
    rejected: int
    fills: int
    order_rejections: int
    errors: int
    approval_rate: float
    fill_rate: float
    average_edge: float
    total_staked: float
    realized_pnl: float
    open_positions: int
    exposure_by_city: dict[str, float]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=("daily", "weekly", "monthly"), required=True)
    parser.add_argument("--as-of", default=None, help="UTC timestamp used to choose the previous complete period")
    parser.add_argument("--ledger", default="data/paper_trades.jsonl")
    parser.add_argument("--output-dir", default="reports/performance")
    args = parser.parse_args(argv)

    as_of = _parse_as_of(args.as_of)
    window = report_window(args.period, as_of)
    entries = filter_entries_for_window(read_jsonl_entries(args.ledger), window)
    metrics = calculate_report_metrics(entries)
    output_path = write_report(window, metrics, Path(args.output_dir))
    print(output_path)
    return 0


def report_window(period: Period, as_of: datetime) -> ReportWindow:
    as_of = as_of.astimezone(timezone.utc)
    today = as_of.date()
    if period == "daily":
        report_date = today - timedelta(days=1)
        start = datetime.combine(report_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(report_date, time.max, tzinfo=timezone.utc)
        label = report_date.isoformat()
        return ReportWindow(period, label, label, start, end, "daily", f"{label}.md")
    if period == "weekly":
        this_week_monday = today - timedelta(days=today.weekday())
        start_date = this_week_monday - timedelta(days=7)
        end_date = start_date + timedelta(days=6)
        start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
        iso_year, iso_week, _ = start_date.isocalendar()
        label = f"{iso_year}-W{iso_week:02d}"
        title_label = f"{label} ({start_date.isoformat()} to {end_date.isoformat()})"
        return ReportWindow(period, label, title_label, start, end, "weekly", f"{label}.md")
    first_of_this_month = today.replace(day=1)
    previous_month_end = first_of_this_month - timedelta(days=1)
    start_date = previous_month_end.replace(day=1)
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(previous_month_end, time.max, tzinfo=timezone.utc)
    label = f"{start_date.year:04d}-{start_date.month:02d}"
    return ReportWindow(period, label, label, start, end, "monthly", f"{label}.md")


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


def filter_entries_for_window(entries: Iterable[dict[str, Any]], window: ReportWindow) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for entry in entries:
        timestamp = entry.get("timestamp")
        if not timestamp:
            continue
        try:
            when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        if window.start <= when <= window.end:
            selected.append(entry)
    return selected


def calculate_report_metrics(entries: Iterable[dict[str, Any]]) -> ReportMetrics:
    decisions = approved = rejected = fills = order_rejections = errors = 0
    edges: list[float] = []
    total_staked = 0.0
    realized_pnl = 0.0
    positions: dict[tuple[str, str], float] = {}
    exposure_by_city: dict[str, float] = {}

    for entry in entries:
        event_type = str(entry.get("event_type", ""))
        payload = entry.get("payload") or {}
        if event_type == "decision":
            decisions += 1
            edges.append(_float(payload.get("edge")))
            city = str(payload.get("city", "unknown"))
            exposure_by_city[city] = exposure_by_city.get(city, 0.0) + _float(payload.get("dollars"))
            if payload.get("risk_approved") is True:
                approved += 1
            else:
                rejected += 1
        elif event_type in ("paper_fill", "live_fill"):
            fills += 1
            total_staked += _float(payload.get("dollars"))
            _apply_position_delta(positions, payload)
        elif event_type in ("paper_order_rejected", "live_order_rejected"):
            order_rejections += 1
        elif event_type == "daily_pnl":
            realized_pnl += _float(payload.get("realized_pnl"))
        elif event_type == "error":
            errors += 1

    approval_rate = approved / decisions if decisions else 0.0
    fill_rate = fills / approved if approved else 0.0
    average_edge = sum(edges) / len(edges) if edges else 0.0
    open_positions = sum(1 for shares in positions.values() if abs(shares) > 1e-12)
    return ReportMetrics(
        decisions=decisions,
        approved=approved,
        rejected=rejected,
        fills=fills,
        order_rejections=order_rejections,
        errors=errors,
        approval_rate=approval_rate,
        fill_rate=fill_rate,
        average_edge=average_edge,
        total_staked=total_staked,
        realized_pnl=realized_pnl,
        open_positions=open_positions,
        exposure_by_city=dict(sorted(exposure_by_city.items())),
    )


def write_report(window: ReportWindow, metrics: ReportMetrics, output_dir: Path) -> Path:
    path = output_dir / window.output_subdir / window.output_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_report(window, metrics), encoding="utf-8")
    return path


def format_report(window: ReportWindow, metrics: ReportMetrics) -> str:
    period_name = window.period.capitalize()
    lines = [
        f"# Weatherbot {period_name} Performance Report — {window.title_label}",
        "",
        f"Period: {window.start:%Y-%m-%d %H:%M} UTC to {window.end:%Y-%m-%d %H:%M} UTC",
        "Mode: paper trading",
        "Resource profile: low resource / serial execution",
        "",
        "## Executive Summary",
        f"- Decisions: {metrics.decisions}",
        f"- Approved: {metrics.approved}",
        f"- Rejected: {metrics.rejected}",
        f"- Fills: {metrics.fills}",
        f"- Order rejections: {metrics.order_rejections}",
        f"- Errors: {metrics.errors}",
        "",
        "## Performance Metrics",
        f"- Approval rate: {metrics.approval_rate:.2%}",
        f"- Fill rate: {metrics.fill_rate:.2%}",
        f"- Average edge: {metrics.average_edge:.2%}",
        f"- Total staked: ${metrics.total_staked:.2f}",
        f"- Realized PnL: ${metrics.realized_pnl:.2f}",
        f"- Open positions: {metrics.open_positions}",
        "",
        "## Exposure by City",
    ]
    if metrics.exposure_by_city:
        lines.extend(f"- {city}: ${amount:.2f}" for city, amount in metrics.exposure_by_city.items())
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Review Notes",
            "- Check whether approvals align with min-edge and spread rules.",
            "- Investigate any order rejections or errors before increasing size.",
            "- Compare realized PnL to expected edge after markets resolve.",
            "",
        ]
    )
    return "\n".join(lines)


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


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
