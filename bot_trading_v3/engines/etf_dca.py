from __future__ import annotations

from core.data import get_data, drop_incomplete_candle
from core.indicators import add_indicators
from core.utils import esc, fib_zones, fmt, ron_to_qty


def build_etf_signal(name: str, meta: dict, config: dict, state: dict, regime: str, regime_details: str) -> str | None:
    df = get_data(meta.get("yf_symbol", ""))
    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 180:
        print(f"ETF skipped {name}: insufficient data")
        return None

    df = add_indicators(df)
    if df.empty:
        return None

    last = df.iloc[-1]
    min_hours = int(config["settings"].get("min_alert_interval_hours", 4))

    close = float(last["Close"])
    high = float(last["High"])
    low = float(last["Low"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema150 = float(last["EMA150"])
    atr = float(last["ATR"])
    high80 = float(last["SWING_HIGH_80"])
    low80 = float(last["SWING_LOW_80"])

    monthly = float(config["settings"].get("monthly_budget_ron", 500))
    cash = float(config["settings"].get("cash_available_ron", monthly))
    weight = float(meta.get("target_weight", 0))
    allocation = min(cash, monthly * weight)

    if regime == "RISK OFF":
        allocation *= 0.50
    elif regime == "NEUTRAL":
        allocation *= 0.75

    currency = meta.get("currency", "EUR")
    label = esc(meta.get("label", name))
    xtb = esc(meta.get("xtb_symbol", name))
    yf = esc(meta.get("yf_symbol", name))

    trend_ok = close > ema50 > ema150
    strong_trend = close > ema20 > ema50 > ema150
    extended = close > ema20 + 1.2 * atr
    near_ema20 = abs(close - ema20) <= 0.65 * atr
    near_ema50 = abs(close - ema50) <= 0.85 * atr
    zones = fib_zones(low80, high80)

    primary = max([x for x in [ema20, zones["23.6%"]] if x < max(close, high)] or [min(ema20, close * 0.995)])
    secondary = max([x for x in [ema50, zones["38.2%"]] if x < primary] or [min(ema50, zones["38.2%"])])

    if close < ema50 and ema20 < ema50:
        key = f"{name}:ETF_RISK"
        if state.allow_alert(key, min_hours):
            return (
                f"🔴 <b>{esc(name)} — DCA PRUDENȚĂ</b>\n"
                f"{label}\n"
                f"Preț: <b>{fmt(close)}</b> | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Regime: <b>{esc(regime)}</b>\n"
                f"Sugestie: doar tranșe mici sau așteaptă stabilizare."
            )

    if allocation <= 0:
        return None

    if trend_ok and low <= primary <= high:
        key = f"{name}:ETF_HIT_PRIMARY:{round(primary, 2)}"
        if state.allow_alert(key, min_hours):
            qty = ron_to_qty(config, allocation * 0.60, primary, currency)
            return (
                f"🔔 <b>{esc(name)} — BUY LIMIT HIT</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b>\n"
                f"Buy Limit principal: <b>{fmt(primary)}</b>\n"
                f"Buget: <b>{allocation * 0.60:.0f} RON</b> | Qty est.: <b>{qty:.4f}</b>\n"
                f"Regime: <b>{esc(regime)}</b>"
            )

    if trend_ok and low <= secondary <= high:
        key = f"{name}:ETF_HIT_SECONDARY:{round(secondary, 2)}"
        if state.allow_alert(key, min_hours):
            qty = ron_to_qty(config, allocation * 0.40, secondary, currency)
            return (
                f"🔔🟢 <b>{esc(name)} — BUY LIMIT DEEP HIT</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b>\n"
                f"Buy Limit secundar: <b>{fmt(secondary)}</b>\n"
                f"Buget: <b>{allocation * 0.40:.0f} RON</b> | Qty est.: <b>{qty:.4f}</b>\n"
                f"Regime: <b>{esc(regime)}</b>"
            )

    if trend_ok and near_ema20 and close >= ema20:
        key = f"{name}:ETF_EMA20_ENTRY"
        if state.allow_alert(key, min_hours):
            buy_limit = min(close, ema20 + 0.15 * atr)
            qty = ron_to_qty(config, allocation, buy_limit, currency)
            invalid = ema50 - 0.8 * atr
            return (
                f"🟢 <b>{esc(name)} — DCA ENTRY</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Regime: <b>{esc(regime)}</b>\n\n"
                f"Reason: pullback la EMA20 în trend ascendent\n"
                f"Preț: {fmt(close)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n\n"
                f"Ordin sugerat:\n"
                f"• Buy Limit: <b>{fmt(buy_limit)}</b>\n"
                f"• Buget: <b>{allocation:.0f} RON</b>\n"
                f"• Cantitate estimată: <b>{qty:.4f}</b>\n"
                f"• Invalidation tehnică: sub {fmt(invalid)}"
            )

    if close > ema150 and near_ema50:
        key = f"{name}:ETF_EMA50_ENTRY"
        if state.allow_alert(key, min_hours):
            buy_limit = min(close, ema50 + 0.2 * atr)
            qty = ron_to_qty(config, allocation, buy_limit, currency)
            return (
                f"🟢🟢 <b>{esc(name)} — DCA STRONGER DIP</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Regime: <b>{esc(regime)}</b>\n"
                f"Buy Limit: <b>{fmt(buy_limit)}</b> | Buget: <b>{allocation:.0f} RON</b> | Qty: <b>{qty:.4f}</b>"
            )

    if strong_trend and extended:
        key = f"{name}:ETF_EXTENDED_WAIT"
        if state.allow_alert(key, min_hours):
            return (
                f"🟡 <b>{esc(name)} — DCA WAIT / SET LIMITS</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Regime: <b>{esc(regime)}</b> ({esc(regime_details)})\n\n"
                f"Preț: <b>{fmt(close)}</b> | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Trend bullish, dar preț extins. Nu chase.\n\n"
                f"Buy Limit zones:\n"
                f"• 23.6%: <b>{fmt(zones['23.6%'])}</b>\n"
                f"• 38.2%: <b>{fmt(zones['38.2%'])}</b>\n"
                f"• 50.0%: <b>{fmt(zones['50.0%'])}</b>\n"
                f"Alocare: <b>{allocation:.0f} RON</b>"
            )

    if trend_ok and close > ema20:
        key = f"{name}:ETF_PLAN"
        if state.allow_alert(key, min_hours):
            qty1 = ron_to_qty(config, allocation * 0.60, primary, currency)
            qty2 = ron_to_qty(config, allocation * 0.40, secondary, currency)
            return (
                f"📌 <b>{esc(name)} — PUNE BUY LIMIT DCA</b>\n"
                f"{label}\n"
                f"XTB: <b>{xtb}</b> | Yahoo: <b>{yf}</b>\n"
                f"Regime: <b>{esc(regime)}</b> ({esc(regime_details)})\n\n"
                f"Preț actual: <b>{fmt(close)}</b>\n"
                f"EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)} | ATR: {fmt(atr)}\n\n"
                f"Ordin(e) Buy Limit:\n"
                f"• Principal 60%: <b>{fmt(primary)}</b> | {allocation * 0.60:.0f} RON | qty {qty1:.4f}\n"
                f"• Secundar 40%: <b>{fmt(secondary)}</b> | {allocation * 0.40:.0f} RON | qty {qty2:.4f}"
            )

    return None
