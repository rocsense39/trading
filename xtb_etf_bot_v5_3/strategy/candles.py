from __future__ import annotations

import pandas as pd


def _body(row) -> float:
    return abs(float(row["Close"]) - float(row["Open"]))


def _range(row) -> float:
    return max(float(row["High"]) - float(row["Low"]), 1e-9)


def detect_bullish_patterns(df: pd.DataFrame) -> tuple[str, ...]:
    """Detect a small set of bullish confirmation candles on the latest bar.

    These are intentionally simple and conservative. They are confirmations,
    not standalone buy signals.
    """
    if df is None or len(df) < 3:
        return ()

    d = df.dropna(subset=["Open", "High", "Low", "Close"]).tail(4)
    if len(d) < 3:
        return ()

    last = d.iloc[-1]
    prev = d.iloc[-2]
    prev2 = d.iloc[-3]

    o = float(last["Open"])
    h = float(last["High"])
    l = float(last["Low"])
    c = float(last["Close"])
    po = float(prev["Open"])
    ph = float(prev["High"])
    pl = float(prev["Low"])
    pc = float(prev["Close"])
    p2o = float(prev2["Open"])
    p2h = float(prev2["High"])
    p2l = float(prev2["Low"])
    p2c = float(prev2["Close"])

    body = abs(c - o)
    rng = max(h - l, 1e-9)
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)

    patterns: list[str] = []

    # Bullish engulfing: latest bullish body engulfs previous bearish body.
    if c > o and pc < po and o <= pc and c >= po:
        patterns.append("Bullish engulfing")

    # Hammer: small body in upper part of candle with long lower wick.
    if body > 0 and lower_shadow >= 2.0 * body and upper_shadow <= max(body, 0.25 * rng) and c >= o:
        patterns.append("Hammer")

    # Piercing line: bearish candle followed by bullish candle closing above midpoint.
    prev_mid = (po + pc) / 2
    if pc < po and c > o and o <= pc and c > prev_mid and c < po:
        patterns.append("Piercing line")

    # Morning star: bearish candle, small indecision candle, then bullish close above midpoint.
    prev2_body = abs(p2c - p2o)
    prev_body = abs(pc - po)
    prev2_mid = (p2o + p2c) / 2
    if p2c < p2o and prev_body <= 0.55 * max(prev2_body, 1e-9) and c > o and c > prev2_mid:
        patterns.append("Morning star")

    # Inside bar breakout: previous candle is inside the one before it; latest closes above previous high.
    if ph <= p2h and pl >= p2l and c > ph:
        patterns.append("Inside bar breakout")

    # Strong bullish candle / marubozu-like bar.
    if c > o and body >= 0.70 * rng and (h - c) <= 0.15 * rng:
        patterns.append("Strong bullish candle")

    # 20-bar breakout confirmation, if indicator exists.
    if "HH20" in df.columns:
        hh20 = float(last.get("HH20", float("nan")))
        if pd.notna(hh20) and c > hh20:
            patterns.append("20-bar breakout")

    # Deduplicate while preserving order.
    return tuple(dict.fromkeys(patterns))
