"""Paper-trading decision engine wiring strategy, risk, ledger, and broker."""

from __future__ import annotations

from dataclasses import dataclass

from weatherbot.execution.orders import Order, OrderFill, OrderSide, OrderStatus, PaperBroker
from weatherbot.ledger import ImmutableLedger, LedgerEntry
from weatherbot.risk.exposure import ExposureBook, TradeCandidate
from weatherbot.risk.kill_switch import KillSwitch
from weatherbot.risk.limits import RiskLimits, evaluate_trade_risk
from weatherbot.strategy.ev import probability_edge
from weatherbot.strategy.probability import Bucket, bucket_probability
from weatherbot.strategy.sizing import capped_kelly_bet


@dataclass(frozen=True)
class MarketCandidate:
    decision_id: str
    market_id: str
    market_slug: str
    city: str
    event_date: str
    outcome: str
    forecast_value: float
    sigma: float
    bucket: Bucket
    best_bid: float
    best_ask: float
    liquidity_usd: float

    def __post_init__(self) -> None:
        for name in ("decision_id", "market_id", "market_slug", "city", "event_date", "outcome"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        _validate_book_price(self.best_bid, "best_bid")
        _validate_book_price(self.best_ask, "best_ask")
        if self.best_bid > self.best_ask:
            raise ValueError("best_bid cannot exceed best_ask")
        if self.liquidity_usd < 0:
            raise ValueError("liquidity_usd must be non-negative")


@dataclass(frozen=True)
class EngineResult:
    approved: bool
    reasons: list[str]
    probability: float
    edge: float
    dollars: float
    order_fill: OrderFill | None = None


class PaperTradingEngine:
    """Evaluate one market candidate and, if safe, submit a paper order."""

    def __init__(
        self,
        *,
        run_id: str,
        config_hash: str,
        broker: PaperBroker,
        ledger: ImmutableLedger,
        risk_limits: RiskLimits,
        exposure_book: ExposureBook,
        kill_switch: KillSwitch,
        bankroll: float,
        kelly_fraction_cap: float,
        realized_daily_pnl: float,
    ) -> None:
        self.run_id = run_id
        self.config_hash = config_hash
        self.broker = broker
        self.ledger = ledger
        self.risk_limits = risk_limits
        self.exposure_book = exposure_book
        self.kill_switch = kill_switch
        self.bankroll = bankroll
        self.kelly_fraction_cap = kelly_fraction_cap
        self.realized_daily_pnl = realized_daily_pnl

    def evaluate_and_trade(self, candidate: MarketCandidate) -> EngineResult:
        probability = bucket_probability(candidate.forecast_value, candidate.sigma, candidate.bucket)
        edge = probability_edge(probability, candidate.best_ask)
        dollars = capped_kelly_bet(
            probability,
            candidate.best_ask,
            bankroll=self.bankroll,
            max_bet=self.risk_limits.max_bet,
            kelly_fraction_cap=self.kelly_fraction_cap,
        )

        if self.kill_switch.is_triggered():
            reasons = ["kill_switch"]
            self._log_decision(
                candidate,
                probability=probability,
                edge=edge,
                dollars=dollars,
                risk_approved=False,
                risk_reasons=reasons,
                extra={"kill_switch_reason": self.kill_switch.reason()},
            )
            return EngineResult(False, reasons, probability, edge, dollars, None)

        risk_candidate = TradeCandidate(
            decision_id=candidate.decision_id,
            market_id=candidate.market_id,
            city=candidate.city,
            event_date=candidate.event_date,
            outcome=candidate.outcome,
            dollars=dollars if dollars > 0 else self.risk_limits.max_bet,
            edge=edge,
            spread=candidate.best_ask - candidate.best_bid,
            liquidity_usd=candidate.liquidity_usd,
        )
        risk_decision = evaluate_trade_risk(
            risk_candidate,
            self.risk_limits,
            self.exposure_book,
            realized_daily_pnl=self.realized_daily_pnl,
        )
        self._log_decision(
            candidate,
            probability=probability,
            edge=edge,
            dollars=dollars,
            risk_approved=risk_decision.approved,
            risk_reasons=risk_decision.reasons,
        )
        if not risk_decision.approved:
            return EngineResult(False, risk_decision.reasons, probability, edge, dollars, None)

        order = Order(
            decision_id=candidate.decision_id,
            market_id=candidate.market_id,
            outcome=candidate.outcome,
            side=OrderSide.BUY,
            limit_price=candidate.best_bid + self.risk_limits.max_spread,
            dollars=dollars,
        )
        fill = self.broker.submit_limit_order(order, best_bid=candidate.best_bid, best_ask=candidate.best_ask)
        event_type = "paper_fill" if fill.status == OrderStatus.FILLED else "paper_order_open"
        if fill.status == OrderStatus.REJECTED:
            event_type = "paper_order_rejected"
        self._log_order(candidate, fill, event_type=event_type)
        return EngineResult(True, [], probability, edge, dollars, fill)

    def _log_decision(
        self,
        candidate: MarketCandidate,
        *,
        probability: float,
        edge: float,
        dollars: float,
        risk_approved: bool,
        risk_reasons: list[str],
        extra: dict | None = None,
    ) -> None:
        payload = {
            "market_id": candidate.market_id,
            "market_slug": candidate.market_slug,
            "city": candidate.city,
            "event_date": candidate.event_date,
            "outcome": candidate.outcome,
            "probability": probability,
            "edge": edge,
            "spread": candidate.best_ask - candidate.best_bid,
            "dollars": dollars,
            "risk_approved": risk_approved,
            "risk_reasons": risk_reasons,
        }
        if extra:
            payload.update(extra)
        self.ledger.append(
            LedgerEntry(
                run_id=self.run_id,
                decision_id=candidate.decision_id,
                event_type="decision",
                config_hash=self.config_hash,
                payload=payload,
            )
        )

    def _log_order(self, candidate: MarketCandidate, fill: OrderFill, *, event_type: str) -> None:
        self.ledger.append(
            LedgerEntry(
                run_id=self.run_id,
                decision_id=candidate.decision_id,
                event_type=event_type,
                config_hash=self.config_hash,
                payload={
                    "market_id": candidate.market_id,
                    "market_slug": candidate.market_slug,
                    "outcome": candidate.outcome,
                    "side": fill.order.side.value,
                    "status": fill.status.value,
                    "limit_price": fill.order.limit_price,
                    "fill_price": fill.price,
                    "shares": fill.shares,
                    "dollars": fill.dollars,
                    "reason": fill.reason,
                },
            )
        )


def _validate_book_price(price: float, name: str) -> None:
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
