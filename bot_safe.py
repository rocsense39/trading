import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

SYMBOLS = {
    # PRIORITARE = cele pe care le urmărești / le ai deja
    "IUHC": {"yf": "IUHC.L", "kind": "ETF", "priority": True},
    "SPYN": {"yf": "SPYN.DE", "kind": "ETF", "priority": True},
    "ESIE": {"yf": "ESIE.DE", "kind": "ETF", "priority": True},
    "XLEP": {"yf": "XLEP.L", "kind": "ETF", "priority": True},
    "JNJ":  {"yf": "JNJ", "kind": "STOCK", "priority": True},
    "SGLD": {"yf": "SGLD.L", "kind": "ETC", "priority": True},

    # WATCHLIST
    "AXTI": {"yf": "AXTI", "kind": "STOCK", "priority": False},
    "AAOI": {"yf": "AAOI", "kind": "STOCK", "priority": False},
    "ABBV": {"yf": "ABBV", "kind": "STOCK", "priority": False},
    "H411": {"yf": "H411.DE", "kind": "ETF", "priority": False},
    "ARTL": {"yf": "ARTL", "kind": "STOCK", "priority": False},
    "XOM":  {"yf": "XOM", "kind": "STOCK", "priority": False},
}

INTERVAL = "1h"
PERIOD = "3mo"
SLEEP_SECONDS = 900   # 15 min
TZ = ZoneInfo("Europe/Berlin")

EMA_FAST = 20
EMA_SLOW = 50
ATR_LEN = 14
VOL_MA_LEN = 20
RR = 2.0

NEAR_EMA_PCT = 0.005
BREAKOUT_BUFFER_ATR = 0.15
DIP_BUFFER_ATR = 0.10
TREND_STRENGTH_MIN = 0.0025

last_alerts = {}

# =========================
# TELEGRAM
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
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code != 200:
            print("Telegram API error:", response.status_code, response.text)
    except Exception as e:
        print("Telegram error:", e)

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
    df["LOW_5"] = df["Low"].shift(1).rolling(5).min()

    return df.dropna()

# =========================
# HELPERS
# =========================
def fmt(x: float) -> str:
    if x >= 10:
        return f"{x:.2f}"
    return f"{x:.4f}"

def safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0

def get_quality(score: int) -> str:
    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return "LOW"

def make_key(name: str, df: pd.DataFrame) -> str:
    return f"{name}_{df.index[-1]}"

