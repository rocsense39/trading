from __future__ import annotations

from core.data import get_data, drop_incomplete_candle
from core.indicators import add_indicators
from core.utils import esc, fmt, portfolio_value_ron, ron_to_qty


def build_swing_signal(name: str, meta: dict, config: dict, state: dict, regime: str) -> str | None:
    if regime == "RISK OFF":
        return None

    df = get_data(meta.get("yf_symbol", ""))
    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 180:
        print(f"Swing skipped {name}: insufficient data")
        return None

    df = add_indicators(df)
    if df.empty:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    min_hours = int(config["settings"].get("min_alert_interval_hours", 4))

    close = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    atr = float(last["ATR"])
    vol = float(last["Volume"])
    vol_ma = float(last["VOL_MA"])
    hh20 = float(last["HH20"])
    ll20 = float(last["LL20"])

    pos = config.get("portfolio", {}).get("positions", {}).get(name, {})
    avg = float(pos.get("avg_price", 0) or 0)
    qty_pos = float(pos.get("qty", 0) or 0)

    currency = meta.get("currency", "USD")
    max_alloc_pct = float(meta.get("max_allocation_pct", 5))
    portfolio_value = portfolio_value_ron(config, {name: (close, currency)})
    max_trade_ron = portfolio_value * max_alloc_pct / 100

    label = esc(meta.get("label", name))
    xtb = esc(meta.get("xtb_symbol", name))

    trend_bull = close > ema20 > ema50
    volume_ok = vol_ma > 0 and vol > 1.2 * vol_ma
    breakout = trend_bull and close > hh20 and (volume_ok or atr > float(prev["ATR"]))
    pullback = trend_bull and abs(close - ema20) <= 0.8 * atr
    invalidation = close < ema50 or close < ll20

    if qty_pos > 0 and avg > 0:
        pnl_pct = (close / avg - 1) * 100
        if pnl_pct >= 8:
            key = f"{name}:SWING_TRAIL"
            if state.allow_alert(key, min_hours):
                trail = max(avg, ema20 - 0.5 * atr)
                return (
                    f"🔵 <b>{esc(name)} — TRAILING STOP</b>\n"
                    f"{label}\n"
                    f"Poziția este aprox. +{pnl_pct:.1f}% față de avg {fmt(avg)}.\n"
                    f"Stop orientativ: <b>{fmt(trail)}</b>"
                )

    if invalidation:
        key = f"{name}:SWING_INVALIDATION"
        if state.allow_alert(key, min_hours):
            return (
                f"🔴 <b>{esc(name)} — SWING INVALIDATION</b>\n"
                f"{label}\n"
                f"Preț: {fmt(close)} | EMA50: {fmt(ema50)} | LL20: {fmt(ll20)}\n"
                f"Evită add. Verifică Sell Stop."
            )

    if breakout:
        key = f"{name}:SWING_BREAKOUT"
        if state.allow_alert(key, min_hours):
            entry = close + 0.10 * atr
            sl = float(meta.get("manual_stop") or max(ema20 - 1.2 * atr, close - 2.0 * atr))
            risk = max(entry - sl, 0.01)
            tp1 = float(meta.get("manual_tp1") or entry + 1.5 * risk)
            tp2 = float(meta.get("manual_tp2") or entry + 2.5 * risk)
            qty = ron_to_qty(config, max_trade_ron, entry, currency)

            return (
                f"🚀 <b>{esc(name)} — SWING BREAKOUT</b>\n"
                f"{label} | XTB: <b>{xtb}</b>\n"
                f"Regime: <b>{esc(regime)}</b>\n"
                f"Preț: {fmt(close)} | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n\n"
                f"Ordin orientativ:\n"
                f"• Buy Stop: <b>{fmt(entry)}</b>\n"
                f"• Sell Stop: <b>{fmt(sl)}</b>\n"
                f"• TP1: <b>{fmt(tp1)}</b>\n"
                f"• TP2: <b>{fmt(tp2)}</b>\n"
                f"• Max alocare: {max_alloc_pct:.1f}% ≈ {max_trade_ron:.0f} RON\n"
                f"• Qty estimată: {qty:.4f}"
            )

    if pullback:
        key = f"{name}:SWING_PULLBACK"
        if state.allow_alert(key, min_hours):
            entry = min(close, ema20 + 0.20 * atr)
            sl = float(meta.get("manual_stop") or (ema50 - 1.0 * atr))
            risk = max(entry - sl, 0.01)
            tp1 = float(meta.get("manual_tp1") or entry + 1.5 * risk)
            tp2 = float(meta.get("manual_tp2") or entry + 2.5 * risk)
            qty = ron_to_qty(config, max_trade_ron, entry, currency)

            return (
                f"🟢 <b>{esc(name)} — SWING PULLBACK</b>\n"
                f"{label} | XTB: <b>{xtb}</b>\n"
                f"Regime: <b>{esc(regime)}</b>\n"
                f"Preț: {fmt(close)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n\n"
                f"Ordin orientativ:\n"
                f"• Buy Limit: <b>{fmt(entry)}</b>\n"
                f"• Sell Stop: <b>{fmt(sl)}</b>\n"
                f"• TP1: <b>{fmt(tp1)}</b>\n"
                f"• TP2: <b>{fmt(tp2)}</b>\n"
                f"• Max alocare: {max_alloc_pct:.1f}% ≈ {max_trade_ron:.0f} RON\n"
                f"• Qty estimată: {qty:.4f}"
            )

    return None
