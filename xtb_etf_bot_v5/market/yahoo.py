from __future__ import annotations
import pandas as pd
import yfinance as yf
from core.models import MarketSnapshot
from .indicators import snapshot_from_ohlcv

def fetch_snapshot(symbol: str, period: str = "9mo", interval: str = "1h") -> MarketSnapshot | None:
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)
    try:
        return snapshot_from_ohlcv(symbol, df[["Open","High","Low","Close","Volume"]].dropna(), source="yahoo")
    except Exception:
        return None
