"""Supported weather market city/station metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CityStation:
    slug: str
    name: str
    latitude: float
    longitude: float
    station: str
    temperature_unit: str
    region: str
    timezone: str


_STATIONS: dict[str, CityStation] = {
    "nyc": CityStation("nyc", "New York City", 40.7772, -73.8726, "KLGA", "F", "us", "America/New_York"),
    "chicago": CityStation("chicago", "Chicago", 41.9742, -87.9073, "KORD", "F", "us", "America/Chicago"),
    "miami": CityStation("miami", "Miami", 25.7959, -80.2870, "KMIA", "F", "us", "America/New_York"),
    "dallas": CityStation("dallas", "Dallas", 32.8471, -96.8518, "KDAL", "F", "us", "America/Chicago"),
    "seattle": CityStation("seattle", "Seattle", 47.4502, -122.3088, "KSEA", "F", "us", "America/Los_Angeles"),
    "atlanta": CityStation("atlanta", "Atlanta", 33.6407, -84.4277, "KATL", "F", "us", "America/New_York"),
    "london": CityStation("london", "London", 51.5048, 0.0495, "EGLC", "C", "eu", "Europe/London"),
    "paris": CityStation("paris", "Paris", 48.9962, 2.5979, "LFPG", "C", "eu", "Europe/Paris"),
    "munich": CityStation("munich", "Munich", 48.3537, 11.7750, "EDDM", "C", "eu", "Europe/Berlin"),
    "ankara": CityStation("ankara", "Ankara", 40.1281, 32.9951, "LTAC", "C", "eu", "Europe/Istanbul"),
    "seoul": CityStation("seoul", "Seoul", 37.4691, 126.4505, "RKSI", "C", "asia", "Asia/Seoul"),
    "tokyo": CityStation("tokyo", "Tokyo", 35.7647, 140.3864, "RJTT", "C", "asia", "Asia/Tokyo"),
    "shanghai": CityStation("shanghai", "Shanghai", 31.1443, 121.8083, "ZSPD", "C", "asia", "Asia/Shanghai"),
    "singapore": CityStation("singapore", "Singapore", 1.3502, 103.9940, "WSSS", "C", "asia", "Asia/Singapore"),
    "lucknow": CityStation("lucknow", "Lucknow", 26.7606, 80.8893, "VILK", "C", "asia", "Asia/Kolkata"),
    "tel-aviv": CityStation("tel-aviv", "Tel Aviv", 32.0114, 34.8867, "LLBG", "C", "asia", "Asia/Jerusalem"),
    "toronto": CityStation("toronto", "Toronto", 43.6772, -79.6306, "CYYZ", "C", "ca", "America/Toronto"),
    "sao-paulo": CityStation("sao-paulo", "Sao Paulo", -23.4356, -46.4731, "SBGR", "C", "sa", "America/Sao_Paulo"),
    "buenos-aires": CityStation("buenos-aires", "Buenos Aires", -34.8222, -58.5358, "SAEZ", "C", "sa", "America/Argentina/Buenos_Aires"),
    "wellington": CityStation("wellington", "Wellington", -41.3272, 174.8052, "NZWN", "C", "oc", "Pacific/Auckland"),
}


def get_city_station(slug: str) -> CityStation:
    try:
        return _STATIONS[slug]
    except KeyError as exc:
        raise KeyError(f"unknown city: {slug}") from exc


def supported_city_slugs() -> tuple[str, ...]:
    return tuple(sorted(_STATIONS))
