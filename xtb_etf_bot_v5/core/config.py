import json
from pathlib import Path
from .models import Instrument

class ConfigError(Exception):
    pass

class BotConfig:
    def __init__(self, settings: dict, instruments: list[Instrument]):
        self.settings = settings
        self.instruments = instruments

    @classmethod
    def from_file(cls, path: str | Path = "config/portfolio.json"):
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        instruments = [Instrument(**item) for item in data["instruments"]]
        return cls(data["settings"], instruments)
