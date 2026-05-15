import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# =========================
# CONFIG
# =========================
TOKEN = "8581114074:AAFS55UBbtGPQR0NAzBYc3QOpDYFQzqY1A"
CHAT_ID = "8631997789"


SYMBOLS = {
    "SGLD": {
        "xtb_symbol": "SGLD.UK",
        "yf_symbol": "SGLD.L",
        "label": "Physical Gold ETC"
    },
    "XLEP": {
        "xtb_symbol": "XLEP.UK",
        "yf_symbol": "XLEP.L",
        "label": "Energy S&P US Select Sector ETF"
    },
    "ESIE": {
        "xtb_symbol": "ESIE.DE",
        "yf_symbol": "ESIE.DE",
        "label": "MSCI Europe Energy ETF"
    },
    "SXR8": {
        "xtb_symbol": "SXR8.DE",
        "yf_symbol": "SXR8.DE",
        "label": "Core S&P 500 ETF"
    },
}

INTERVAL = "1h"
PERIOD = "3mo"
SLEEP_SECONDS = 900  # 15 minute

EMA_FAST = 20
EMA_SLOW = 50
ATR_LEN = 14
VOL_MA_LEN = 20
RR = 2.0

# timezone pentru bursele europene
MKT_TZ = ZoneInfo("Europe/Berlin")

last_alerts = {}


# =========================
# TELEGRAM
# =========================
def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")


# =========================
# DATA
# =========================
def get_data(symbol: str) -> pd.DataFrame:
    df = yf.download(
        symbol,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.rename(columns=str.title).copy()

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    df = df[list(required)].dropna().copy()

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(MKT_TZ)
    else:
        df.index = df.index.tz_convert(MKT_TZ)

    return df


def drop_incomplete_candle(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) < 3:
        return df

    now = datetime.now(MKT_TZ)
    last_ts = df.index[-1]

    # elimină lumânarea încă în formare
    if (
        last_ts.year == now.year
        and last_ts.month == now.month
        and last_ts.day == now.day
        and last_ts.hour == now.hour
    ):
        return df.iloc[:-1].copy()

    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(ATR_LEN).mean()

    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_LEN).mean()
    df["HH_10_PREV"] = df["High"].shift(1).rolling(10).max()
    df["LL_10_PREV"] = df["Low"].shift(1).rolling(10).min()

    return df.dropna().copy()


# =========================
# LOGIC
# =========================
def format_price(x: float) -> str:
    if x >= 100:
        return f"{x:.2f}"
    if x >= 10:
        return f"{x:.2f}"
    return f"{x:.4f}"


def build_message(title: str, xtb_symbol: str, yf_symbol: str, setup: str,
                  close_: float, ema20: float, ema50: float,
                  atr: float, vol: float, vol_ma: float,
                  entry: float, sl: float, tp: float, icon: str, bias: str) -> str:
    return (
        f"{icon} <b>{title}</b>\n"
        f"XTB: <b>{xtb_symbol}</b> | Yahoo: <b>{yf_symbol}</b>\n"
        f"Setup: <b>{setup}</b>\n"
        f"Preț: {format_price(close_)}\n"
        f"EMA20: {format_price(ema20)} | EMA50: {format_price(ema50)}\n"
        f"ATR: {format_price(atr)} | Volum vs medie: {vol:.0f} / {vol_ma:.0f}\n\n"
        f"Idee:\n"
        f"• bias: {bias}\n"
        f"• entry orientativ: {format_price(entry)}\n"
        f"• SL orientativ: {format_price(sl)}\n"
        f"• TP orientativ: {format_price(tp)}"
    )


def analyze_symbol(name: str, meta: dict) -> str | None:
    xtb_symbol = meta["xtb_symbol"]
    yf_symbol = meta["yf_symbol"]
    label = meta["label"]

    df = get_data(yf_symbol)
    if df.empty or len(df) < 80:
        return None

    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 80:
        return None

    df = add_indicators(df)
    if df.empty or len(df) < 5:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close_ = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    atr = float(last["ATR"])
    vol = float(last["Volume"])
    vol_ma = float(last["VOL_MA"])
    hh_10_prev = float(last["HH_10_PREV"])
    ll_10_prev = float(last["LL_10_PREV"])

    trend_bull = close_ > ema20 > ema50
    trend_bear = close_ < ema20 < ema50
    near_ema20 = abs(close_ - ema20) / close_ <= 0.007
    breakout_up = close_ > hh_10_prev
    breakdown_down = close_ < ll_10_prev
    volume_ok = vol > vol_ma
    atr_rising = float(last["ATR"]) > float(prev["ATR"])

    candle_key = f"{name}_{df.index[-1].isoformat()}"
    if last_alerts.get(name) == candle_key:
        return None

    message = None
    title = label

    if trend_bull and near_ema20:
        entry = close_
        sl = min(float(df.tail(5)["Low"].min()), entry - 1.2 * atr)
        tp = entry + RR * (entry - sl)
        message = build_message(
            title, xtb_symbol, yf_symbol,
            "Trend bullish + pullback la EMA20",
            close_, ema20, ema50, atr, vol, vol_ma,
            entry, sl, tp,
            "🟢", "BUY doar pe confirmare"
        )

    elif breakout_up and trend_bull and (volume_ok or atr_rising):
        entry = close_
        sl = entry - 1.5 * atr
        tp = entry + RR * (entry - sl)
        message = build_message(
            title, xtb_symbol, yf_symbol,
            "Breakout bullish",
            close_, ema20, ema50, atr, vol, vol_ma,
            entry, sl, tp,
            "🚀", "BUY STOP / intrare pe confirmare"
        )

    elif breakdown_down and trend_bear and (volume_ok or atr_rising):
        entry = close_
        sl = entry + 1.5 * atr
        tp = entry - RR * (sl - entry)
        message = build_message(
            title, xtb_symbol, yf_symbol,
            "Breakdown bearish",
            close_, ema20, ema50, atr, vol, vol_ma,
            entry, sl, tp,
            "🔴", "SELL / evită BUY"
        )

    if message:
        last_alerts[name] = candle_key

    return message


def run():
    send_telegram("✅ Bot ETF/ETC sincronizat a pornit.")
    while True:
        now = datetime.now(MKT_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{now}] Scan ETF/ETC...")

        for name, meta in SYMBOLS.items():
            try:
                msg = analyze_symbol(name, meta)
                if msg:
                    send_telegram(msg)
                    print(f"Alert sent: {name}")
            except Exception as e:
                print(f"Error on {name}: {e}")

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    run()
