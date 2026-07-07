from core.models import Instrument, MarketSnapshot, TradePlan


def build_trade_plan(inst: Instrument, snap: MarketSnapshot, order_eur: float) -> TradePlan:
    entry = snap.close
    qty = order_eur / entry if entry > 0 else 0.0
    sleeve = inst.sleeve
    if sleeve in {"core", "core_growth"}:
        sl = snap.ema50 - snap.atr20
        tp1 = max(entry * 1.08, snap.ema20 + 2 * snap.atr20)
        risk = max(entry - sl, 0.01)
        rr = (tp1 - entry) / risk
        return TradePlan(inst.key, "BUY", order_eur, qty, entry, sl, tp1, 20, None, 0, "After TP1 move SL to breakeven; trail with EMA20/ATR20; do not fully exit core.", rr)
    if sleeve == "quality":
        sl = snap.ema150 - snap.atr20
        return TradePlan(inst.key, "BUY", order_eur, qty, entry, sl, None, 0, None, 0, "No TP; rebalance only if quality exceeds target band.", None)
    sl = entry - 1.8 * snap.atr20
    risk = max(entry - sl, 0.01)
    tp1 = max(entry * 1.08, entry + 1.5 * risk)
    tp2 = max(entry * 1.15, entry + 2.5 * risk)
    return TradePlan(inst.key, "BUY", order_eur, qty, entry, sl, tp1, 30, tp2, 30, "After TP2 trail remaining 40% with EMA20/ATR20.", (tp1 - entry) / risk)
