from __future__ import annotations

import html
import math
from typing import Any, Iterable


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def fmt(value: Any) -> str:
    try:
        x = float(value)
    except Exception:
        return "n/a"
    if math.isnan(x):
        return "n/a"
    if abs(x) >= 10:
        return f"{x:.2f}"
    return f"{x:.4f}"


def enabled_items(items: dict) -> Iterable[tuple[str, dict]]:
    for name, meta in items.items():
        if meta.get("enabled", True):
            yield name, meta


def get_fx(config: dict, currency: str) -> float:
    currency = str(currency).upper()
    settings = config.get("settings", {})
    if currency == "RON":
        return 1.0
    if currency == "EUR":
        return float(settings.get("eur_ron", 5.0))
    if currency == "USD":
        return float(settings.get("usd_ron", 4.65))
    return 1.0


def ron_to_qty(config: dict, amount_ron: float, price: float, currency: str) -> float:
    fx = get_fx(config, currency)
    if price <= 0 or amount_ron <= 0 or fx <= 0:
        return 0.0
    return amount_ron / (price * fx)


def fib_zones(low: float, high: float) -> dict[str, float]:
    move = max(high - low, 0.0)
    return {
        "23.6%": high - 0.236 * move,
        "38.2%": high - 0.382 * move,
        "50.0%": high - 0.500 * move,
    }


def portfolio_value_ron(config: dict, latest: dict[str, tuple[float, str]] | None = None) -> float:
    latest = latest or {}
    total = float(config.get("settings", {}).get("cash_available_ron", 0))
    for sym, pos in config.get("portfolio", {}).get("positions", {}).items():
        qty = float(pos.get("qty", 0) or 0)
        avg = float(pos.get("avg_price", 0) or 0)
        currency = pos.get("currency", "EUR")
        price = latest.get(sym, (avg, currency))[0]
        total += qty * price * get_fx(config, currency)
    return total
