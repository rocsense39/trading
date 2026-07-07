from __future__ import annotations
from dataclasses import dataclass
from .portfolio import HoldingView

@dataclass
class OrderPlan:
    order_type: str
    entry: float
    amount_eur: float
    qty: float
    sl: float
    tp1: float | None
    tp1_sell_pct: int
    tp2: float | None
    tp2_sell_pct: int
    trailing: str
    reward_risk: float | None


def entry_price(view: HoldingView) -> tuple[str, float]:
    s = view.snap
    sleeve = view.meta.get("sleeve", "satellite")
    extended = s.close > s.ema20 + 1.25 * s.atr
    breakout = s.close > s.hh20 and s.volume >= 1.05 * s.vol_ma
    if extended:
        return "BUY LIMIT", min(s.ema20, s.close - 0.65 * s.atr)
    if breakout and sleeve != "quality":
        return "BUY STOP", s.hh20 + 0.10 * s.atr
    if s.close >= s.ema20:
        return "BUY LIMIT", max(s.ema20 - 0.15 * s.atr, s.ema50)
    return "BUY LIMIT", s.ema50 + 0.10 * s.atr


def protection(view: HoldingView, entry: float) -> tuple[float, float | None, int, float | None, int, str, float | None]:
    s = view.snap
    sleeve = view.meta.get("sleeve", "satellite")
    if sleeve in {"core", "core_growth"}:
        sl = min(entry - 2.0 * s.atr, s.ema50 - 1.0 * s.atr)
        tp1 = max(entry * 1.08, s.ema20 + 2.0 * s.atr)
        rr = (tp1 - entry) / (entry - sl) if entry > sl else 0.0
        return sl, tp1, 20, None, 0, "After TP1, trail with EMA20 or 2 ATR; never fully exit core.", rr
    if sleeve == "quality":
        sl = s.ema150 - 1.0 * s.atr
        return sl, None, 0, None, 0, "No TP. Rebalance only if QUALITY exceeds 15%.", None
    sl = entry - 1.8 * s.atr
    risk = max(entry - sl, 0.01)
    tp1 = max(entry * 1.08, entry + 1.5 * risk)
    tp2 = max(entry * 1.15, entry + 2.5 * risk)
    rr = (tp1 - entry) / risk
    return sl, tp1, 30, tp2, 30, "After TP2, trail remaining 40% with EMA20/ATR.", rr


def make_order_plan(view: HoldingView, amount_eur: float) -> OrderPlan:
    order_type, entry = entry_price(view)
    sl, tp1, tp1pct, tp2, tp2pct, trailing, rr = protection(view, entry)
    qty = amount_eur / entry if entry > 0 else 0.0
    return OrderPlan(order_type, entry, amount_eur, qty, sl, tp1, tp1pct, tp2, tp2pct, trailing, rr)
