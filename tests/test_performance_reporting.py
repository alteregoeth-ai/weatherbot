import json
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def write_ledger(path: Path) -> None:
    entries = [
        {
            "timestamp": "2026-05-17T00:00:00+00:00",
            "event_type": "decision",
            "payload": {"risk_approved": True, "edge": 0.20, "dollars": 1.0, "city": "NYC"},
        },
        {
            "timestamp": "2026-05-17T23:59:59+00:00",
            "event_type": "paper_fill",
            "payload": {"market_id": "m1", "outcome": "YES", "side": "buy", "shares": 2.0, "dollars": 1.0},
        },
        {
            "timestamp": "2026-05-18T00:00:00+00:00",
            "event_type": "decision",
            "payload": {"risk_approved": False, "edge": 0.05, "dollars": 0.0, "city": "Miami"},
        },
        {
            "timestamp": "2026-05-17T12:00:00+00:00",
            "event_type": "daily_pnl",
            "payload": {"realized_pnl": 0.25},
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")


def test_performance_report_script_exists_is_executable_and_compiles():
    script = ROOT / "scripts" / "performance_report.py"
    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR
    subprocess.run(["python", "-m", "py_compile", str(script)], check=True)


def test_daily_report_uses_previous_utc_day_window_and_standard_template(tmp_path):
    ledger = tmp_path / "paper.jsonl"
    output_dir = tmp_path / "reports"
    write_ledger(ledger)

    result = subprocess.run(
        [
            "python",
            "scripts/performance_report.py",
            "--period",
            "daily",
            "--as-of",
            "2026-05-18T00:05:00+00:00",
            "--ledger",
            str(ledger),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    report_path = output_dir / "daily" / "2026-05-17.md"
    assert str(report_path) in result.stdout
    content = report_path.read_text(encoding="utf-8")
    assert "# Weatherbot Daily Performance Report — 2026-05-17" in content
    assert "Period: 2026-05-17 00:00 UTC to 2026-05-17 23:59 UTC" in content
    assert "Decisions: 1" in content
    assert "Approved: 1" in content
    assert "Fills: 1" in content
    assert "Realized PnL: $0.25" in content
    assert "Open positions: 1" in content
    assert "Miami" not in content


def test_weekly_and_monthly_templates_write_to_predictable_paths(tmp_path):
    ledger = tmp_path / "paper.jsonl"
    output_dir = tmp_path / "reports"
    write_ledger(ledger)

    weekly = subprocess.run(
        ["python", "scripts/performance_report.py", "--period", "weekly", "--as-of", "2026-05-18T00:05:00+00:00", "--ledger", str(ledger), "--output-dir", str(output_dir)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    monthly = subprocess.run(
        ["python", "scripts/performance_report.py", "--period", "monthly", "--as-of", "2026-06-01T00:05:00+00:00", "--ledger", str(ledger), "--output-dir", str(output_dir)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "reports/weekly/2026-W20.md" in weekly.stdout.replace(str(output_dir), "reports")
    assert "reports/monthly/2026-05.md" in monthly.stdout.replace(str(output_dir), "reports")
    assert "# Weatherbot Weekly Performance Report" in (output_dir / "weekly" / "2026-W20.md").read_text(encoding="utf-8")
    assert "# Weatherbot Monthly Performance Report" in (output_dir / "monthly" / "2026-05.md").read_text(encoding="utf-8")


def test_low_resource_daily_push_script_has_guards_and_expected_schedule_command():
    script = ROOT / "scripts" / "daily_report_push.sh"
    content = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(script)], check=True)
    assert "flock" in content
    assert "nice -n 10" in content
    assert "ionice -c2 -n7" in content
    assert "OPENBLAS_NUM_THREADS=1" in content
    assert "performance_report.py --period daily" in content
    assert "git push fork" in content
    assert "5 0 * * *" in content


def test_reporting_docs_define_daily_weekly_monthly_templates_and_utc_push_policy():
    content = (ROOT / "docs" / "performance-reporting.md").read_text(encoding="utf-8")

    assert "00:05 UTC" in content
    assert "00:00 UTC to 23:59 UTC" in content
    assert "Daily" in content
    assert "Weekly" in content
    assert "Monthly" in content
    assert "low resource" in content.lower()
    assert "git push fork" in content
