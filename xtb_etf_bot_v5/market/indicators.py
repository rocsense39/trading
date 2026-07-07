from __future__ import annotations
import pandas as pd
from core.models import MarketSnapshot

def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    out = out.fillna(100).where(loss != 0, 100)
    return out

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=150, adjust=False).mean()
    prev = df["Close"].shift(1)
    tr = pd.concat([(df["High"]-df["Low"]), (df["High"]-prev).abs(), (df["Low"]-prev).abs()], axis=1).max(axis=1)
    df["ATR20"] = tr.rolling(20).mean()
    df["RSI14"] = rsi(df["Close"], 14)
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    return df.dropna()

def snapshot_from_ohlcv(symbol: str, df: pd.DataFrame, source: str = "test") -> MarketSnapshot:
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing OHLCV columns for {symbol}")
    ind = add_indicators(df)
    if ind.empty:
        raise ValueError(f"Not enough data for {symbol}")
    last = ind.iloc[-1]
    return MarketSnapshot(symbol=symbol, close=float(last.Close), ema20=float(last.EMA20), ema50=float(last.EMA50), ema150=float(last.EMA150), atr20=float(last.ATR20), rsi14=float(last.RSI14), hh20=float(last.HH20), ll20=float(last.LL20), source=source)
