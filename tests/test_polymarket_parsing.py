import pytest

from weatherbot.data.polymarket import (
    ParsedPolymarketMarket,
    PolymarketParseError,
    parse_gamma_event_markets,
    parse_temperature_bucket,
)
from weatherbot.strategy.probability import BucketKind


def gamma_event():
    return {
        "id": "event-1",
        "slug": "highest-temperature-in-new-york-city-on-june-1-2026",
        "title": "Highest temperature in New York City on June 1, 2026?",
        "volume": 10000,
        "liquidity": 2000,
        "endDate": "2026-06-02T00:00:00Z",
        "markets": [
            {
                "id": "m-70-74",
                "slug": "nyc-70-74",
                "question": "Will the highest temperature in New York City be between 70-74°F on June 1?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.44", "0.56"]',
                "clobTokenIds": '["yes-token-70-74", "no-token-70-74"]',
                "conditionId": "0xabc",
                "volume": "500",
                "liquidity": "250",
                "active": True,
                "closed": False,
            },
            {
                "id": "m-bad",
                "question": "Will it rain in New York City?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.20", "0.80"]',
                "volume": "500",
                "liquidity": "250",
                "active": True,
                "closed": False,
            },
        ],
    }


def test_parse_temperature_bucket_closed_range():
    bucket = parse_temperature_bucket("Will the high be between 70-74°F?")

    assert bucket.kind == BucketKind.CLOSED
    assert bucket.low == 70
    assert bucket.high == 74


def test_parse_temperature_bucket_edge_ranges():
    lte = parse_temperature_bucket("Will the high be 69°F or below?")
    gte = parse_temperature_bucket("Will the high be 75°F or higher?")

    assert lte.kind == BucketKind.LTE
    assert lte.high == 69
    assert gte.kind == BucketKind.GTE
    assert gte.low == 75


def test_parse_temperature_bucket_single_degree():
    bucket = parse_temperature_bucket("Will the temperature be 72°F on June 1?")

    assert bucket.kind == BucketKind.CLOSED
    assert bucket.low == 72
    assert bucket.high == 72


def test_gamma_event_markets_parse_double_encoded_fields_and_orderbook_top():
    books = {
        "yes-token-70-74": {
            "bids": [{"price": "0.43", "size": "100"}],
            "asks": [{"price": "0.44", "size": "80"}],
        }
    }

    markets = parse_gamma_event_markets(gamma_event(), books_by_yes_token=books, min_liquidity_usd=100)

    assert len(markets) == 1
    market = markets[0]
    assert isinstance(market, ParsedPolymarketMarket)
    assert market.event_id == "event-1"
    assert market.market_id == "m-70-74"
    assert market.market_slug == "nyc-70-74"
    assert market.condition_id == "0xabc"
    assert market.yes_token_id == "yes-token-70-74"
    assert market.no_token_id == "no-token-70-74"
    assert market.city == "New York City"
    assert market.event_date == "2026-06-01"
    assert market.best_bid == pytest.approx(0.43)
    assert market.best_ask == pytest.approx(0.44)
    assert market.spread == pytest.approx(0.01)
    assert market.liquidity_usd == pytest.approx(250)
    assert market.bucket.low == 70
    assert market.bucket.high == 74


def test_gamma_event_parser_rejects_closed_inactive_low_liquidity_and_missing_books():
    event = gamma_event()
    event["markets"][0]["liquidity"] = "99.99"

    markets = parse_gamma_event_markets(event, books_by_yes_token={}, min_liquidity_usd=100)

    assert markets == []


def test_parsed_market_converts_to_engine_candidate_with_forecast_and_sigma():
    parsed = parse_gamma_event_markets(
        gamma_event(),
        books_by_yes_token={"yes-token-70-74": {"bids": [{"price": "0.43", "size": "100"}], "asks": [{"price": "0.44", "size": "80"}]}},
        min_liquidity_usd=100,
    )[0]

    candidate = parsed.to_market_candidate(decision_id="run-1:m-70-74", forecast_value=72.0, sigma=2.0)

    assert candidate.decision_id == "run-1:m-70-74"
    assert candidate.market_id == "m-70-74"
    assert candidate.market_slug == "nyc-70-74"
    assert candidate.city == "New York City"
    assert candidate.event_date == "2026-06-01"
    assert candidate.forecast_value == 72.0
    assert candidate.sigma == 2.0
    assert candidate.best_bid == pytest.approx(0.43)
    assert candidate.best_ask == pytest.approx(0.44)


def test_invalid_double_encoded_json_raises_parse_error_for_strict_single_market_parse():
    event = gamma_event()
    event["markets"] = [dict(event["markets"][0], outcomes="not-json")]

    with pytest.raises(PolymarketParseError, match="outcomes"):
        parse_gamma_event_markets(event, strict=True)
