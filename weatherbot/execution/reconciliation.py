"""Reconcile local ledger state against remote CLOB fills and positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class LocalFill:
    decision_id: str
    market_id: str
    outcome: str
    shares: float
    price: float
    dollars: float

    @classmethod
    def from_ledger_entries(cls, entries: Iterable[dict[str, Any]]) -> list["LocalFill"]:
        fills: list[LocalFill] = []
        for entry in entries:
            if entry.get("event_type") not in ("paper_fill", "live_fill"):
                continue
            payload = entry.get("payload") or {}
            fills.append(
                cls(
                    decision_id=str(entry.get("decision_id", "")),
                    market_id=str(payload.get("market_id", "")),
                    outcome=str(payload.get("outcome", "")),
                    shares=float(payload.get("shares", 0.0)),
                    price=float(payload.get("fill_price", payload.get("price", 0.0))),
                    dollars=float(payload.get("dollars", 0.0)),
                )
            )
        return fills


@dataclass(frozen=True)
class RemoteFill:
    decision_id: str
    remote_order_id: str
    market_id: str
    outcome: str
    shares: float
    price: float
    dollars: float


@dataclass(frozen=True)
class PositionSnapshot:
    market_id: str
    outcome: str
    shares: float


@dataclass(frozen=True)
class ReconciliationIssue:
    code: str
    detail: str
    decision_id: str | None = None
    market_id: str | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    issues: list[ReconciliationIssue]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def can_open_new_trades(self) -> bool:
        return self.ok


def reconcile_execution_state(
    *,
    local_fills: Iterable[LocalFill],
    remote_fills: Iterable[RemoteFill],
    local_positions: Iterable[PositionSnapshot],
    remote_positions: Iterable[PositionSnapshot],
    tolerance: float = 1e-9,
) -> ReconciliationReport:
    """Compare local and remote execution state.

    Any reconciliation issue blocks new trades until resolved.
    """

    issues: list[ReconciliationIssue] = []
    local_fill_map = {_fill_key(fill): fill for fill in local_fills}
    remote_fill_map = {_fill_key(fill): fill for fill in remote_fills}

    for key, fill in local_fill_map.items():
        if key not in remote_fill_map:
            issues.append(
                ReconciliationIssue(
                    code="missing_remote_fill",
                    decision_id=fill.decision_id,
                    market_id=fill.market_id,
                    outcome=fill.outcome,
                    detail="local fill has no matching remote fill",
                )
            )
    for key, fill in remote_fill_map.items():
        if key not in local_fill_map:
            issues.append(
                ReconciliationIssue(
                    code="missing_local_fill",
                    decision_id=fill.decision_id,
                    market_id=fill.market_id,
                    outcome=fill.outcome,
                    detail="remote fill has no matching local ledger fill",
                )
            )

    local_position_map = _position_map(local_positions)
    remote_position_map = _position_map(remote_positions)
    for key in sorted(set(local_position_map) | set(remote_position_map)):
        local_shares = local_position_map.get(key, 0.0)
        remote_shares = remote_position_map.get(key, 0.0)
        if abs(local_shares - remote_shares) > tolerance:
            market_id, outcome = key
            issues.append(
                ReconciliationIssue(
                    code="position_mismatch",
                    market_id=market_id,
                    outcome=outcome,
                    detail=f"local shares {local_shares} != remote shares {remote_shares}",
                )
            )

    return ReconciliationReport(issues=issues)


def _fill_key(fill: LocalFill | RemoteFill) -> tuple[str, str, str]:
    return (fill.decision_id, fill.market_id, fill.outcome)


def _position_map(positions: Iterable[PositionSnapshot]) -> dict[tuple[str, str], float]:
    by_market: dict[tuple[str, str], float] = {}
    for position in positions:
        key = (position.market_id, position.outcome)
        by_market[key] = by_market.get(key, 0.0) + position.shares
    return by_market
