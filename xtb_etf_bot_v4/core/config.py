from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Account, Instrument, Position, Sleeve


class ConfigError(ValueError):
    pass


class BotConfig:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.account = self._parse_account(raw.get("account", {}))
        self.targets = self._parse_targets(raw.get("targets", {}))
        self.instruments = self._parse_instruments(raw.get("instruments", {}))
        self.positions = self._parse_positions(raw.get("positions", {}))
        self._validate()

    @staticmethod
    def from_file(path: str | Path) -> "BotConfig":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        return BotConfig(json.loads(p.read_text(encoding="utf-8")))

    @staticmethod
    def _parse_account(d: dict[str, Any]) -> Account:
        return Account(
            base_currency=str(d.get("base_currency", "EUR")),
            equity_eur=float(d["equity_eur"]),
            free_cash_eur=float(d["free_cash_eur"]),
            cash_reserve_pct_of_equity=float(d.get("cash_reserve_pct_of_equity", 0.05)),
            min_order_eur=float(d.get("min_order_eur", 10.0)),
            max_order_eur=float(d.get("max_order_eur", 50.0)),
            one_new_entry_per_day=bool(d.get("one_new_entry_per_day", True)),
        )

    @staticmethod
    def _parse_targets(d: dict[str, Any]) -> dict[str, float]:
        return {k: float(v) for k, v in d.items()}

    @staticmethod
    def _parse_instruments(d: dict[str, Any]) -> dict[str, Instrument]:
        return {
            key: Instrument(
                key=key,
                xtb_symbol=str(v["xtb_symbol"]),
                yf_symbol=str(v["yf_symbol"]),
                sleeve=Sleeve(str(v["sleeve"])),
                currency=str(v.get("currency", "EUR")),
            )
            for key, v in d.items()
        }

    @staticmethod
    def _parse_positions(d: dict[str, Any]) -> dict[str, Position]:
        return {key: Position(key=key, qty=float(v.get("qty", 0.0)), avg_price=float(v.get("avg_price", 0.0))) for key, v in d.items()}

    def _validate(self) -> None:
        total = sum(self.targets.values())
        if abs(total - 1.0) > 0.0001:
            raise ConfigError(f"Target weights must sum to 1.0, got {total:.6f}")
        missing_instruments = set(self.targets) - set(self.instruments)
        if missing_instruments:
            raise ConfigError(f"Missing instruments for targets: {sorted(missing_instruments)}")
        if self.account.free_cash_eur < 0 or self.account.equity_eur <= 0:
            raise ConfigError("Invalid account equity/free cash")
