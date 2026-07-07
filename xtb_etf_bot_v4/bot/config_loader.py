from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_SETTINGS = [
    "equity_eur", "free_cash_eur", "cash_reserve_pct", "reserve_basis",
    "min_order_eur", "max_order_eur", "one_new_entry_per_day"
]


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED_SETTINGS if k not in cfg.get("settings", {})]
    if missing:
        raise ValueError(f"Missing settings: {missing}")
    if not cfg.get("etfs"):
        raise ValueError("No ETFs configured")
    if cfg["settings"]["reserve_basis"] not in {"portfolio_value", "equity", "free_cash"}:
        raise ValueError("reserve_basis must be portfolio_value, equity, or free_cash")
    total_weight = sum(float(e.get("target_weight", 0.0)) for e in cfg["etfs"].values() if e.get("enabled", True))
    if abs(total_weight - 1.0) > 0.01:
        raise ValueError(f"ETF target weights must sum to 1.0; got {total_weight:.3f}")
