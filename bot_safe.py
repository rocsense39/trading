import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# =========================
# CONFIG
# =========================

def send_telegram(msg: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Lipsesc BOT_TOKEN sau CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print("Telegram error:", e)


SYMBOLS = {
    "SGLD": "SGLD.L",
    "XLEP": "XLEP.L",
    "ESIE": "ESIE.DE",
    "SXR8": "SXR8.DE",
    "JNJ": "JNJ"
}

INTERVAL = "1h"
PERIOD = "3mo"
SLEEP_SECONDS = 900  # 15 min

TZ = ZoneInfo("Europe/Berlin")

EMA_FAST = 20
EMA_SLOW = 50
ATR_LEN = 14
VOL_MA_LEN = 20
RR = 2.0

last_alerts = {}

# =========================
# TELEGRAM
# =========================
def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg
    }
    requests.post(url, json=payload, timeout=15)

# =========================
# DATA
# =========================
def get_data(symbol: str) -> pd.DataFrame:
    df = yf.download(
        symbol,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=True,
        progress=False
    )

    if df.empty:
        return df

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.dropna().copy()
    return df

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs()
    ], axis=1).max(axis=1)

    df["ATR"] = tr.rolling(ATR_LEN).mean()
    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_LEN).mean()
    df["HH_10"] = df["High"].shift(1).rolling(10).max()
    df["LL_10"] = df["Low"].shift(1).rolling(10).min()

    return df.dropna()

# =========================
# HELPERS
# =========================
def fmt(x: float) -> str:
    if x >= 100:
        return f"{x:.2f}"
    if x >= 10:
        return f"{x:.2f}"
    return f"{x:.4f}"

def safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0

def get_quality(score: int) -> str:
    if score >= 4:
        return "HIGH"
    if score == 3:
        return "MEDIUM"
    return "LOW"

# =========================
# ANALYSIS
# =========================
def analyze(name: str, symbol: str) -> str | None:
    df = get_data(symbol)
    if df.empty or len(df) < 80:
        return None

    df = add_indicators(df)
    if df.empty or len(df) < 30:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = safe_float(last["Close"])
    high = safe_float(last["High"])
    low = safe_float(last["Low"])
    ema20 = safe_float(last["EMA20"])
    ema50 = safe_float(last["EMA50"])
    atr = safe_float(last["ATR"])
    vol = safe_float(last["Volume"])
    vol_ma = safe_float(last["VOL_MA"])
    hh10 = safe_float(last["HH_10"])

    if atr <= 0 or close <= 0:
        return None

    trend = close > ema20 > ema50
    strong_trend = (ema20 - ema50) / close > 0.0025
    near_ema = abs(close - ema20) / close <= 0.005
    volume_ok = vol > vol_ma
    green_candle = close > safe_float(last["Open"])
    atr_rising = atr > safe_float(prev["ATR"])
    breakout_ready = close > hh10 if hh10 > 0 else False

    score = 0
    if trend:
        score += 1
    if strong_trend:
        score += 1
    if near_ema:
        score += 1
    if volume_ok:
        score += 1
    if green_candle:
        score += 1

    quality = get_quality(score)

    candle_key = f"{name}_{df.index[-1]}"
    if last_alerts.get(name) == candle_key:
        return None

    if quality == "LOW":
        return None

    # MEDIUM = watchlist only
    if quality == "MEDIUM":
        msg = (
            f"👀 {name}\n\n"
            f"Trend: bullish\n"
            f"Setup: pullback detectat\n\n"
            f"Price: {fmt(close)}\n"
            f"EMA20: {fmt(ema20)}\n"
            f"EMA50: {fmt(ema50)}\n\n"
            f"Calitate: MEDIUM\n"
            f"Acțiune: WATCHLIST\n\n"
            f"Așteaptă confirmare:\n"
            f"• bounce clar din EMA20\n"
            f"• sau breakout peste maximul recent"
        )
        last_alerts[name] = candle_key
        return msg

    # HIGH = full setup
    entry = close
    sl = min(float(df.tail(5)["Low"].min()), entry - 1.2 * atr)
    tp = entry + RR * (entry - sl)

    confirm_text = "Breakout gata" if breakout_ready else "Trend + pullback confirmat"

    msg = (
        f"🟢 {name}\n\n"
        f"Trend: bullish\n"
        f"Setup: {confirm_text}\n\n"
        f"Price: {fmt(close)}\n\n"
        f"Entry: {fmt(entry)}\n"
        f"SL: {fmt(sl)}\n"
        f"TP: {fmt(tp)}\n\n"
        f"EMA20: {fmt(ema20)}\n"
        f"EMA50: {fmt(ema50)}\n"
        f"ATR: {fmt(atr)}\n\n"
        f"Calitate: HIGH"
    )

    last_alerts[name] = candle_key
    return msg

# =========================
# MAIN LOOP
# =========================
def run():
    send_telegram("✅ SAFE BOT v2 pornit: MEDIUM=WATCHLIST, HIGH=setup complet")
    print("Bot rulează...")

    while True:
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Scan...")

        for name, sym in SYMBOLS.items():
            try:
                msg = analyze(name, sym)
                if msg:
                    send_telegram(msg)
                    print("Alert:", name)
            except Exception as e:
                print(f"Error on {name}: {e}")

        time.sleep(SLEEP_SECONDS)

run()
