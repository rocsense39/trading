from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any


def load_state(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"alerts": {}, "daily_entry": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"alerts": {}, "daily_entry": {}}


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(state, indent=2), encoding="utf-8")


def today(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).date().isoformat()


def daily_entry_allowed(cfg: dict[str, Any], state: dict[str, Any]) -> bool:
    if not cfg["settings"].get("one_new_entry_per_day", True):
        return True
    return state.get("daily_entry", {}).get("date") != today(cfg["settings"].get("timezone", "Europe/Berlin"))


def mark_daily_entry(cfg: dict[str, Any], state: dict[str, Any], symbol: str) -> None:
    state["daily_entry"] = {"date": today(cfg["settings"].get("timezone", "Europe/Berlin")), "symbol": symbol}
