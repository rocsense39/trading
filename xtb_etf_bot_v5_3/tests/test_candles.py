import pandas as pd
from strategy.candles import detect_bullish_patterns


def test_bullish_engulfing_detected():
    df = pd.DataFrame([
        {"Open": 100, "High": 102, "Low": 98, "Close": 101},
        {"Open": 101, "High": 102, "Low": 96, "Close": 97},
        {"Open": 96.5, "High": 103, "Low": 96, "Close": 102},
    ])
    assert "Bullish engulfing" in detect_bullish_patterns(df)


def test_hammer_detected():
    df = pd.DataFrame([
        {"Open": 100, "High": 101, "Low": 99, "Close": 100.5},
        {"Open": 100, "High": 101, "Low": 99, "Close": 100.2},
        {"Open": 100, "High": 100.6, "Low": 94, "Close": 100.4},
    ])
    assert "Hammer" in detect_bullish_patterns(df)
