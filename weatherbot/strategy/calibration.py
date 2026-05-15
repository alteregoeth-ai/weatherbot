"""Per-city/source forecast calibration for weather probabilities."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt


_DEFAULT_SIGMA_BY_UNIT = {
    "fahrenheit": 4.0,
    "celsius": 2.25,
    "inch": 0.25,
    "inches": 0.25,
    "mm": 6.0,
}


@dataclass(frozen=True)
class CalibrationKey:
    """Identity for a comparable forecast-error population."""

    city: str
    station: str
    source: str
    unit: str
    horizon_hours: int

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive")
        for field_name in ("city", "station", "source", "unit"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True)
class ForecastObservation:
    """Resolved forecast vs actual pair used for calibration."""

    key: CalibrationKey
    forecast_value: float
    actual_value: float

    def __post_init__(self) -> None:
        if self.actual_value is None:
            raise ValueError("actual_value is required for calibration")

    @property
    def error(self) -> float:
        return float(self.actual_value) - float(self.forecast_value)


class CalibrationStore:
    """In-memory calibration store using RMSE after enough observations.

    This is intentionally simple and deterministic. A later data-layer task can
    persist observations to JSONL/SQLite without changing the probability code.
    """

    def __init__(self, *, min_samples: int = 20, min_sigma: float = 0.5) -> None:
        if min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if min_sigma <= 0:
            raise ValueError("min_sigma must be positive")
        self._min_samples = min_samples
        self._min_sigma = float(min_sigma)
        self._errors: dict[CalibrationKey, list[float]] = defaultdict(list)

    def add_observation(self, observation: ForecastObservation) -> None:
        self._errors[observation.key].append(observation.error)

    def sample_count(self, key: CalibrationKey) -> int:
        return len(self._errors.get(key, []))

    def sigma_for(self, key: CalibrationKey) -> float:
        errors = self._errors.get(key, [])
        if len(errors) < self._min_samples:
            return max(self._min_sigma, default_sigma_for(key))
        rmse = sqrt(sum(error * error for error in errors) / len(errors))
        return max(self._min_sigma, rmse)


def default_sigma_for(key: CalibrationKey) -> float:
    """Return conservative default sigma for the key's unit and horizon.

    The horizon adjustment scales by sqrt(days) so longer forecasts get wider
    uncertainty without exploding linearly.
    """

    base = _DEFAULT_SIGMA_BY_UNIT.get(key.unit.lower(), 1.0)
    horizon_days = max(1.0, key.horizon_hours / 24.0)
    return base * sqrt(horizon_days)
