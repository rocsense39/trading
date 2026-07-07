from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .models import Instrument, Sleeve

class ConfigError(RuntimeError):
    pass

class BotConfig:
    def __init__(self, settings: dict[str, Any], instruments: dict[str, Instrument]):
        self.settings = settings
        self.instruments = instruments

    @classmethod
    def from_file(cls, path: Path) -> "BotConfig":
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        instruments = {}
        for key, item in raw["instruments"].items():
            instruments[key] = Instrument(
                key=key,
                xtb_symbol=item["xtb_symbol"],
                yf_symbol=item["yf_symbol"],
                sleeve=Sleeve(item["sleeve"]),
                target_weight=float(item["target_weight"]),
                qty=float(item.get("qty", 0.0)),
                avg_price=float(item.get("avg_price", 0.0)),
            )
        return cls(settings=raw["settings"], instruments=instruments)
