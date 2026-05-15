"""Local file-based kill switch for blocking new trades immediately."""

from __future__ import annotations

from pathlib import Path


class KillSwitch:
    """A simple file sentinel that blocks new trades when present."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def is_triggered(self) -> bool:
        return self.path.exists()

    def allows_new_trades(self) -> bool:
        return not self.is_triggered()

    def reason(self) -> str:
        if not self.is_triggered():
            return ""
        text = self.path.read_text(encoding="utf-8").strip()
        return text or "kill switch file present"

    def trigger(self, reason: str = "manual kill switch") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason, encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
