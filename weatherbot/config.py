"""Configuration loading and safety validation for weatherbot."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal


class ConfigError(ValueError):
    """Raised when a weatherbot configuration is unsafe or invalid."""


Mode = Literal["paper", "live"]
Stage = Literal["paper", "stage_a", "stage_b"]


@dataclass(frozen=True)
class TradingConfig:
    max_bet: float
    min_edge: float
    max_spread: float
    min_liquidity_usd: float = 0.0


@dataclass(frozen=True)
class RiskConfig:
    max_daily_loss: float
    max_open_positions: int
    max_city_exposure: float
    max_event_exposure: float


@dataclass(frozen=True)
class ExecutionConfig:
    enable_live: bool
    dry_run: bool = True


@dataclass(frozen=True)
class ReportingConfig:
    telegram_enabled: bool = False


@dataclass(frozen=True)
class LedgerConfig:
    path: str = "data/trades.jsonl"


@dataclass(frozen=True)
class WeatherbotConfig:
    mode: Mode
    stage: Stage
    trading: TradingConfig
    risk: RiskConfig
    execution: ExecutionConfig
    reporting: ReportingConfig
    ledger: LedgerConfig


def load_config(path: str | Path) -> WeatherbotConfig:
    """Load a JSON config file and enforce paper/live safety gates."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON config: {exc}") from exc

    cfg = _parse_config(raw)
    validate_config(cfg)
    return cfg


def validate_config(cfg: WeatherbotConfig) -> None:
    """Validate config invariants that protect paper and tiny-live modes."""

    if cfg.mode not in ("paper", "live"):
        raise ConfigError("mode must be 'paper' or 'live'")
    if cfg.stage not in ("paper", "stage_a", "stage_b"):
        raise ConfigError("stage must be 'paper', 'stage_a', or 'stage_b'")
    if cfg.mode == "live" and not cfg.execution.enable_live:
        raise ConfigError("live mode requires execution.enable_live=true")
    if cfg.stage in ("paper", "stage_a"):
        _validate_stage_a_limits(cfg.trading)
    if cfg.risk.max_daily_loss < 0:
        raise ConfigError("risk.max_daily_loss must be non-negative")
    if cfg.risk.max_open_positions < 0:
        raise ConfigError("risk.max_open_positions must be non-negative")


def _validate_stage_a_limits(trading: TradingConfig) -> None:
    if trading.max_bet > 1.0:
        raise ConfigError("stage_a max_bet must be <= 1.0")
    if trading.min_edge < 0.15:
        raise ConfigError("stage_a min_edge must be >= 0.15")
    if trading.max_spread > 0.02:
        raise ConfigError("stage_a max_spread must be <= 0.02")


def _parse_config(raw: dict[str, Any]) -> WeatherbotConfig:
    try:
        trading_raw = raw["trading"]
        risk_raw = raw["risk"]
        execution_raw = raw["execution"]
    except KeyError as exc:
        raise ConfigError(f"missing required config section: {exc.args[0]}") from exc

    return WeatherbotConfig(
        mode=_required_str(raw, "mode"),  # type: ignore[arg-type]
        stage=_required_str(raw, "stage"),  # type: ignore[arg-type]
        trading=TradingConfig(
            max_bet=_number(trading_raw, "max_bet"),
            min_edge=_number(trading_raw, "min_edge"),
            max_spread=_number(trading_raw, "max_spread"),
            min_liquidity_usd=_number(trading_raw, "min_liquidity_usd", default=0.0),
        ),
        risk=RiskConfig(
            max_daily_loss=_number(risk_raw, "max_daily_loss"),
            max_open_positions=_int(risk_raw, "max_open_positions"),
            max_city_exposure=_number(risk_raw, "max_city_exposure"),
            max_event_exposure=_number(risk_raw, "max_event_exposure"),
        ),
        execution=ExecutionConfig(
            enable_live=_bool(execution_raw, "enable_live"),
            dry_run=_bool(execution_raw, "dry_run", default=True),
        ),
        reporting=ReportingConfig(
            telegram_enabled=_bool(raw.get("reporting", {}), "telegram_enabled", default=False),
        ),
        ledger=LedgerConfig(
            path=str(raw.get("ledger", {}).get("path", "data/trades.jsonl")),
        ),
    )


def _required_str(section: dict[str, Any], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string")
    return value


def _number(section: dict[str, Any], key: str, default: float | None = None) -> float:
    if key not in section:
        if default is not None:
            return default
        raise ConfigError(f"missing numeric config value: {key}")
    value = section[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{key} must be a number")
    if value < 0:
        raise ConfigError(f"{key} must be non-negative")
    return float(value)


def _int(section: dict[str, Any], key: str) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{key} must be an integer")
    if value < 0:
        raise ConfigError(f"{key} must be non-negative")
    return value


def _bool(section: dict[str, Any], key: str, default: bool | None = None) -> bool:
    if key not in section:
        if default is not None:
            return default
        raise ConfigError(f"missing boolean config value: {key}")
    value = section[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value
