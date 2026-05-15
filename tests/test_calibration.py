import pytest

from weatherbot.strategy.calibration import (
    CalibrationKey,
    CalibrationStore,
    ForecastObservation,
)


def test_uses_safe_default_sigma_when_no_city_specific_history_exists():
    store = CalibrationStore(min_samples=5)
    key = CalibrationKey(city="New York", station="KNYC", source="visual_crossing", unit="fahrenheit", horizon_hours=24)

    assert store.sigma_for(key) == pytest.approx(4.0)


def test_uses_horizon_adjusted_default_sigma_for_longer_forecasts():
    store = CalibrationStore(min_samples=5)
    key = CalibrationKey(city="Austin", station="KAUS", source="visual_crossing", unit="fahrenheit", horizon_hours=72)

    assert store.sigma_for(key) > 4.0
    assert store.sigma_for(key) == pytest.approx(6.9282, abs=0.001)


def test_refuses_city_specific_calibration_below_minimum_sample_size():
    store = CalibrationStore(min_samples=3)
    key = CalibrationKey(city="Chicago", station="KORD", source="visual_crossing", unit="fahrenheit", horizon_hours=24)

    store.add_observation(ForecastObservation(key=key, forecast_value=70, actual_value=72))
    store.add_observation(ForecastObservation(key=key, forecast_value=70, actual_value=68))

    assert store.sample_count(key) == 2
    assert store.sigma_for(key) == pytest.approx(4.0)


def test_updates_sigma_from_resolved_forecast_errors_after_minimum_samples():
    store = CalibrationStore(min_samples=3, min_sigma=0.5)
    key = CalibrationKey(city="Chicago", station="KORD", source="visual_crossing", unit="fahrenheit", horizon_hours=24)

    store.add_observation(ForecastObservation(key=key, forecast_value=70, actual_value=72))
    store.add_observation(ForecastObservation(key=key, forecast_value=70, actual_value=68))
    store.add_observation(ForecastObservation(key=key, forecast_value=70, actual_value=73))

    # Errors: 2, -2, 3. RMSE = sqrt((4 + 4 + 9) / 3)
    assert store.sample_count(key) == 3
    assert store.sigma_for(key) == pytest.approx(2.3804, abs=0.001)


def test_separates_calibration_by_city_station_source_unit_and_horizon():
    store = CalibrationStore(min_samples=1, min_sigma=0.5)
    chicago = CalibrationKey(city="Chicago", station="KORD", source="visual_crossing", unit="fahrenheit", horizon_hours=24)
    chicago_other_source = CalibrationKey(city="Chicago", station="KORD", source="noaa", unit="fahrenheit", horizon_hours=24)

    store.add_observation(ForecastObservation(key=chicago, forecast_value=70, actual_value=80))

    assert store.sigma_for(chicago) == pytest.approx(10.0)
    assert store.sigma_for(chicago_other_source) == pytest.approx(4.0)


def test_enforces_min_sigma_so_one_lucky_sample_does_not_create_overconfidence():
    store = CalibrationStore(min_samples=1, min_sigma=1.5)
    key = CalibrationKey(city="Phoenix", station="KPHX", source="visual_crossing", unit="fahrenheit", horizon_hours=24)

    store.add_observation(ForecastObservation(key=key, forecast_value=100, actual_value=100.1))

    assert store.sigma_for(key) == pytest.approx(1.5)


def test_rejects_unresolved_or_invalid_observations():
    key = CalibrationKey(city="Miami", station="KMIA", source="visual_crossing", unit="fahrenheit", horizon_hours=24)

    with pytest.raises(ValueError, match="actual_value"):
        ForecastObservation(key=key, forecast_value=80, actual_value=None)

    with pytest.raises(ValueError, match="horizon_hours"):
        CalibrationKey(city="Miami", station="KMIA", source="visual_crossing", unit="fahrenheit", horizon_hours=0)
