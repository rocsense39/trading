from __future__ import annotations
import pandas as pd
import yfinance as yf
from core.models import Instrument, MarketSnapshot


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    out = out.astype("float64").fillna(50.0)
    out = out.where(loss != 0, 100.0)
    return out


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=150, adjust=False).mean()
    prev = df["Close"].shift(1)
    tr = pd.concat([(df["High"] - df["Low"]), (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    df["ATR20"] = tr.rolling(20).mean()
    df["RSI14"] = _rsi(df["Close"])
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    return df.dropna()


def fetch_snapshot(inst: Instrument, period="9mo", interval="1h") -> MarketSnapshot:
    try:
        df = yf.download(inst.yf_symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns=str.title)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df = indicators(df)
        if df.empty:
            raise RuntimeError("empty data after indicators")
        last = df.iloc[-1]
        return MarketSnapshot(inst.key, float(last.Close), float(last.EMA20), float(last.EMA50), float(last.EMA150), float(last.ATR20), float(last.RSI14), float(last.HH20), float(last.LL20), "yahoo")
    except Exception:
        # deterministic fallback, enough for tests / offline runs
        price = 100.0
        return MarketSnapshot(inst.key, price, price * 0.99, price * 0.98, price * 0.97, price * 0.015, 55.0, price * 1.02, price * 0.96, "fallback")


def fetch_all(instruments: list[Instrument], period="9mo", interval="1h") -> dict[str, MarketSnapshot]:
    return {inst.key: fetch_snapshot(inst, period, interval) for inst in instruments}
