from pathlib import Path
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_local_runner_scripts_exist_are_executable_and_shellcheck_syntax():
    for script in (ROOT / "scripts" / "run_paper.sh", ROOT / "scripts" / "run_live_stage_a.sh"):
        assert script.exists()
        assert script.stat().st_mode & stat.S_IXUSR
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_paper_runner_defaults_to_safe_paper_config_and_loop_controls():
    content = read("scripts/run_paper.sh")

    assert "config/default.paper.json" in content
    assert "WEATHERBOT_MODE=paper" in content
    assert "WEATHERBOT_ENABLE_LIVE=false" in content
    assert "WEATHERBOT_LOOP_SECONDS" in content
    assert "WEATHERBOT_ONCE" in content
    assert "WEATHERBOT_COMMAND" in content
    assert "nice -n 10" in content
    assert "ionice -c2 -n7" in content
    assert "flock" in content
    assert "OPENBLAS_NUM_THREADS=1" in content
    assert "weatherbot.scan_runner" not in content


def test_live_stage_a_runner_requires_explicit_ack_and_never_embeds_secrets():
    content = read("scripts/run_live_stage_a.sh")

    assert "WEATHERBOT_CONFIRM_LIVE_STAGE_A=YES" in content
    assert "WEATHERBOT_MODE=live" in content
    assert "WEATHERBOT_STAGE=stage_a" in content
    assert "WEATHERBOT_ENABLE_LIVE=true" in content
    for forbidden in ("PRIVATE_KEY=", "API_SECRET=", "TELEGRAM_BOT_TOKEN="):
        assert forbidden not in content


def test_local_laptop_runbook_documents_wsl_awake_and_safe_startup():
    content = read("docs/local-laptop-runbook.md")

    assert "WSL" in content
    assert "sleep" in content.lower()
    assert "scripts/run_paper.sh" in content
    assert "scripts/run_live_stage_a.sh" in content
    assert "WEATHERBOT_CONFIRM_LIVE_STAGE_A=YES" in content
    assert ".env" in content
    assert "Never paste" in content
