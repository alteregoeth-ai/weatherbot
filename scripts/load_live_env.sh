#!/usr/bin/env bash
# Load live trading secrets from macOS Keychain into the current shell.
#
# IMPORTANT: Do not use `set -e` here. If `security find-generic-password` fails
# (missing item, wrong account, user denies Keychain), we must not exit the
# interactive shell — Cursor/zsh would show "terminal process terminated (exit 1)".

set -uo pipefail

SERVICE="weatherbot-live"
ACCOUNT="${USER:-weatherbot}"

load_secret() {
  local key="$1"
  # Always succeed from the shell's perspective; empty string means lookup failed.
  security find-generic-password \
    -a "$ACCOUNT" \
    -s "${SERVICE}:${key}" \
    -w 2>/dev/null || true
}

export PRIVATE_KEY="$(load_secret PRIVATE_KEY)"
export CHAIN_ID="$(load_secret CHAIN_ID)"
export SIGNATURE_TYPE="$(load_secret SIGNATURE_TYPE)"
export PROXY_KEY="$(load_secret PROXY_KEY)"
export POLY_API_KEY="$(load_secret POLY_API_KEY)"
export POLY_SECRET="$(load_secret POLY_SECRET)"
export POLY_PASSPHRASE="$(load_secret POLY_PASSPHRASE)"

echo "Weatherbot live env vars loaded into current shell."

empty=()
[[ -z "$PRIVATE_KEY" ]] && empty+=("PRIVATE_KEY")
[[ -z "$CHAIN_ID" ]] && empty+=("CHAIN_ID")
[[ -z "$SIGNATURE_TYPE" ]] && empty+=("SIGNATURE_TYPE")
[[ -z "$PROXY_KEY" ]] && empty+=("PROXY_KEY")
[[ -z "$POLY_API_KEY" ]] && empty+=("POLY_API_KEY")
[[ -z "$POLY_SECRET" ]] && empty+=("POLY_SECRET")
[[ -z "$POLY_PASSPHRASE" ]] && empty+=("POLY_PASSPHRASE")

if ((${#empty[@]})); then
  echo "  [load_live_env] Empty values (Keychain miss, wrong account, or access denied): ${empty[*]}" >&2
  echo "  [load_live_env] Expected items: service '${SERVICE}', account '${ACCOUNT}' (your macOS username)." >&2
  echo "  [load_live_env] Re-run ./scripts/setup_live_secrets.sh or unlock Keychain, then source again." >&2
fi
