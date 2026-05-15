"""Probability helpers for weather outcome buckets.

Polymarket weather markets usually settle to discrete integer temperatures or
rainfall totals. The helpers here model the realized value as a normal
forecast distribution and apply a 0.5-unit continuity correction around integer
bucket boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import erf, sqrt


class BucketKind(str, Enum):
    CLOSED = "closed"
    LTE = "lte"
    GTE = "gte"


@dataclass(frozen=True)
class Bucket:
    """A discrete outcome bucket for a weather market."""

    kind: BucketKind
    low: float | None = None
    high: float | None = None

    @classmethod
    def closed(cls, low: float, high: float) -> "Bucket":
        if low > high:
            raise ValueError("closed bucket low must be <= high")
        return cls(kind=BucketKind.CLOSED, low=float(low), high=float(high))

    @classmethod
    def less_than_or_equal(cls, high: float) -> "Bucket":
        return cls(kind=BucketKind.LTE, high=float(high))

    @classmethod
    def greater_than_or_equal(cls, low: float) -> "Bucket":
        return cls(kind=BucketKind.GTE, low=float(low))


def bucket_probability(forecast_value: float, sigma: float, bucket: Bucket) -> float:
    """Return probability that realized value lands in the bucket.

    Args:
        forecast_value: Mean forecast value for the market unit.
        sigma: Calibrated forecast standard deviation in the same unit.
        bucket: Target outcome bucket.

    Returns:
        A probability in [0, 1].
    """

    if sigma <= 0:
        raise ValueError("sigma must be positive")

    mean = float(forecast_value)
    stddev = float(sigma)

    if bucket.kind == BucketKind.CLOSED:
        assert bucket.low is not None and bucket.high is not None
        lower = bucket.low - 0.5
        upper = bucket.high + 0.5
        return _clamp_probability(_normal_cdf(upper, mean, stddev) - _normal_cdf(lower, mean, stddev))

    if bucket.kind == BucketKind.LTE:
        assert bucket.high is not None
        return _clamp_probability(_normal_cdf(bucket.high + 0.5, mean, stddev))

    if bucket.kind == BucketKind.GTE:
        assert bucket.low is not None
        return _clamp_probability(1.0 - _normal_cdf(bucket.low - 0.5, mean, stddev))

    raise ValueError(f"unsupported bucket kind: {bucket.kind}")


def _normal_cdf(x: float, mean: float, stddev: float) -> float:
    z = (x - mean) / (stddev * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))


def _clamp_probability(value: float) -> float:
    return min(1.0, max(0.0, value))
