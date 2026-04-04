import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# =========================
# CONFIG
# =========================
TOKEN = "8581114074:AAFS55UBbtGPQR0NAzBYc3QOpDYFOzqY1A"
CHAT_ID = "8631997789"


SYMBOLS = {
    "GOLD": "GC=F",   # aur futures
    "SP500": "SPY",   # proxy S&P500
    "EXXON": "XOM",
    "ENERGY": "XLE",  # daca gasesti ticker bun pentru XLEP.UK, inlocuiesti aici
}

INTERVAL = "1h"
PERIOD = "20d"
SLEEP_SECONDS = 900   # 15 minute

EMA_FAST = 20
EMA_SLOW = 50
ATR_LEN = 14
VOL_MA_LEN = 20

RISK_PCT_SL = 0.012   # 1.2% default, doar orientativ
RR = 2.0              # risk/reward

NY_TZ = ZoneInfo("America/New_York")
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
        threads=False
    )

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns=str.title).copy()

    # yfinance poate întoarce MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    return df.dropna().copy()


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

    df["HH_10"] = df["High"].rolling(10).max()
    df["LL_10"] = df["Low"].rolling(10).min()

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


def analyze_symbol(name: str, symbol: str) -> str | None:
    df = get_data(symbol)
    if df.empty or len(df) < 60:
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

    trend_bull = close_ > ema20 > ema50
    trend_bear = close_ < ema20 < ema50

    near_ema20 = abs(close_ - ema20) / close_ <= 0.006
    breakout_up = close_ > float(df.iloc[-2]["HH_10"])
    breakdown_down = close_ < float(df.iloc[-2]["LL_10"])

    volume_ok = vol > vol_ma
    atr_rising = float(last["ATR"]) > float(prev["ATR"])

    # cheie unică pe lumânare ca să nu repete alerta
    candle_key = f"{name}_{df.index[-1]}"
    if last_alerts.get(name) == candle_key:
        return None

    message = None

    # 1) Pullback bullish sănătos
    if trend_bull and near_ema20:
        entry = close_
        sl = min(float(df.tail(5)["Low"].min()), entry - 1.2 * atr)
        tp = entry + RR * (entry - sl)

        message = (
            f"🟢 <b>{name}</b> ({symbol})\n"
            f"Setup: <b>Trend bullish + pullback la EMA20</b>\n"
            f"Preț: {format_price(close_)}\n"
            f"EMA20: {format_price(ema20)} | EMA50: {format_price(ema50)}\n"
            f"ATR: {format_price(atr)} | Volum vs medie: {vol:.0f} / {vol_ma:.0f}\n\n"
            f"Idee:\n"
            f"• bias: BUY doar pe confirmare\n"
            f"• entry orientativ: {format_price(entry)}\n"
            f"• SL orientativ: {format_price(sl)}\n"
            f"• TP orientativ: {format_price(tp)}"
        )

    # 2) Breakout bullish
    elif breakout_up and trend_bull and (volume_ok or atr_rising):
        entry = close_
        sl = entry - 1.5 * atr
        tp = entry + RR * (entry - sl)

        message = (
            f"🚀 <b>{name}</b> ({symbol})\n"
            f"Setup: <b>Breakout bullish</b>\n"
            f"Preț: {format_price(close_)}\n"
            f"EMA20: {format_price(ema20)} | EMA50: {format_price(ema50)}\n"
            f"ATR: {format_price(atr)} | Volum vs medie: {vol:.0f} / {vol_ma:.0f}\n\n"
            f"Idee:\n"
            f"• bias: BUY STOP / intrare pe confirmare\n"
            f"• entry orientativ: {format_price(entry)}\n"
            f"• SL orientativ: {format_price(sl)}\n"
            f"• TP orientativ: {format_price(tp)}"
        )

    # 3) Breakdown bearish
    elif breakdown_down and trend_bear and (volume_ok or atr_rising):
        entry = close_
        sl = entry + 1.5 * atr
        tp = entry - RR * (sl - entry)

        message = (
            f"🔴 <b>{name}</b> ({symbol})\n"
            f"Setup: <b>Breakdown bearish</b>\n"
            f"Preț: {format_price(close_)}\n"
            f"EMA20: {format_price(ema20)} | EMA50: {format_price(ema50)}\n"
            f"ATR: {format_price(atr)} | Volum vs medie: {vol:.0f} / {vol_ma:.0f}\n\n"
            f"Idee:\n"
            f"• bias: SELL / evită BUY\n"
            f"• entry orientativ: {format_price(entry)}\n"
            f"• SL orientativ: {format_price(sl)}\n"
            f"• TP orientativ: {format_price(tp)}"
        )

    # 4) Stare neutră utilă
    else:
        return None

    last_alerts[name] = candle_key
    return message


# =========================
# MAIN
# =========================
def run():
    send_telegram("✅ Bot TREND/PULLBACK pornit.")
    while True:
        now = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{now}] Scan...")

        for name, symbol in SYMBOLS.items():
            try:
                msg = analyze_symbol(name, symbol)
                if msg:
                    send_telegram(msg)
                    print(f"Alert sent: {name}")
            except Exception as e:
                print(f"Error on {name}: {e}")

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    run()