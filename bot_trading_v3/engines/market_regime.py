from __future__ import annotations

from core.data import get_data
from core.indicators import add_indicators
from core.utils import fmt


def classify_market_regime(config: dict) -> tuple[str, str]:
    symbols = config.get("regime_symbols", {})
    score = 0
    details = []

    for label, symbol in [
        ("S&P", symbols.get("sp500", "SPY")),
        ("Nasdaq", symbols.get("nasdaq", "QQQ")),
    ]:
        df = get_data(symbol, period="6mo", interval="1d")
        if df.empty or len(df) < 80:
            details.append(f"{label}: n/a")
            continue

        df = add_indicators(df)
        if df.empty:
            details.append(f"{label}: n/a")
            continue

        last = df.iloc[-1]
        close = float(last["Close"])
        ema20 = float(last["EMA20"])
        ema50 = float(last["EMA50"])

        if close > ema20 > ema50:
            score += 1
            details.append(f"{label}: bullish")
        elif close < ema50:
            score -= 1
            details.append(f"{label}: weak")
        else:
            details.append(f"{label}: neutral")

    vix_df = get_data(symbols.get("vix", "^VIX"), period="3mo", interval="1d")
    if not vix_df.empty:
        vix = float(vix_df.iloc[-1]["Close"])
        if vix < 18:
            score += 1
            details.append(f"VIX: calm {fmt(vix)}")
        elif vix > 25:
            score -= 1
            details.append(f"VIX: high {fmt(vix)}")
        else:
            details.append(f"VIX: neutral {fmt(vix)}")

    if score >= 2:
        return "RISK ON", "; ".join(details)
    if score <= -1:
        return "RISK OFF", "; ".join(details)
    return "NEUTRAL", "; ".join(details)
