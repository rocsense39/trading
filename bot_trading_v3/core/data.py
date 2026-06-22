from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


TZ = ZoneInfo("Europe/Berlin")


def get_data(symbol: str, period: str = "6mo", interval: str = "1h") -> pd.DataFrame:
    if not symbol:
        return pd.DataFrame()

    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        print(f"Download error {symbol}: {exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        print(f"No data for {symbol}")
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.rename(columns=str.title)
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(df.columns):
        print(f"Missing OHLCV for {symbol}: {list(df.columns)}")
        return pd.DataFrame()

    df = df[required].dropna().copy()

    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert(TZ)
        else:
            df.index = df.index.tz_convert(TZ)
    except Exception:
        pass

    return df


def drop_incomplete_candle(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) < 3:
        return df

    now = datetime.now(TZ)
    last = df.index[-1]
    try:
        if last.date() == now.date() and last.hour == now.hour:
            return df.iloc[:-1].copy()
    except Exception:
        return df

    return df
