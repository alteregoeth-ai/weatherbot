import pytest

from weatherbot.strategy.probability import Bucket, bucket_probability


def test_normal_closed_bucket_probability_uses_continuity_correction():
    bucket = Bucket.closed(low=70, high=74)

    probability = bucket_probability(forecast_value=72, sigma=2.0, bucket=bucket)

    assert probability == pytest.approx(0.7887, abs=0.001)


def test_less_than_or_equal_bucket_probability_uses_upper_edge():
    bucket = Bucket.less_than_or_equal(69)

    probability = bucket_probability(forecast_value=70, sigma=2.0, bucket=bucket)

    assert probability == pytest.approx(0.4013, abs=0.001)


def test_greater_than_or_equal_bucket_probability_uses_lower_edge():
    bucket = Bucket.greater_than_or_equal(75)

    probability = bucket_probability(forecast_value=74, sigma=2.0, bucket=bucket)

    assert probability == pytest.approx(0.4013, abs=0.001)


def test_wider_sigma_lowers_confidence_for_same_bucket():
    bucket = Bucket.closed(low=70, high=74)

    tight = bucket_probability(forecast_value=72, sigma=1.0, bucket=bucket)
    wide = bucket_probability(forecast_value=72, sigma=5.0, bucket=bucket)

    assert tight > wide
    assert tight > 0.98
    assert wide < 0.40


def test_rejects_non_positive_sigma():
    with pytest.raises(ValueError, match="sigma"):
        bucket_probability(forecast_value=72, sigma=0, bucket=Bucket.closed(70, 74))


def test_rejects_invalid_closed_bucket_range():
    with pytest.raises(ValueError, match="low"):
        Bucket.closed(low=75, high=70)
