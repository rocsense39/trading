from __future__ import annotations
from dataclasses import dataclass
from core.models import Instrument, MarketSnapshot, Sleeve


@dataclass(frozen=True)
class TradePlan:
    key: str
    order_type: str
    entry: float
    stop_loss: float | None
    tp1: float | None
    tp1_sell_pct: float
    tp2: float | None
    tp2_sell_pct: float
    trailing_rule: str
    style: str
    reward_risk: float | None
    notes: list[str]


def _round_price(x: float) -> float:
    if x >= 100:
        return round(x, 2)
    if x >= 10:
        return round(x, 3)
    return round(x, 4)


def entry_plan(inst: Instrument, snap: MarketSnapshot) -> tuple[str, float, list[str]]:
    """Choose a semi-manual XTB entry order type and price.

    Rules are intentionally simple for Module 4:
    - If price is extended above EMA20, use a buy limit near EMA20.
    - If price is breaking above HH20, use a buy stop.
    - Otherwise use a buy limit around EMA20/EMA50 support.
    """
    notes: list[str] = []
    atr = max(snap.atr20, snap.close * 0.003)
    extended = snap.close > snap.ema20 + 1.25 * atr
    breakout = snap.close >= snap.hh20

    if extended:
        entry = max(snap.ema20 - 0.10 * atr, snap.ema50)
        notes.append("extended price; use pullback buy limit")
        return "BUY LIMIT", _round_price(entry), notes

    if breakout and inst.sleeve in {Sleeve.CORE, Sleeve.CORE_GROWTH, Sleeve.SATELLITE}:
        entry = snap.hh20 + 0.10 * atr
        notes.append("breakout setup; use buy stop")
        return "BUY STOP", _round_price(entry), notes

    if snap.close >= snap.ema20:
        entry = max(snap.ema20 - 0.15 * atr, snap.ema50)
        notes.append("constructive trend; buy limit near EMA20/EMA50")
        return "BUY LIMIT", _round_price(entry), notes

    entry = min(snap.ema50 + 0.10 * atr, snap.close + 0.25 * atr)
    notes.append("weaker candle; buy limit only if price stabilizes")
    return "BUY LIMIT", _round_price(entry), notes


def build_trade_plan(inst: Instrument, snap: MarketSnapshot) -> TradePlan:
    order_type, entry, notes = entry_plan(inst, snap)
    atr = max(snap.atr20, snap.close * 0.003)

    if inst.sleeve == Sleeve.QUALITY:
        stop = snap.ema150 - 1.0 * atr
        notes.append("quality sleeve: no fixed TP; rebalance only")
        return TradePlan(
            key=inst.key,
            order_type=order_type,
            entry=entry,
            stop_loss=_round_price(stop),
            tp1=None,
            tp1_sell_pct=0.0,
            tp2=None,
            tp2_sell_pct=0.0,
            trailing_rule="No fixed TP. Rebalance only if quality sleeve exceeds its target band.",
            style="quality",
            reward_risk=None,
            notes=notes,
        )

    if inst.sleeve in {Sleeve.CORE, Sleeve.CORE_GROWTH}:
        stop = min(entry - 2.0 * atr, snap.ema50 - 1.0 * atr)
        tp1 = max(entry * 1.08, snap.ema20 + 2.0 * atr)
        risk = max(entry - stop, 0.01)
        rr = (tp1 - entry) / risk
        notes.append("core sleeve: partial trim only; do not fully exit")
        return TradePlan(
            key=inst.key,
            order_type=order_type,
            entry=entry,
            stop_loss=_round_price(stop),
            tp1=_round_price(tp1),
            tp1_sell_pct=20.0 if inst.sleeve == Sleeve.CORE else 30.0,
            tp2=None,
            tp2_sell_pct=0.0,
            trailing_rule="After TP1, move stop toward breakeven and trail with EMA20 or 2 ATR.",
            style="core",
            reward_risk=round(rr, 2),
            notes=notes,
        )

    # Tactical satellite sleeve: stricter stop and two profit-taking levels.
    stop = entry - 1.8 * atr
    risk = max(entry - stop, 0.01)
    tp1 = max(entry * 1.08, entry + 1.5 * risk)
    tp2 = max(entry * 1.15, entry + 2.5 * risk)
    rr = (tp1 - entry) / risk
    notes.append("satellite sleeve: hard SL, TP1/TP2, trail the rest")
    return TradePlan(
        key=inst.key,
        order_type=order_type,
        entry=entry,
        stop_loss=_round_price(stop),
        tp1=_round_price(tp1),
        tp1_sell_pct=30.0,
        tp2=_round_price(tp2),
        tp2_sell_pct=30.0,
        trailing_rule="After TP2, trail remaining 40% with EMA20/ATR.",
        style="satellite",
        reward_risk=round(rr, 2),
        notes=notes,
    )
