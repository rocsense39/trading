from dataclasses import dataclass
import pandas as pd

EMA_FAST=20; EMA_MID=50; EMA_SLOW=150; ATR_LEN=20

@dataclass
class Snapshot:
    close: float; high: float; low: float
    ema20: float; ema50: float; ema150: float
    atr: float; hh20: float; ll20: float; rsi14: float
    volume: float; vol_ma: float


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df=df.copy()
    df['EMA20']=df['Close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA50']=df['Close'].ewm(span=EMA_MID, adjust=False).mean()
    df['EMA150']=df['Close'].ewm(span=EMA_SLOW, adjust=False).mean()
    pc=df['Close'].shift(1)
    tr=pd.concat([(df['High']-df['Low']),(df['High']-pc).abs(),(df['Low']-pc).abs()], axis=1).max(axis=1)
    df['ATR']=tr.rolling(ATR_LEN).mean()
    delta=df['Close'].diff(); gain=delta.clip(lower=0).rolling(14).mean(); loss=(-delta.clip(upper=0)).rolling(14).mean()
    df['RSI14']=100-(100/(1+(gain/loss.replace(0, pd.NA))))
    df['HH20']=df['High'].shift(1).rolling(20).max(); df['LL20']=df['Low'].shift(1).rolling(20).min()
    df['VOL_MA']=df['Volume'].rolling(20).mean()
    return df.dropna().copy()


def snapshot_from_df(df: pd.DataFrame) -> Snapshot|None:
    df=add_indicators(df)
    if df.empty or len(df)<80: return None
    r=df.iloc[-1]
    return Snapshot(float(r.Close),float(r.High),float(r.Low),float(r.EMA20),float(r.EMA50),float(r.EMA150),float(r.ATR),float(r.HH20),float(r.LL20),float(r.RSI14),float(r.Volume),float(r.VOL_MA))
