from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo


STATE_PATH = Path("state.json")
TZ = ZoneInfo("Europe/Berlin")


class BotState(dict):
    def save(self) -> None:
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(self, f, indent=2, ensure_ascii=False)

    def allow_alert(self, key: str, min_hours: int) -> bool:
        now = datetime.now(TZ)
        alerts = self.setdefault("alerts", {})
        last = alerts.get(key)

        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                elapsed = (now - last_dt).total_seconds() / 3600
                if elapsed < min_hours:
                    return False
            except Exception:
                pass

        alerts[key] = now.isoformat()
        self.save()
        return True


def load_state() -> BotState:
    if not STATE_PATH.exists():
        return BotState({"alerts": {}})

    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("alerts", {})
        return BotState(data)
    except Exception:
        return BotState({"alerts": {}})
