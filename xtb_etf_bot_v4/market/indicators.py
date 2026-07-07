from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 150
ATR_LEN = 20
RSI_LEN = 14
VOL_MA_LEN = 20


@dataclass(frozen=True)
class Snapshot:
    symbol: str
    close: float
    high: float
    low: float
    ema20: float
    ema50: float
    ema150: float
    atr20: float
    hh20: float
    ll20: float
    rsi14: float
    volume: float
    vol_ma20: float
    rows: int
    source: str = "unknown"

    @property
    def above_ema50(self) -> bool:
        return self.close > self.ema50

    @property
    def above_ema150(self) -> bool:
        return self.close > self.ema150

    @property
    def strong_short_trend(self) -> bool:
        return self.close > self.ema20 > self.ema50

    @property
    def strong_long_trend(self) -> bool:
        return self.close > self.ema20 > self.ema50 > self.ema150

    @property
    def rsi_supportive(self) -> bool:
        return self.rsi14 >= 50


def _require_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    if df is None or df.empty:
        return pd.DataFrame(columns=required)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)
    if not set(required).issubset(df.columns):
        return pd.DataFrame(columns=required)
    return df[required].dropna().copy()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = _require_ohlcv(df)
    if df.empty:
        return df

    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    previous_close = df["Close"].shift(1)
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - previous_close).abs(),
            (df["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR20"] = true_range.rolling(ATR_LEN).mean()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_LEN).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_LEN).mean()
    # Robust RSI: when loss is zero and gain is positive, RSI should be 100,
    # not NaN. The first implementation returned NaNs on clean rising test
    # series and made the indicator table empty after dropna().
    rs = gain / loss.replace(0, pd.NA)
    df["RSI14"] = 100 - (100 / (1 + rs))
    df.loc[(loss == 0) & (gain > 0), "RSI14"] = 100.0
    df.loc[(loss == 0) & (gain == 0), "RSI14"] = 50.0

    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    df["VOL_MA20"] = df["Volume"].rolling(VOL_MA_LEN).mean()

    return df.dropna().copy()


def snapshot_from_df(df: pd.DataFrame, *, symbol: str, source: str = "unknown") -> Snapshot | None:
    enriched = add_indicators(df)
    if enriched.empty or len(enriched) < 80:
        return None
    row = enriched.iloc[-1]
    return Snapshot(
        symbol=symbol,
        close=float(row["Close"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        ema20=float(row["EMA20"]),
        ema50=float(row["EMA50"]),
        ema150=float(row["EMA150"]),
        atr20=float(row["ATR20"]),
        hh20=float(row["HH20"]),
        ll20=float(row["LL20"]),
        rsi14=float(row["RSI14"]),
        volume=float(row["Volume"]),
        vol_ma20=float(row["VOL_MA20"]),
        rows=len(enriched),
        source=source,
    )
