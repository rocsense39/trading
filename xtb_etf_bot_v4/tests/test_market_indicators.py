from __future__ import annotations

import pandas as pd

from market.indicators import add_indicators, snapshot_from_df


def test_indicators_create_snapshot_from_valid_ohlcv():
    dates = pd.date_range("2026-01-01", periods=220, freq="h", tz="UTC")
    close = pd.Series([100 + i * 0.1 for i in range(220)], index=dates)
    df = pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": 1000,
        }
    )
    enriched = add_indicators(df)
    assert not enriched.empty
    snap = snapshot_from_df(df, symbol="TEST", source="unit")
    assert snap is not None
    assert snap.close > snap.ema50
    assert snap.atr20 > 0
    assert snap.source == "unit"


def test_snapshot_returns_none_for_empty_df():
    assert snapshot_from_df(pd.DataFrame(), symbol="EMPTY") is None
