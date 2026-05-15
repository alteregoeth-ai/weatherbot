import json
from pathlib import Path

import pytest

from weatherbot.config import ConfigError, load_config


def test_loads_default_paper_config():
    cfg = load_config(Path("config/default.paper.json"))
    assert cfg.mode == "paper"
    assert cfg.stage == "paper"
    assert cfg.trading.max_bet == 1.0
    assert cfg.trading.min_edge == 0.15
    assert cfg.trading.max_spread == 0.02
    assert cfg.execution.enable_live is False


def test_live_mode_requires_explicit_enable_live(tmp_path):
    path = tmp_path / "live.json"
    path.write_text(json.dumps({
        "mode": "live",
        "stage": "stage_a",
        "trading": {"max_bet": 1.0, "min_edge": 0.15, "max_spread": 0.02},
        "risk": {"max_daily_loss": 5.0, "max_open_positions": 5, "max_city_exposure": 3.0, "max_event_exposure": 1.0},
        "execution": {"enable_live": False}
    }))

    with pytest.raises(ConfigError, match="enable_live"):
        load_config(path)


def test_stage_a_rejects_max_bet_over_one_dollar(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "mode": "paper",
        "stage": "stage_a",
        "trading": {"max_bet": 1.01, "min_edge": 0.15, "max_spread": 0.02},
        "risk": {"max_daily_loss": 5.0, "max_open_positions": 5, "max_city_exposure": 3.0, "max_event_exposure": 1.0},
        "execution": {"enable_live": False}
    }))

    with pytest.raises(ConfigError, match="max_bet"):
        load_config(path)


def test_stage_a_rejects_edge_below_fifteen_percent(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "mode": "paper",
        "stage": "stage_a",
        "trading": {"max_bet": 1.0, "min_edge": 0.149, "max_spread": 0.02},
        "risk": {"max_daily_loss": 5.0, "max_open_positions": 5, "max_city_exposure": 3.0, "max_event_exposure": 1.0},
        "execution": {"enable_live": False}
    }))

    with pytest.raises(ConfigError, match="min_edge"):
        load_config(path)


def test_stage_a_rejects_spread_over_two_cents(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "mode": "paper",
        "stage": "stage_a",
        "trading": {"max_bet": 1.0, "min_edge": 0.15, "max_spread": 0.021},
        "risk": {"max_daily_loss": 5.0, "max_open_positions": 5, "max_city_exposure": 3.0, "max_event_exposure": 1.0},
        "execution": {"enable_live": False}
    }))

    with pytest.raises(ConfigError, match="max_spread"):
        load_config(path)
