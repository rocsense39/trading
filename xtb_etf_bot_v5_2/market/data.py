from __future__ import annotations

import contextlib
import io
import logging
import warnings

import pandas as pd
import yfinance as yf

from core.models import Instrument, MarketSnapshot

# Silence noisy yfinance messages such as "1 Failed download" and HTTP quoteSummary 404.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", category=FutureWarning)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce").astype("float64")
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
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=150, adjust=False).mean()
    prev = df["Close"].shift(1)
    tr = pd.concat(
        [
            (df["High"] - df["Low"]),
            (df["High"] - prev).abs(),
            (df["Low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR20"] = tr.rolling(20).mean()
    df["RSI14"] = _rsi(df["Close"])
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    return df.dropna()


@contextlib.contextmanager
def _quiet_yfinance():
    # yfinance prints some failures directly to stdout/stderr. Suppress them; we handle failures safely.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def _download(symbol: str, period: str, interval: str) -> pd.DataFrame:
    with _quiet_yfinance():
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError(f"empty yfinance data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(df.columns):
        raise RuntimeError(f"missing OHLCV columns for {symbol}: {list(df.columns)}")
    df = df[required].dropna()
    if len(df) < 180:
        raise RuntimeError(f"not enough rows for {symbol}: {len(df)}")
    df = indicators(df)
    if df.empty:
        raise RuntimeError(f"empty data after indicators for {symbol}")
    return df


def _snapshot_from_df(key: str, df: pd.DataFrame, source: str) -> MarketSnapshot:
    last = df.iloc[-1]
    return MarketSnapshot(
        key=key,
        close=float(last.Close),
        ema20=float(last.EMA20),
        ema50=float(last.EMA50),
        ema150=float(last.EMA150),
        atr20=float(last.ATR20),
        rsi14=float(last.RSI14),
        high20=float(last.HH20),
        low20=float(last.LL20),
        source=source,
    )


def _configured_fallback(inst: Instrument) -> MarketSnapshot | None:
    if inst.fallback_close is None:
        return None
    close = float(inst.fallback_close)
    return MarketSnapshot(
        key=inst.key,
        close=close,
        ema20=float(inst.fallback_ema20 if inst.fallback_ema20 is not None else close * 1.01),
        ema50=float(inst.fallback_ema50 if inst.fallback_ema50 is not None else close * 1.02),
        ema150=float(inst.fallback_ema150 if inst.fallback_ema150 is not None else close * 1.03),
        atr20=float(inst.fallback_atr20 if inst.fallback_atr20 is not None else close * 0.02),
        rsi14=float(inst.fallback_rsi14 if inst.fallback_rsi14 is not None else 35.0),
        high20=float(inst.fallback_high20 if inst.fallback_high20 is not None else close * 1.02),
        low20=float(inst.fallback_low20 if inst.fallback_low20 is not None else close * 0.96),
        source="static_fallback",
    )


def _safe_generic_fallback(inst: Instrument) -> MarketSnapshot:
    # Deliberately weak/neutral: never create a false bullish BUY signal from missing data.
    price = float(inst.fallback_close or 100.0)
    return MarketSnapshot(
        inst.key,
        price,
        price * 1.01,
        price * 1.02,
        price * 1.03,
        price * 0.02,
        35.0,
        price * 1.02,
        price * 0.96,
        "fallback_no_data",
    )


def fetch_snapshot(inst: Instrument, period="9mo", interval="1h") -> MarketSnapshot:
    candidates = [inst.yf_symbol]
    for symbol in inst.yf_symbol_candidates:
        if symbol and symbol not in candidates:
            candidates.append(symbol)

    for symbol in candidates:
        try:
            df = _download(symbol, period, interval)
            return _snapshot_from_df(inst.key, df, "yahoo")
        except Exception:
            continue

    configured = _configured_fallback(inst)
    if configured is not None:
        return configured
    return _safe_generic_fallback(inst)


def fetch_all(instruments: list[Instrument], period="9mo", interval="1h") -> dict[str, MarketSnapshot]:
    return {inst.key: fetch_snapshot(inst, period, interval) for inst in instruments}
