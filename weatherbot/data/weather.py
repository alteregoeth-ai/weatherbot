"""Weather forecast normalization helpers.

Provider adapters normalize external weather API payloads into secret-safe
`ForecastSnapshot` objects. This module stores provenance, not credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode
from typing import Any

from weatherbot.data.stations import CityStation


_SECRET_KEY_FRAGMENTS = (
    "secret",
    "private_key",
    "api_key",
    "apikey",
    "password",
    "passphrase",
    "token",
    "mnemonic",
    "seed",
)


class ForecastParseError(ValueError):
    """Raised when forecast provider data cannot be normalized safely."""


@dataclass(frozen=True)
class ForecastSnapshot:
    city_slug: str
    city_name: str
    station: str
    source: str
    forecast_date: str
    fetched_at: str
    high_temperature: float
    unit: str
    horizon_days: float
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.city_slug:
            raise ForecastParseError("city_slug is required")
        if not self.source:
            raise ForecastParseError("source is required")
        if self.unit not in {"F", "C"}:
            raise ForecastParseError("unit must be F or C")
        _validate_iso_date(self.forecast_date, "forecast_date")
        _parse_datetime(self.fetched_at, "fetched_at")
        if self.horizon_days < 0:
            raise ForecastParseError("horizon_days must be non-negative")
        if _contains_secret_like_key(self.metadata):
            raise ForecastParseError("secret-like metadata is not allowed")


def build_open_meteo_daily_url(
    station: CityStation,
    *,
    forecast_days: int = 7,
    model: str | None = "ecmwf_ifs025",
) -> str:
    """Build a credential-free Open-Meteo daily-high forecast URL."""

    if forecast_days <= 0:
        raise ValueError("forecast_days must be positive")
    temperature_unit = "fahrenheit" if station.temperature_unit == "F" else "celsius"
    params: dict[str, Any] = {
        "latitude": station.latitude,
        "longitude": station.longitude,
        "daily": "temperature_2m_max",
        "temperature_unit": temperature_unit,
        "forecast_days": forecast_days,
        "timezone": station.timezone,
        "bias_correction": "true",
    }
    if model:
        params["models"] = model
    return "https://api.open-meteo.com/v1/forecast?" + urlencode(params)


def normalize_open_meteo_daily_highs(
    payload: dict[str, Any],
    *,
    station: CityStation,
    source: str,
    fetched_at: str,
) -> list[ForecastSnapshot]:
    """Normalize Open-Meteo daily max temperature payload into snapshots."""

    try:
        daily = payload["daily"]
        dates = daily["time"]
        highs = daily["temperature_2m_max"]
    except KeyError as exc:
        raise ForecastParseError("payload missing daily time/temperature_2m_max") from exc
    if not isinstance(dates, list) or not isinstance(highs, list):
        raise ForecastParseError("daily time and temperature_2m_max must be lists")
    if len(dates) != len(highs):
        raise ForecastParseError("daily time and temperature_2m_max length mismatch")

    fetched_dt = _parse_datetime(fetched_at, "fetched_at")
    snapshots: list[ForecastSnapshot] = []
    for forecast_date, high in zip(dates, highs):
        if high is None:
            continue
        _validate_iso_date(str(forecast_date), "forecast_date")
        try:
            high_value = float(high)
        except (TypeError, ValueError) as exc:
            raise ForecastParseError("temperature_2m_max values must be numeric or null") from exc
        horizon_days = _days_between_dates(fetched_dt, str(forecast_date))
        snapshots.append(
            ForecastSnapshot(
                city_slug=station.slug,
                city_name=station.name,
                station=station.station,
                source=source,
                forecast_date=str(forecast_date),
                fetched_at=fetched_at,
                high_temperature=high_value,
                unit=station.temperature_unit,
                horizon_days=horizon_days,
                metadata={"provider": "open-meteo"},
            )
        )
    return snapshots


def select_best_forecast(snapshots: list[ForecastSnapshot], *, station: CityStation) -> ForecastSnapshot | None:
    """Select preferred forecast source for one city/date snapshot group."""

    if not snapshots:
        return None
    same_city = [snapshot for snapshot in snapshots if snapshot.city_slug == station.slug]
    candidates = same_city or snapshots
    if station.region == "us":
        hrrr = [snapshot for snapshot in candidates if snapshot.source.lower() == "hrrr" and snapshot.horizon_days <= 2.0]
        if hrrr:
            return max(hrrr, key=lambda snapshot: snapshot.fetched_at)
    ecmwf = [snapshot for snapshot in candidates if snapshot.source.lower() == "ecmwf"]
    if ecmwf:
        return max(ecmwf, key=lambda snapshot: snapshot.fetched_at)
    return max(candidates, key=lambda snapshot: snapshot.fetched_at)


def _validate_iso_date(value: str, field: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ForecastParseError(f"{field} must be YYYY-MM-DD") from exc


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ForecastParseError(f"{field} must be ISO-8601") from exc


def _days_between_dates(fetched_dt: datetime, forecast_date: str) -> float:
    forecast_dt = datetime.strptime(forecast_date, "%Y-%m-%d")
    return float((forecast_dt.date() - fetched_dt.date()).days)


def _contains_secret_like_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS):
                return True
            if _contains_secret_like_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_like_key(item) for item in value)
    return False
