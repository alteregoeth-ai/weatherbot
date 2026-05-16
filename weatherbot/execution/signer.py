"""Secret-safe credential holder for guarded Polymarket CLOB execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClobCredentials:
    """CLOB credentials whose repr excludes secret values."""

    wallet_address: str
    private_key: str = field(repr=False)
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    api_passphrase: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.wallet_address:
            raise ValueError("wallet_address is required")
        for name in ("private_key", "api_key", "api_secret", "api_passphrase"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")

    def safe_dict(self) -> dict[str, str]:
        """Return only non-secret metadata safe for logs/reports."""

        return {"wallet_address": self.wallet_address}
