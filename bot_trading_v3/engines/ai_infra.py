from __future__ import annotations

from core.data import get_data, drop_incomplete_candle
from core.indicators import add_indicators
from core.utils import esc, fmt


def build_ai_infra_signal(name: str, meta: dict, config: dict, state: dict, regime: str, regime_details: str) -> str | None:
    if regime == "RISK OFF":
        return None

    df = get_data(meta.get("yf_symbol", ""))
    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 120:
        print(f"AI infra skipped {name}: insufficient data")
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

    label = esc(meta.get("label", name))
    xtb = esc(meta.get("xtb_symbol", name))
    yf = esc(meta.get("yf_symbol", name))

    bullish = close > ema20 > ema50
    breakout = bullish and close > hh20 and (vol_ma > 0 and vol > 1.25 * vol_ma)
    pullback = bullish and abs(close - ema20) <= 0.75 * atr
    invalid = close < ema50 or close < ll20

    if invalid:
        key = f"{name}:AI_INFRA_INVALID"
        if state.allow_alert(key, min_hours):
            return (
                f"🔴 <b>{esc(name)} — AI INFRA WATCH: SLĂBICIUNE</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Preț: {fmt(close)} | EMA50: {fmt(ema50)} | LL20: {fmt(ll20)}\n"
                f"Regime: <b>{esc(regime)}</b>"
            )

    if breakout:
        key = f"{name}:AI_INFRA_BREAKOUT"
        if state.allow_alert(key, min_hours):
            entry = close + 0.1 * atr
            stop = ema20 - 1.0 * atr
            return (
                f"🚀 <b>{esc(name)} — AI INFRA BREAKOUT</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Regime: <b>{esc(regime)}</b> ({esc(regime_details)})\n\n"
                f"Preț: <b>{fmt(close)}</b> | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Volum: {vol:.0f} vs medie {vol_ma:.0f}\n\n"
                f"Plan orientativ:\n"
                f"• Buy Stop: <b>{fmt(entry)}</b>\n"
                f"• Stop tehnic: <b>{fmt(stop)}</b>\n"
                f"• Nu depăși alocarea maximă stabilită manual."
            )

    if pullback:
        key = f"{name}:AI_INFRA_PULLBACK"
        if state.allow_alert(key, min_hours):
            entry = min(close, ema20 + 0.15 * atr)
            stop = ema50 - 0.8 * atr
            return (
                f"🟢 <b>{esc(name)} — AI INFRA PULLBACK</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Regime: <b>{esc(regime)}</b>\n\n"
                f"Preț: {fmt(close)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n"
                f"Plan orientativ:\n"
                f"• Buy Limit: <b>{fmt(entry)}</b>\n"
                f"• Stop tehnic: <b>{fmt(stop)}</b>"
            )

    # Plan periodic, util dar fără spam.
    if bullish and close > ema20 and float(prev["Close"]) <= float(prev["EMA20"]):
        key = f"{name}:AI_INFRA_TREND_RESUME"
        if state.allow_alert(key, min_hours):
            return (
                f"📌 <b>{esc(name)} — AI INFRA TREND RESUME</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Preț: <b>{fmt(close)}</b> | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Trendul revine peste EMA20. Verifică manual oportunitatea."
            )

    return None
