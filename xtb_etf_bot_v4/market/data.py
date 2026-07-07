from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from core.config import BotConfig
from core.models import PriceSnapshot
from .indicators import Snapshot, snapshot_from_df

MKT_TZ = ZoneInfo("Europe/Berlin")

# Static fallback is deliberately explicit. It lets Module 2 run even when Yahoo is unavailable,
# but the report will mark those rows as source=fallback_static.
STATIC_FALLBACK_PRICES: dict[str, float] = {
    "SXR8": 709.28,
    "SXRV": 1490.80,
    "QUALITY": 76.98,
    "AIINFRA": 9.788,
    "GINFRA": 6.145,
    "XMME": 82.192,
    "H411": 81.63,
}


@dataclass(frozen=True)
class MarketResult:
    snapshots: dict[str, Snapshot]
    prices: dict[str, PriceSnapshot]
    missing: dict[str, str]


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    if df is None or df.empty:
        return pd.DataFrame(columns=required)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)
    if not set(required).issubset(df.columns):
        return pd.DataFrame(columns=required)
    df = df[required].dropna().copy()
    if df.empty:
        return df
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(MKT_TZ)
    else:
        df.index = df.index.tz_convert(MKT_TZ)
    return df


def download_yahoo_ohlcv(symbol: str, *, period: str = "9mo", interval: str = "1h") -> pd.DataFrame:
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        print(f"{symbol}: Yahoo download failed: {exc}")
        return pd.DataFrame()
    return _normalize_ohlcv(df)


def get_yahoo_snapshot(symbol: str, *, period: str = "9mo", interval: str = "1h") -> Snapshot | None:
    df = download_yahoo_ohlcv(symbol, period=period, interval=interval)
    return snapshot_from_df(df, symbol=symbol, source="yahoo")


def _fallback_snapshot(key: str) -> Snapshot | None:
    price = STATIC_FALLBACK_PRICES.get(key)
    if price is None:
        return None
    # Build a smooth synthetic series only for offline testing/report continuity.
    # This is never treated as a trading-quality signal.
    dates = pd.date_range(end=pd.Timestamp.now(tz=MKT_TZ), periods=220, freq="h")
    base = pd.Series([price * (0.95 + 0.05 * i / 219) for i in range(220)], index=dates)
    df = pd.DataFrame(
        {
            "Open": base.shift(1).fillna(base.iloc[0]),
            "High": base * 1.002,
            "Low": base * 0.998,
            "Close": base,
            "Volume": 1000.0,
        }
    )
    return snapshot_from_df(df, symbol=key, source="fallback_static")


def fetch_market(config: BotConfig, *, allow_static_fallback: bool = True) -> MarketResult:
    snapshots: dict[str, Snapshot] = {}
    prices: dict[str, PriceSnapshot] = {}
    missing: dict[str, str] = {}

    for key, instrument in config.instruments.items():
        snap = get_yahoo_snapshot(instrument.yf_symbol)
        if snap is None and allow_static_fallback:
            snap = _fallback_snapshot(key)
        if snap is None:
            missing[key] = f"no usable market data for {instrument.yf_symbol}"
            continue
        snapshots[key] = snap
        prices[key] = PriceSnapshot(key=key, close=snap.close)
    return MarketResult(snapshots=snapshots, prices=prices, missing=missing)
