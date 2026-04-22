#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

eval "$(python3 load_live_env.py)"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

repair_venv() {
	echo "[setup] Repairing Python virtualenv at $VENV_DIR"
	rm -rf "$VENV_DIR"
	python3 -m venv "$VENV_DIR"
	"$VENV_PY" -m pip install --upgrade pip >/dev/null

	if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
		"$VENV_PY" -m pip install -r "$SCRIPT_DIR/requirements.txt"
	else
		"$VENV_PY" -m pip install requests py-clob-client eth-account
	fi
}

if [[ ! -x "$VENV_PY" ]]; then
	repair_venv
elif ! "$VENV_PY" -c "import sys" >/dev/null 2>&1; then
	repair_venv
fi

exec "$VENV_PY" "$SCRIPT_DIR/bot_v2.py" "$@"
