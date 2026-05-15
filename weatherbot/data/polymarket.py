"""Polymarket Gamma/CLOB parsing helpers for weather paper trading.

This module is intentionally read-only. It parses supplied Gamma event/market
payloads and optional CLOB orderbooks into `MarketCandidate` inputs for the paper
engine. It does not sign, submit, or cancel orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from typing import Any

from weatherbot.engine import MarketCandidate
from weatherbot.strategy.probability import Bucket


class PolymarketParseError(ValueError):
    """Raised when a Polymarket payload cannot be parsed safely."""


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class ParsedPolymarketMarket:
    event_id: str
    market_id: str
    market_slug: str
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    city: str
    event_date: str
    bucket: Bucket
    best_bid: float
    best_ask: float
    liquidity_usd: float
    volume_usd: float

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    def to_market_candidate(self, *, decision_id: str, forecast_value: float, sigma: float) -> MarketCandidate:
        return MarketCandidate(
            decision_id=decision_id,
            market_id=self.market_id,
            market_slug=self.market_slug,
            city=self.city,
            event_date=self.event_date,
            outcome="YES",
            forecast_value=forecast_value,
            sigma=sigma,
            bucket=self.bucket,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            liquidity_usd=self.liquidity_usd,
        )


def parse_temperature_bucket(question: str) -> Bucket:
    """Parse a Polymarket weather temperature bucket from market question text."""

    if not question:
        raise PolymarketParseError("question is required")
    number = r"(-?\d+(?:\.\d+)?)"
    lte = re.search(number + r"\s*°?\s*[FC]?\s+or below", question, re.IGNORECASE)
    if lte:
        return Bucket.less_than_or_equal(float(lte.group(1)))
    gte = re.search(number + r"\s*°?\s*[FC]?\s+or higher", question, re.IGNORECASE)
    if gte:
        return Bucket.greater_than_or_equal(float(gte.group(1)))
    between = re.search(
        r"between\s+" + number + r"\s*(?:-|to)\s*" + number + r"\s*°?\s*[FC]?",
        question,
        re.IGNORECASE,
    )
    if between:
        return Bucket.closed(float(between.group(1)), float(between.group(2)))
    single = re.search(r"be\s+" + number + r"\s*°?\s*[FC]?\s+on", question, re.IGNORECASE)
    if single:
        value = float(single.group(1))
        return Bucket.closed(value, value)
    raise PolymarketParseError(f"could not parse temperature bucket from question: {question}")


def parse_gamma_event_markets(
    event: dict[str, Any],
    *,
    books_by_yes_token: dict[str, dict[str, Any]] | None = None,
    min_liquidity_usd: float = 0.0,
    strict: bool = False,
) -> list[ParsedPolymarketMarket]:
    """Parse active liquid weather markets from a Gamma event payload."""

    books_by_yes_token = books_by_yes_token or {}
    event_id = str(event.get("id", ""))
    event_slug = str(event.get("slug", ""))
    city, event_date = _parse_city_and_date(event)
    parsed: list[ParsedPolymarketMarket] = []

    for market in event.get("markets", []) or []:
        try:
            parsed_market = _parse_market(
                event_id=event_id,
                event_slug=event_slug,
                city=city,
                event_date=event_date,
                market=market,
                book=books_by_yes_token.get(_peek_yes_token(market)),
                min_liquidity_usd=min_liquidity_usd,
            )
        except PolymarketParseError:
            if strict:
                raise
            continue
        if parsed_market is not None:
            parsed.append(parsed_market)
    return parsed


def _parse_market(
    *,
    event_id: str,
    event_slug: str,
    city: str,
    event_date: str,
    market: dict[str, Any],
    book: dict[str, Any] | None,
    min_liquidity_usd: float,
) -> ParsedPolymarketMarket | None:
    if market.get("closed") is True or market.get("active") is False:
        return None

    question = str(market.get("question", ""))
    bucket = parse_temperature_bucket(question)
    outcomes = _parse_json_array(market.get("outcomes"), "outcomes")
    token_ids = _parse_json_array(market.get("clobTokenIds"), "clobTokenIds")
    if len(outcomes) < 2 or len(token_ids) < 2:
        raise PolymarketParseError("outcomes and clobTokenIds must each contain Yes/No values")
    yes_index = _yes_index(outcomes)
    no_index = 1 - yes_index if len(outcomes) == 2 else _no_index(outcomes)
    yes_token = str(token_ids[yes_index])
    no_token = str(token_ids[no_index])

    liquidity = _float_field(market, "liquidity", default=_float_field(market, "volume", default=0.0))
    if liquidity < min_liquidity_usd:
        return None
    volume = _float_field(market, "volume", default=0.0)

    bid, ask = _best_bid_ask(book)
    if bid is None or ask is None:
        bid, ask = _fallback_bid_ask_from_prices(market, yes_index=yes_index)
    if bid is None or ask is None:
        raise PolymarketParseError("missing usable bid/ask")

    return ParsedPolymarketMarket(
        event_id=event_id,
        market_id=str(market.get("id", "")),
        market_slug=str(market.get("slug") or event_slug),
        condition_id=str(market.get("conditionId", "")),
        question=question,
        yes_token_id=yes_token,
        no_token_id=no_token,
        city=city,
        event_date=event_date,
        bucket=bucket,
        best_bid=bid,
        best_ask=ask,
        liquidity_usd=liquidity,
        volume_usd=volume,
    )


def _parse_city_and_date(event: dict[str, Any]) -> tuple[str, str]:
    slug = str(event.get("slug", ""))
    match = re.search(r"highest-temperature-in-(?P<city>.+)-on-(?P<month>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})", slug)
    if match:
        city = _title_city(match.group("city"))
        month = _MONTHS.get(match.group("month").lower())
        if month is None:
            raise PolymarketParseError("event slug contains unknown month")
        event_date = date(int(match.group("year")), month, int(match.group("day"))).isoformat()
        return city, event_date
    title = str(event.get("title", ""))
    title_match = re.search(r"in\s+(?P<city>.+?)\s+on\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})", title)
    if title_match:
        city = title_match.group("city").strip().rstrip("?")
        month = _MONTHS.get(title_match.group("month").lower())
        if month is None:
            raise PolymarketParseError("event title contains unknown month")
        event_date = date(int(title_match.group("year")), month, int(title_match.group("day"))).isoformat()
        return city, event_date
    raise PolymarketParseError("could not parse city/date from event")


def _title_city(slug_city: str) -> str:
    return " ".join(part.capitalize() for part in slug_city.split("-"))


def _parse_json_array(value: Any, field: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        raise PolymarketParseError(f"{field} must be a JSON array string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PolymarketParseError(f"could not parse {field}") from exc
    if not isinstance(parsed, list):
        raise PolymarketParseError(f"{field} must decode to a list")
    return parsed


def _peek_yes_token(market: dict[str, Any]) -> str:
    try:
        outcomes = _parse_json_array(market.get("outcomes"), "outcomes")
        token_ids = _parse_json_array(market.get("clobTokenIds"), "clobTokenIds")
        return str(token_ids[_yes_index(outcomes)])
    except Exception:
        return ""


def _yes_index(outcomes: list[Any]) -> int:
    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() == "yes":
            return index
    raise PolymarketParseError("outcomes missing Yes")


def _no_index(outcomes: list[Any]) -> int:
    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() == "no":
            return index
    raise PolymarketParseError("outcomes missing No")


def _float_field(data: dict[str, Any], field: str, *, default: float) -> float:
    value = data.get(field, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PolymarketParseError(f"{field} must be numeric") from exc


def _best_bid_ask(book: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not book:
        return None, None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None, None
    try:
        bid = max(float(level["price"]) for level in bids)
        ask = min(float(level["price"]) for level in asks)
    except (KeyError, TypeError, ValueError) as exc:
        raise PolymarketParseError("invalid orderbook price level") from exc
    _validate_price(bid, "best_bid")
    _validate_price(ask, "best_ask")
    if bid > ask:
        raise PolymarketParseError("best_bid cannot exceed best_ask")
    return bid, ask


def _fallback_bid_ask_from_prices(market: dict[str, Any], *, yes_index: int) -> tuple[float | None, float | None]:
    prices = _parse_json_array(market.get("outcomePrices"), "outcomePrices")
    if len(prices) <= yes_index:
        raise PolymarketParseError("outcomePrices missing Yes price")
    price = float(prices[yes_index])
    _validate_price(price, "outcomePrices Yes price")
    return price, price


def _validate_price(price: float, name: str) -> None:
    if not 0.0 <= price <= 1.0:
        raise PolymarketParseError(f"{name} must be between 0 and 1")
