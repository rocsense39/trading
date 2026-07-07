from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd
from .indicators import snapshot_from_df, Snapshot

MKT_TZ=ZoneInfo('Europe/Berlin')

def get_ohlcv(symbol: str, period='9mo', interval='1h') -> pd.DataFrame:
    try:
        df=yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception as e:
        print(f'{symbol}: download failed: {e}'); return pd.DataFrame()
    if df is None or df.empty: return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex): df.columns=[c[0] for c in df.columns]
    df=df.rename(columns=str.title)
    cols=['Open','High','Low','Close','Volume']
    if not set(cols).issubset(df.columns): return pd.DataFrame()
    df=df[cols].dropna().copy()
    if df.index.tz is None: df.index=df.index.tz_localize('UTC').tz_convert(MKT_TZ)
    else: df.index=df.index.tz_convert(MKT_TZ)
    return df

def get_snapshot(symbol: str) -> Snapshot|None:
    return snapshot_from_df(get_ohlcv(symbol))
