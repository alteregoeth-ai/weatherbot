#!/usr/bin/env python3
"""CLI entrypoint documented in README; implementation is bot_v2.py."""
import subprocess
import sys
from pathlib import Path


def main() -> int:
    bot = Path(__file__).resolve().parent / "bot_v2.py"
    return subprocess.call([sys.executable, str(bot), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
