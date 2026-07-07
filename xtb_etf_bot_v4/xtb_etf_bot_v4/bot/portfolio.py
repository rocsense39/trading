from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from .market import Snapshot, snapshot

@dataclass
class HoldingView:
    name: str
    meta: dict[str, Any]
    snap: Snapshot
    value_eur: float
    target_weight: float
    actual_weight: float
    target_value_eur: float
    gap_eur: float
    gap_pct: float


def position_value_eur(cfg: dict[str, Any], name: str, price: float) -> float:
    pos = cfg.get("portfolio", {}).get("positions", {}).get(name, {})
    return float(pos.get("qty", 0.0)) * price


def build_portfolio(cfg: dict[str, Any]) -> tuple[dict[str, HoldingView], float]:
    tz = cfg["settings"].get("timezone", "Europe/Berlin")
    free_cash = float(cfg["settings"]["free_cash_eur"])
    views: dict[str, HoldingView] = {}
    invested_value = 0.0
    tmp: list[tuple[str, dict[str, Any], Snapshot, float]] = []

    for name, meta in cfg["etfs"].items():
        if not meta.get("enabled", True):
            continue
        snap = snapshot(meta["yf_symbol"], tz_name=tz)
        if snap is None:
            print(f"{name}: skipped — no usable market data")
            continue
        value = position_value_eur(cfg, name, snap.close)
        invested_value += value
        tmp.append((name, meta, snap, value))

    portfolio_value = invested_value + free_cash
    if portfolio_value <= 0:
        portfolio_value = float(cfg["settings"]["equity_eur"])

    for name, meta, snap, value in tmp:
        target = float(meta["target_weight"])
        actual = value / portfolio_value if portfolio_value else 0.0
        target_value = target * portfolio_value
        views[name] = HoldingView(
            name=name, meta=meta, snap=snap, value_eur=value,
            target_weight=target, actual_weight=actual,
            target_value_eur=target_value, gap_eur=target_value - value,
            gap_pct=target - actual
        )
    return views, portfolio_value


def reserve_eur(cfg: dict[str, Any], portfolio_value: float) -> float:
    settings = cfg["settings"]
    pct = float(settings["cash_reserve_pct"])
    basis = settings["reserve_basis"]
    if basis == "equity":
        base = float(settings["equity_eur"])
    elif basis == "free_cash":
        base = float(settings["free_cash_eur"])
    else:
        base = float(portfolio_value)
    return pct * base


def deployable_cash_eur(cfg: dict[str, Any], portfolio_value: float) -> float:
    free_cash = float(cfg["settings"]["free_cash_eur"])
    return max(0.0, free_cash - reserve_eur(cfg, portfolio_value))
