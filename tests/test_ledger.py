import json

import pytest

from weatherbot.ledger import ImmutableLedger, LedgerEntry, LedgerValidationError


def test_appends_jsonl_entries_with_required_audit_fields(tmp_path):
    ledger_path = tmp_path / "trades.jsonl"
    ledger = ImmutableLedger(ledger_path)

    entry = LedgerEntry(
        run_id="run-1",
        decision_id="decision-1",
        event_type="decision",
        config_hash="abc123",
        payload={"market_slug": "weather-nyc", "edge": 0.17},
    )
    ledger.append(entry)

    line = ledger_path.read_text().strip()
    data = json.loads(line)
    assert data["timestamp"]
    assert data["run_id"] == "run-1"
    assert data["decision_id"] == "decision-1"
    assert data["event_type"] == "decision"
    assert data["config_hash"] == "abc123"
    assert data["payload"] == {"market_slug": "weather-nyc", "edge": 0.17}


def test_append_only_log_keeps_existing_entries(tmp_path):
    ledger_path = tmp_path / "trades.jsonl"
    ledger = ImmutableLedger(ledger_path)

    ledger.append(LedgerEntry("run-1", "decision-1", "decision", "hash-1", {"n": 1}))
    ledger.append(LedgerEntry("run-1", "decision-2", "paper_fill", "hash-1", {"n": 2}))

    lines = ledger_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["decision_id"] == "decision-1"
    assert json.loads(lines[1])["decision_id"] == "decision-2"


def test_read_entries_returns_written_entries_in_order(tmp_path):
    ledger = ImmutableLedger(tmp_path / "trades.jsonl")
    ledger.append(LedgerEntry("run-1", "decision-1", "decision", "hash-1", {"n": 1}))
    ledger.append(LedgerEntry("run-1", "decision-2", "paper_fill", "hash-1", {"n": 2}))

    entries = ledger.read_entries()

    assert [entry["decision_id"] for entry in entries] == ["decision-1", "decision-2"]


def test_rejects_secret_like_fields_anywhere_in_payload(tmp_path):
    ledger = ImmutableLedger(tmp_path / "trades.jsonl")

    with pytest.raises(LedgerValidationError, match="secret"):
        ledger.append(
            LedgerEntry(
                "run-1",
                "decision-1",
                "decision",
                "hash-1",
                {"wallet": {"private_key": "0xabc"}},
            )
        )

    assert not (tmp_path / "trades.jsonl").exists()


def test_rejects_empty_required_fields(tmp_path):
    ledger = ImmutableLedger(tmp_path / "trades.jsonl")

    with pytest.raises(LedgerValidationError, match="run_id"):
        ledger.append(LedgerEntry("", "decision-1", "decision", "hash-1", {}))
