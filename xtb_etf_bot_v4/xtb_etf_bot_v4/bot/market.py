from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo
from datetime import datetime
import pandas as pd
import yfinance as yf

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 150
ATR_LEN = 20
VOL_MA_LEN = 20

@dataclass(frozen=True)
class Snapshot:
    close: float
    high: float
    low: float
    ema20: float
    ema50: float
    ema150: float
    atr: float
    hh20: float
    ll20: float
    rsi14: float
    volume: float
    vol_ma: float


def download(symbol: str, period: str = "9mo", interval: str = "1h", tz_name: str = "Europe/Berlin") -> pd.DataFrame:
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        print(f"{symbol}: download failed — {exc}")
        return pd.DataFrame()
    if df is None or df.empty:
        print(f"{symbol}: no market data")
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)
    need = {"Open", "High", "Low", "Close", "Volume"}
    if not need.issubset(df.columns):
        print(f"{symbol}: missing OHLCV columns")
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    tz = ZoneInfo(tz_name)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(tz)
    else:
        df.index = df.index.tz_convert(tz)
    if len(df) >= 3:
        now = datetime.now(tz)
        last = df.index[-1]
        if last.year == now.year and last.month == now.month and last.day == now.day and last.hour == now.hour:
            df = df.iloc[:-1].copy()
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
    prev = df["Close"].shift(1)
    tr = pd.concat([(df["High"] - df["Low"]), (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(ATR_LEN).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["RSI14"] = 100 - (100 / (1 + rs))
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_LEN).mean()
    return df.dropna().copy()


def snapshot(symbol: str, tz_name: str = "Europe/Berlin") -> Snapshot | None:
    df = add_indicators(download(symbol, tz_name=tz_name))
    if df.empty or len(df) < 120:
        return None
    r = df.iloc[-1]
    return Snapshot(
        close=float(r["Close"]), high=float(r["High"]), low=float(r["Low"]),
        ema20=float(r["EMA20"]), ema50=float(r["EMA50"]), ema150=float(r["EMA150"]),
        atr=float(r["ATR"]), hh20=float(r["HH20"]), ll20=float(r["LL20"]),
        rsi14=float(r["RSI14"]), volume=float(r["Volume"]), vol_ma=float(r["VOL_MA"])
    )
