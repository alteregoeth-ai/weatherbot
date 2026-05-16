import json
from pathlib import Path
import stat
import subprocess

from scripts.daily_report import build_daily_summary, format_daily_report


ROOT = Path(__file__).resolve().parents[1]


def test_daily_report_script_exists_is_executable_and_has_valid_python_syntax():
    script = ROOT / "scripts" / "daily_report.py"

    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR
    subprocess.run(["python", "-m", "py_compile", str(script)], check=True)


def test_build_daily_summary_counts_trades_rejections_errors_and_positions():
    entries = [
        {"event_type": "decision", "payload": {"risk_approved": True}},
        {"event_type": "decision", "payload": {"risk_approved": False}},
        {
            "event_type": "paper_fill",
            "payload": {"market_id": "m1", "outcome": "YES", "side": "buy", "shares": 2.0},
        },
        {
            "event_type": "paper_fill",
            "payload": {"market_id": "m2", "outcome": "YES", "side": "buy", "shares": 1.0},
        },
        {
            "event_type": "paper_fill",
            "payload": {"market_id": "m2", "outcome": "YES", "side": "sell", "shares": 1.0},
        },
        {"event_type": "paper_order_rejected", "payload": {"reason": "insufficient cash"}},
        {"event_type": "error", "payload": {"message": "provider timeout", "api_key": "secret"}},
        {"event_type": "daily_pnl", "payload": {"realized_pnl": 1.25}},
    ]

    summary = build_daily_summary(entries)

    assert summary.scanned_markets == 2
    assert summary.matched_markets == 2
    assert summary.approved_orders == 1
    assert summary.filled_orders == 3
    assert summary.rejected_markets == 1
    assert summary.order_rejections == 1
    assert summary.error_count == 1
    assert summary.realized_pnl == 1.25
    assert summary.open_positions == 1


def test_format_daily_report_is_secret_safe_and_contains_error_summary():
    summary = build_daily_summary(
        [
            {"event_type": "decision", "payload": {"risk_approved": False}},
            {"event_type": "error", "payload": {"message": "bad token", "token": "secret-token"}},
        ]
    )

    text = format_daily_report(summary)

    assert "Weatherbot Daily Report" in text
    assert "Scanned: 1" in text
    assert "Rejected: 1" in text
    assert "Errors: 1" in text
    assert "bad token" in text
    assert "secret-token" not in text
    assert "[REDACTED]" in text


def test_daily_report_cli_reads_jsonl_and_prints_summary(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"event_type": "decision", "payload": {"risk_approved": True}}),
                json.dumps({"event_type": "paper_fill", "payload": {"market_id": "m1", "outcome": "YES", "side": "buy", "shares": 2.0}}),
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["python", "scripts/daily_report.py", "--ledger", str(ledger), "--no-telegram"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Weatherbot Daily Report" in result.stdout
    assert "Scanned: 1" in result.stdout
    assert "Filled: 1" in result.stdout


def test_monitoring_docs_cover_cron_telegram_errors_and_secrets():
    content = (ROOT / "docs" / "monitoring.md").read_text(encoding="utf-8")

    assert "scripts/daily_report.py" in content
    assert "cron" in content.lower()
    assert "Telegram" in content
    assert "error" in content.lower()
    assert "Never paste" in content
    assert "TELEGRAM_BOT_TOKEN" in content