# =========================
# ANALYSIS
# =========================
def analyze(name: str, info: dict) -> str | None:
    df = get_data(info["yf"])
    if df.empty or len(df) < 80:
        return None

    df = add_indicators(df)
    if df.empty or len(df) < 30:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = safe_float(last["Close"])
    open_ = safe_float(last["Open"])
    high = safe_float(last["High"])
    ema20 = safe_float(last["EMA20"])
    ema50 = safe_float(last["EMA50"])
    atr = safe_float(last["ATR"])
    vol = safe_float(last["Volume"])
    vol_ma = safe_float(last["VOL_MA"])
    hh10 = safe_float(last["HH_10"])
    low5 = safe_float(last["LOW_5"])

    prev_close = safe_float(prev["Close"])
    prev_ema20 = safe_float(prev["EMA20"])

    if atr <= 0 or close <= 0:
        return None

    trend_bull = close > ema20 > ema50
    above_ema50 = close > ema50
    near_ema20 = abs(close - ema20) / close <= NEAR_EMA_PCT
    strong_trend = (ema20 - ema50) / close > TREND_STRENGTH_MIN
    green_candle = close > open_
    volume_ok = vol > vol_ma if vol_ma > 0 else False

    breakout_ready = close > hh10 if hh10 > 0 else False
    pullback_ok = above_ema50 and prev_close <= prev_ema20 * 1.003 and close >= ema20

    score = 0
    if trend_bull:
        score += 1
    if strong_trend:
        score += 1
    if above_ema50:
        score += 1
    if volume_ok:
        score += 1
    if green_candle:
        score += 1
    if breakout_ready or pullback_ok or near_ema20:
        score += 1

    quality = get_quality(score)

    candle_key = make_key(name, df)
    if last_alerts.get(name) == candle_key:
        return None

    if quality == "LOW":
        return None

    # HOLD / MANAGE pentru prioritare deja deținute
    if info["priority"] and above_ema50 and not breakout_ready and not pullback_ok:
        msg = (
            f"🟡 {name}\n\n"
            f"Status: HOLD / MANAGE\n"
            f"Trend: {'bullish' if trend_bull else 'mixed'}\n\n"
            f"Price: {fmt(close)}\n"
            f"EMA20: {fmt(ema20)}\n"
            f"EMA50: {fmt(ema50)}\n"
            f"ATR: {fmt(atr)}\n\n"
            f"Acțiune:\n"
            f"• nu adăuga acum\n"
            f"• păstrează doar cât timp stă peste EMA50\n"
            f"• urmărește breakout sau dip mai curat\n\n"
            f"Calitate: {quality}"
        )
        last_alerts[name] = candle_key
        return msg

    # BUY THE DIP
    if trend_bull and pullback_ok:
        entry = ema20 + DIP_BUFFER_ATR * atr
        sl = min(low5, ema50 - 0.25 * atr, entry - 1.2 * atr)
        if entry <= sl:
            return None
        tp = entry + RR * (entry - sl)

        msg = (
            f"🟢 {name}\n\n"
            f"Setup: BUY THE DIP\n"
            f"Trend: bullish\n\n"
            f"Price: {fmt(close)}\n\n"
            f"Plan:\n"
            f"• Buy Limit: {fmt(entry)}\n"
            f"• SL: {fmt(sl)}\n"
            f"• TP: {fmt(tp)}\n\n"
            f"EMA20: {fmt(ema20)}\n"
            f"EMA50: {fmt(ema50)}\n"
            f"ATR: {fmt(atr)}\n\n"
            f"Calitate: {quality}"
        )
        last_alerts[name] = candle_key
        return msg

    # BREAKOUT
    if trend_bull and hh10 > 0 and close >= ema20:
        entry = hh10 + BREAKOUT_BUFFER_ATR * atr
        sl = min(low5, entry - 1.25 * atr)
        if entry <= sl:
            return None
        tp = entry + RR * (entry - sl)

        msg = (
            f"🚀 {name}\n\n"
            f"Setup: BREAKOUT\n"
            f"Trend: bullish\n\n"
            f"Price: {fmt(close)}\n\n"
            f"Plan:\n"
            f"• Buy Stop: {fmt(entry)}\n"
            f"• SL: {fmt(sl)}\n"
            f"• TP: {fmt(tp)}\n\n"
            f"HH10: {fmt(hh10)}\n"
            f"EMA20: {fmt(ema20)}\n"
            f"EMA50: {fmt(ema50)}\n"
            f"ATR: {fmt(atr)}\n\n"
            f"Calitate: {quality}"
        )
        last_alerts[name] = candle_key
        return msg

    # WATCHLIST
    entry_watch = hh10 + BREAKOUT_BUFFER_ATR * atr if hh10 > 0 else close
    msg = (
        f"👀 {name}\n\n"
        f"Status: WATCHLIST\n"
        f"Trend: {'bullish' if trend_bull else 'mixed'}\n\n"
        f"Price: {fmt(close)}\n"
        f"EMA20: {fmt(ema20)}\n"
        f"EMA50: {fmt(ema50)}\n"
        f"ATR: {fmt(atr)}\n\n"
        f"Așteaptă:\n"
        f"• dip spre EMA20\n"
        f"• sau breakout peste {fmt(entry_watch)}\n\n"
        f"Calitate: {quality}"
    )
    last_alerts[name] = candle_key
    return msg

# =========================
# MAIN LOOP
# =========================
def run():
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ BOT_TOKEN sau CHAT_ID nu sunt setate.")
        return

    send_telegram(
        "✅ SAFE BOT v3 pornit\n"
        "Moduri active:\n"
        "• BUY THE DIP\n"
        "• BREAKOUT\n"
        "• HOLD / MANAGE\n"
        "• WATCHLIST"
    )
    print("Bot rulează...")

    ordered_items = sorted(
        SYMBOLS.items(),
        key=lambda x: (not x[1]["priority"], x[0])
    )

    while True:
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Scan...")

        for name, info in ordered_items:
            try:
                msg = analyze(name, info)
                if msg:
                    send_telegram(msg)
                    print("Alert:", name)
            except Exception as e:
                print(f"Error on {name}: {e}")

        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    run()
