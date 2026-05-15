import pytest

from weatherbot.data.stations import CityStation, get_city_station, supported_city_slugs
from weatherbot.data.weather import (
    ForecastParseError,
    ForecastSnapshot,
    build_open_meteo_daily_url,
    normalize_open_meteo_daily_highs,
    select_best_forecast,
)


def open_meteo_payload():
    return {
        "latitude": 40.75,
        "longitude": -73.87,
        "generationtime_ms": 1.5,
        "daily_units": {"time": "iso8601", "temperature_2m_max": "°F"},
        "daily": {
            "time": ["2026-06-01", "2026-06-02", "2026-06-03"],
            "temperature_2m_max": [72.4, None, 68.9],
        },
    }


def test_city_station_lookup_contains_core_metadata():
    station = get_city_station("nyc")

    assert isinstance(station, CityStation)
    assert station.slug == "nyc"
    assert station.name == "New York City"
    assert station.station == "KLGA"
    assert station.temperature_unit == "F"
    assert station.timezone == "America/New_York"
    assert "nyc" in supported_city_slugs()


def test_city_station_lookup_rejects_unknown_city():
    with pytest.raises(KeyError, match="unknown city"):
        get_city_station("atlantis")


def test_build_open_meteo_daily_url_uses_station_unit_timezone_and_no_api_key():
    station = get_city_station("nyc")

    url = build_open_meteo_daily_url(station, forecast_days=4, model="ecmwf_ifs025")

    assert "latitude=40.7772" in url
    assert "longitude=-73.8726" in url
    assert "daily=temperature_2m_max" in url
    assert "temperature_unit=fahrenheit" in url
    assert "timezone=America%2FNew_York" in url
    assert "models=ecmwf_ifs025" in url
    assert "api_key" not in url.lower()
    assert "token" not in url.lower()


def test_normalize_open_meteo_daily_highs_extracts_non_null_date_snapshots():
    station = get_city_station("nyc")

    snapshots = normalize_open_meteo_daily_highs(
        open_meteo_payload(),
        station=station,
        source="ecmwf",
        fetched_at="2026-05-30T12:00:00+00:00",
    )

    assert snapshots == [
        ForecastSnapshot(
            city_slug="nyc",
            city_name="New York City",
            station="KLGA",
            source="ecmwf",
            forecast_date="2026-06-01",
            fetched_at="2026-05-30T12:00:00+00:00",
            high_temperature=72.4,
            unit="F",
            horizon_days=2.0,
            metadata={"provider": "open-meteo"},
        ),
        ForecastSnapshot(
            city_slug="nyc",
            city_name="New York City",
            station="KLGA",
            source="ecmwf",
            forecast_date="2026-06-03",
            fetched_at="2026-05-30T12:00:00+00:00",
            high_temperature=68.9,
            unit="F",
            horizon_days=4.0,
            metadata={"provider": "open-meteo"},
        ),
    ]


def test_normalize_rejects_mismatched_time_and_temperature_lengths():
    payload = open_meteo_payload()
    payload["daily"]["temperature_2m_max"] = [70.0]

    with pytest.raises(ForecastParseError, match="length"):
        normalize_open_meteo_daily_highs(
            payload,
            station=get_city_station("nyc"),
            source="ecmwf",
            fetched_at="2026-05-30T12:00:00+00:00",
        )


def test_forecast_snapshot_redacts_secret_like_metadata():
    with pytest.raises(ForecastParseError, match="secret-like metadata"):
        ForecastSnapshot(
            city_slug="nyc",
            city_name="New York City",
            station="KLGA",
            source="visual-crossing",
            forecast_date="2026-06-01",
            fetched_at="2026-05-30T12:00:00+00:00",
            high_temperature=72.0,
            unit="F",
            horizon_days=2.0,
            metadata={"api_key": "should-not-be-stored"},
        )


def test_select_best_forecast_prefers_hrrr_for_us_short_horizon_else_ecmwf():
    station = get_city_station("nyc")
    ecmwf = ForecastSnapshot(
        city_slug=station.slug,
        city_name=station.name,
        station=station.station,
        source="ecmwf",
        forecast_date="2026-06-01",
        fetched_at="2026-05-31T12:00:00+00:00",
        high_temperature=73.0,
        unit="F",
        horizon_days=1.0,
        metadata={"provider": "open-meteo"},
    )
    hrrr = ForecastSnapshot(
        city_slug=station.slug,
        city_name=station.name,
        station=station.station,
        source="hrrr",
        forecast_date="2026-06-01",
        fetched_at="2026-05-31T12:00:00+00:00",
        high_temperature=72.0,
        unit="F",
        horizon_days=1.0,
        metadata={"provider": "open-meteo"},
    )

    assert select_best_forecast([ecmwf, hrrr], station=station) == hrrr
    assert select_best_forecast([ecmwf], station=station) == ecmwf

    london = get_city_station("london")
    london_ecmwf = ForecastSnapshot(
        city_slug=london.slug,
        city_name=london.name,
        station=london.station,
        source="ecmwf",
        forecast_date="2026-06-01",
        fetched_at="2026-05-31T12:00:00+00:00",
        high_temperature=21.0,
        unit="C",
        horizon_days=1.0,
        metadata={"provider": "open-meteo"},
    )
    london_hrrr = ForecastSnapshot(
        city_slug=london.slug,
        city_name=london.name,
        station=london.station,
        source="hrrr",
        forecast_date="2026-06-01",
        fetched_at="2026-05-31T12:00:00+00:00",
        high_temperature=20.0,
        unit="C",
        horizon_days=1.0,
        metadata={"provider": "open-meteo"},
    )

    assert select_best_forecast([london_ecmwf, london_hrrr], station=london) == london_ecmwf
