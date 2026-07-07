from __future__ import annotations
from typing import Any
from .market import download, add_indicators


def classify_regime(cfg: dict[str, Any]) -> tuple[str, int, str]:
    symbols = cfg.get("regime_symbols", {})
    tz = cfg["settings"].get("timezone", "Europe/Berlin")
    score = 50
    notes: list[str] = []
    for label, sym in [("S&P", symbols.get("sp500", "SPY")), ("Nasdaq", symbols.get("nasdaq", "QQQ"))]:
        df = add_indicators(download(sym, period="9mo", interval="1d", tz_name=tz))
        if df.empty:
            notes.append(f"{label}: n/a")
            continue
        r = df.iloc[-1]
        close, ema20, ema50, ema150 = float(r["Close"]), float(r["EMA20"]), float(r["EMA50"]), float(r["EMA150"])
        if close > ema20 > ema50 > ema150:
            score += 15
            notes.append(f"{label}: strong trend")
        elif close > ema50 > ema150:
            score += 8
            notes.append(f"{label}: positive")
        elif close < ema50:
            score -= 12
            notes.append(f"{label}: weak")
        else:
            notes.append(f"{label}: neutral")
    vix_df = download(symbols.get("vix", "^VIX"), period="3mo", interval="1d", tz_name=tz)
    if not vix_df.empty:
        vix = float(vix_df.iloc[-1]["Close"])
        if vix < 18:
            score += 10
            notes.append(f"VIX calm {vix:.2f}")
        elif vix > 25:
            score -= 20
            notes.append(f"VIX high {vix:.2f}")
        else:
            notes.append(f"VIX neutral {vix:.2f}")
    score = max(0, min(100, score))
    regime = "RISK ON" if score >= 70 else "RISK OFF" if score < 40 else "NEUTRAL"
    return regime, score, "; ".join(notes)
