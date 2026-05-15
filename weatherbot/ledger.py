"""Append-only, secret-safe JSONL ledger for decisions and paper/live orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class LedgerValidationError(ValueError):
    """Raised when a ledger entry is missing audit fields or contains secrets."""


_SECRET_KEY_FRAGMENTS = (
    "secret",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "password",
    "passphrase",
    "token",
    "mnemonic",
    "seed",
)


@dataclass(frozen=True)
class LedgerEntry:
    run_id: str
    decision_id: str
    event_type: str
    config_hash: str
    payload: dict[str, Any]


class ImmutableLedger:
    """JSONL audit ledger that only appends and rejects secret-like fields."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: LedgerEntry) -> None:
        record = self._record_for(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")

    def read_entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    entries.append(json.loads(stripped))
        return entries

    def _record_for(self, entry: LedgerEntry) -> dict[str, Any]:
        _validate_required("run_id", entry.run_id)
        _validate_required("decision_id", entry.decision_id)
        _validate_required("event_type", entry.event_type)
        _validate_required("config_hash", entry.config_hash)
        if not isinstance(entry.payload, dict):
            raise LedgerValidationError("payload must be a dict")
        _reject_secret_like_fields(entry.payload)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": entry.run_id,
            "decision_id": entry.decision_id,
            "event_type": entry.event_type,
            "config_hash": entry.config_hash,
            "payload": entry.payload,
        }


def _validate_required(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LedgerValidationError(f"{name} is required")


def _reject_secret_like_fields(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS):
                raise LedgerValidationError(f"secret-like field is not allowed in ledger: {path}.{key}")
            _reject_secret_like_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_like_fields(child, path=f"{path}[{index}]")
