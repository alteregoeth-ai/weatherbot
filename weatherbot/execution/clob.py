"""Guarded Polymarket CLOB execution wrapper.

This module provides safety gates and dry-run payload generation before any live
CLOB client integration is used. It does not import py-clob-client directly;
callers inject a client adapter so tests and paper runs remain dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from weatherbot.execution.orders import Order
from weatherbot.execution.signer import ClobCredentials
from weatherbot.risk.limits import RiskLimits


class ClobExecutionError(RuntimeError):
    """Raised when live execution would violate safety gates."""


class ClobClient(Protocol):
    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an order on the remote CLOB and return its response."""


@dataclass(frozen=True)
class ClobOrderResult:
    submitted: bool
    dry_run: bool
    payload: dict[str, Any]
    remote_order_id: str | None = None
    response: dict[str, Any] | None = None


class ClobExecutor:
    """Safety-gated wrapper around an injected Polymarket CLOB client."""

    def __init__(
        self,
        *,
        enable_live: bool,
        dry_run: bool,
        credentials: ClobCredentials,
        risk_limits: RiskLimits,
        client: ClobClient,
    ) -> None:
        if not enable_live:
            raise ClobExecutionError("live CLOB executor requires enable_live=true")
        self.dry_run = dry_run
        self.credentials = credentials
        self.risk_limits = risk_limits
        self.client = client

    def submit_order(self, order: Order) -> ClobOrderResult:
        self._validate_stage_a_order(order)
        payload = order_payload(order)
        if self.dry_run:
            return ClobOrderResult(submitted=False, dry_run=True, payload=payload)
        response = self.client.create_order(payload)
        return ClobOrderResult(
            submitted=True,
            dry_run=False,
            payload=payload,
            remote_order_id=_remote_order_id(response),
            response=response,
        )

    def _validate_stage_a_order(self, order: Order) -> None:
        if order.dollars is not None and order.dollars > self.risk_limits.max_bet:
            raise ClobExecutionError("order dollars exceeds stage_a max_bet")
        if order.dollars is None and order.shares is not None:
            notional = order.shares * order.limit_price
            if notional > self.risk_limits.max_bet:
                raise ClobExecutionError("order notional exceeds stage_a max_bet")


def order_payload(order: Order) -> dict[str, Any]:
    """Build the exact secret-free payload intended for CLOB submission."""

    payload: dict[str, Any] = {
        "market_id": order.market_id,
        "outcome": order.outcome,
        "side": order.side.value,
        "limit_price": order.limit_price,
        "decision_id": order.decision_id,
    }
    if order.dollars is not None:
        payload["dollars"] = order.dollars
    if order.shares is not None:
        payload["shares"] = order.shares
    return payload


def _remote_order_id(response: dict[str, Any]) -> str | None:
    value = response.get("order_id") or response.get("id")
    if value is None:
        return None
    return str(value)
