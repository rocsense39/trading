import pandas as pd
from market.indicators import snapshot_from_ohlcv

def test_indicators_create_snapshot_from_valid_ohlcv():
    n = 220
    close = pd.Series([100 + i * 0.2 for i in range(n)])
    df = pd.DataFrame({
        "Open": close - 0.1,
        "High": close + 0.5,
        "Low": close - 0.5,
        "Close": close,
        "Volume": [1000] * n,
    })
    s = snapshot_from_ohlcv("TEST", df)
    assert s.close > s.ema50 > s.ema150
    assert s.rsi14 >= 50
