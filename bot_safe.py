"""
DCA + Swing Alert Bot pentru Google Colab
Strategie:
1) ETF core / DCA oportunist: SXR8, SXRV, XXME, H411
   - nu cumpără automat; trimite alerte pentru Buy Limit zones
   - folosește trend, EMA20/EMA50, ATR și retrageri procentuale
2) Swing satelit: AAOI, AIFS etc.
   - alerte pentru breakout, pullback și invalidare
   - sizing limitat la 1-5% din portofoliu
3) Aur: alertă opțională când trendul devine favorabil sau apare pullback sănătos

IMPORTANT:
- Nu pune token-ul Telegram direct în cod public.
- În Colab folosește variabile de mediu sau Colab Secrets.
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# =========================
# CONFIG GENERAL
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN", "PASTE_TOKEN_HERE")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PASTE_CHAT_ID_HERE")

MKT_TZ = ZoneInfo("Europe/Berlin")
INTERVAL = "1h"
PERIOD = "6mo"
SLEEP_SECONDS = 900

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 150
ATR_LEN = 20
VOL_MA_LEN = 20

# Buget lunar pentru ETF-uri. Modifică lunar manual.
MONTHLY_ETF_BUDGET_RON = 500

# Nu recomand să riști mai mult de 1-5% capital pe swing-uri speculative.
MAX_SWING_ALLOCATION_PCT = 5

# Pentru DCA oportunist: botul sugerează zone, nu cumpărare market.
DCA_LEVELS = {
    "shallow": 0.236,
    "normal": 0.382,
    "deep": 0.500,
}

# =========================
# WATCHLIST
# =========================
SYMBOLS = {
    # ETF CORE
    "SXR8": {
        "type": "ETF_CORE",
        "xtb_symbol": "SXR8.DE",
        "yf_symbol": "SXR8.DE",
        "label": "iShares Core S&P 500 UCITS ETF",
        "target_weight": 0.45,
    },
    "SXRV": {
        "type": "ETF_CORE",
        "xtb_symbol": "SXRV.DE",
        "yf_symbol": "SXRV.DE",
        "label": "iShares Nasdaq 100 UCITS ETF",
        "target_weight": 0.30,
    },
    "XXME": {
        "type": "ETF_CORE",
        "xtb_symbol": "XXME.DE",
        "yf_symbol": "XXME.DE",
        "label": "MSCI Emerging Markets / EM ETF",
        "target_weight": 0.15,
    },
    "H411": {
        "type": "ETF_CORE",
        "xtb_symbol": "H411.DE",
        "yf_symbol": "H411.DE",
        "label": "ETF tematic / sectorial H411",
        "target_weight": 0.10,
    },

    # SWING SATELIT
    "AAOI": {
        "type": "SWING",
        "xtb_symbol": "AAOI.US",
        "yf_symbol": "AAOI",
        "label": "Applied Optoelectronics",
        "max_allocation_pct": 5,
    },
    "AIFS": {
        "type": "SWING",
        "xtb_symbol": "AIFS.US",
        "yf_symbol": "AIFS",
        "label": "AIFS",
        "max_allocation_pct": 3,
    },

    # AUR, activat pentru mai târziu
    "SGLD": {
        "type": "GOLD",
        "xtb_symbol": "SGLD.UK",
        "yf_symbol": "SGLD.L",
        "label": "Physical Gold ETC",
        "target_weight": 0.00,
    },
}

last_alerts: dict[str, str] = {}


# =========================
# TELEGRAM
# =========================
def send_telegram(message: str) -> None:
    if not TOKEN or TOKEN == "PASTE_TOKEN_HERE":
        print("Telegram TOKEN lipsă. Mesaj:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")


# =========================
# DATA + INDICATORI
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
    df["EMA50"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(ATR_LEN).mean()

    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_LEN).mean()
    df["HH_20_PREV"] = df["High"].shift(1).rolling(20).max()
    df["LL_20_PREV"] = df["Low"].shift(1).rolling(20).min()

    # swing recent pentru fib / DCA zones
    df["SWING_HIGH_60"] = df["High"].rolling(60).max()
    df["SWING_LOW_60"] = df["Low"].rolling(60).min()

    return df.dropna().copy()


# =========================
# UTILS
# =========================
def fmt(x: float) -> str:
    if x >= 100:
        return f"{x:.2f}"
    if x >= 10:
        return f"{x:.2f}"
    return f"{x:.4f}"


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0


def alert_once(name: str, candle_time: str, setup: str) -> bool:
    key = f"{name}_{setup}_{candle_time}"
    if last_alerts.get(f"{name}_{setup}") == key:
        return False
    last_alerts[f"{name}_{setup}"] = key
    return True


def fib_buy_zones(swing_low: float, swing_high: float) -> dict[str, float]:
    move = swing_high - swing_low
    return {
        "Buy Limit 23.6% - dip superficial": swing_high - 0.236 * move,
        "Buy Limit 38.2% - dip normal": swing_high - 0.382 * move,
        "Buy Limit 50.0% - dip adânc": swing_high - 0.500 * move,
    }


# =========================
# ETF DCA LOGIC
# =========================
def analyze_etf_core(name: str, meta: dict, df: pd.DataFrame) -> list[str]:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    candle_time = df.index[-1].isoformat()

    close_ = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema150 = float(last["EMA150"])
    atr = float(last["ATR"])
    swing_high = float(last["SWING_HIGH_60"])
    swing_low = float(last["SWING_LOW_60"])

    trend_bull = close_ > ema20 > ema50 > ema150
    long_trend_ok = close_ > ema50 > ema150
    extended = close_ > ema20 + 1.2 * atr
    near_ema20 = abs(close_ - ema20) <= 0.6 * atr
    near_ema50 = abs(close_ - ema50) <= 0.8 * atr
    pullback_to_ema20 = last["Low"] <= ema20 <= last["High"] or near_ema20
    pullback_to_ema50 = last["Low"] <= ema50 <= last["High"] or near_ema50

    zones = fib_buy_zones(swing_low, swing_high)
    monthly_part_ron = MONTHLY_ETF_BUDGET_RON * float(meta.get("target_weight", 0))

    messages = []

    # 1) Piață prea extinsă: nu chase, doar propune buy limits
    if trend_bull and extended:
        setup = "ETF_EXTENDED_SET_LIMITS"
        if alert_once(name, candle_time, setup):
            zone_text = "\n".join([f"• {k}: <b>{fmt(v)}</b>" for k, v in zones.items()])
            msg = (
                f"🟡 <b>{meta['label']}</b> — DCA oportunist\n"
                f"XTB: <b>{meta['xtb_symbol']}</b> | Yahoo: <b>{meta['yf_symbol']}</b>\n"
                f"Setup: <b>Trend bullish, dar preț extins</b>\n"
                f"Preț: <b>{fmt(close_)}</b> | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"ATR: {fmt(atr)}\n\n"
                f"Nu chase market. Pune/menține Buy Limit-uri:\n{zone_text}\n\n"
                f"Alocare lunară orientativă pentru acest ETF: <b>{monthly_part_ron:.0f} RON</b>"
            )
            messages.append(msg)

    # 2) Pullback sănătos la EMA20 în trend bullish
    if long_trend_ok and pullback_to_ema20 and close_ >= ema20:
        setup = "ETF_BUY_LIMIT_EMA20"
        if alert_once(name, candle_time, setup):
            buy_limit = min(close_, ema20 + 0.15 * atr)
            protective_level = ema50 - 0.8 * atr
            msg = (
                f"🟢 <b>{meta['label']}</b> — DCA entry posibil\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Setup: <b>Pullback la EMA20 în trend bullish</b>\n"
                f"Preț: {fmt(close_)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n"
                f"Sugestie Buy Limit: <b>{fmt(buy_limit)}</b>\n"
                f"Nivel de invalidare tehnică: sub {fmt(protective_level)}\n"
                f"Alocare orientativă: <b>{monthly_part_ron:.0f} RON</b>"
            )
            messages.append(msg)

    # 3) Pullback mai bun la EMA50 / dip normal
    if close_ > ema150 and pullback_to_ema50:
        setup = "ETF_BUY_LIMIT_EMA50"
        if alert_once(name, candle_time, setup):
            buy_limit = min(close_, ema50 + 0.2 * atr)
            msg = (
                f"🟢🟢 <b>{meta['label']}</b> — DCA zonă mai bună\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Setup: <b>Pullback la EMA50 / dip normal</b>\n"
                f"Preț: {fmt(close_)} | EMA50: <b>{fmt(ema50)}</b> | EMA150: {fmt(ema150)}\n"
                f"Sugestie Buy Limit: <b>{fmt(buy_limit)}</b>\n"
                f"Alocare orientativă: <b>{monthly_part_ron:.0f} RON</b>"
            )
            messages.append(msg)

    # 4) Atenționare: trend slăbit, nu adăuga agresiv
    if close_ < ema50 and ema20 < ema50:
        setup = "ETF_RISK_OFF"
        if alert_once(name, candle_time, setup):
            msg = (
                f"🔴 <b>{meta['label']}</b> — DCA cu prudență\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Preț sub EMA50 și EMA20 < EMA50.\n"
                f"Preț: {fmt(close_)} | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Nu mări agresiv expunerea. Așteaptă stabilizare sau cumpără doar tranșe mici."
            )
            messages.append(msg)

    return messages


# =========================
# SWING LOGIC
# =========================
def analyze_swing(name: str, meta: dict, df: pd.DataFrame) -> list[str]:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    candle_time = df.index[-1].isoformat()

    close_ = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema150 = float(last["EMA150"])
    atr = float(last["ATR"])
    vol = float(last["Volume"])
    vol_ma = float(last["VOL_MA"])
    hh20 = float(last["HH_20_PREV"])
    ll20 = float(last["LL_20_PREV"])

    trend_bull = close_ > ema20 > ema50
    volume_ok = vol > 1.2 * vol_ma if vol_ma > 0 else False
    breakout = close_ > hh20 and trend_bull
    pullback = trend_bull and abs(close_ - ema20) <= 0.8 * atr
    invalidation = close_ < ema50 or close_ < ll20

    max_alloc = float(meta.get("max_allocation_pct", MAX_SWING_ALLOCATION_PCT))
    messages = []

    if breakout and (volume_ok or atr > float(prev["ATR"])):
        setup = "SWING_BREAKOUT"
        if alert_once(name, candle_time, setup):
            entry = close_ + 0.1 * atr
            sl = max(ema20 - 1.2 * atr, close_ - 2.0 * atr)
            risk = entry - sl
            tp1 = entry + 1.5 * risk
            tp2 = entry + 2.5 * risk
            msg = (
                f"🚀 <b>{meta['label']}</b> — Swing breakout\n"
                f"XTB: <b>{meta['xtb_symbol']}</b> | Yahoo: <b>{meta['yf_symbol']}</b>\n"
                f"Preț: {fmt(close_)} | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Volum: {vol:.0f} vs medie {vol_ma:.0f}\n\n"
                f"Plan orientativ:\n"
                f"• Buy Stop: <b>{fmt(entry)}</b>\n"
                f"• Sell Stop: <b>{fmt(sl)}</b>\n"
                f"• TP1: {fmt(tp1)} | TP2: {fmt(tp2)}\n"
                f"• Max alocare: <b>{max_alloc:.1f}% din portofoliu</b>"
            )
            messages.append(msg)

    if pullback:
        setup = "SWING_PULLBACK"
        if alert_once(name, candle_time, setup):
            entry = min(close_, ema20 + 0.2 * atr)
            sl = ema50 - 1.0 * atr
            risk = entry - sl
            tp1 = entry + 1.5 * risk
            tp2 = entry + 2.5 * risk
            msg = (
                f"🟢 <b>{meta['label']}</b> — Swing pullback\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Setup: trend bullish + revenire la EMA20\n"
                f"Preț: {fmt(close_)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n\n"
                f"Plan orientativ:\n"
                f"• Buy Limit: <b>{fmt(entry)}</b>\n"
                f"• Sell Stop: <b>{fmt(sl)}</b>\n"
                f"• TP1: {fmt(tp1)} | TP2: {fmt(tp2)}\n"
                f"• Max alocare: <b>{max_alloc:.1f}%</b>"
            )
            messages.append(msg)

    if invalidation:
        setup = "SWING_INVALIDATION"
        if alert_once(name, candle_time, setup):
            msg = (
                f"🔴 <b>{meta['label']}</b> — Atenție swing\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Preț: {fmt(close_)} | EMA50: {fmt(ema50)} | LL20: {fmt(ll20)}\n"
                f"Setup-ul bullish este slăbit. Evită add / verifică stop-ul."
            )
            messages.append(msg)

    return messages


# =========================
# GOLD LOGIC
# =========================
def analyze_gold(name: str, meta: dict, df: pd.DataFrame) -> list[str]:
    last = df.iloc[-1]
    candle_time = df.index[-1].isoformat()

    close_ = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    atr = float(last["ATR"])

    trend_bull = close_ > ema20 > ema50
    pullback_ok = abs(close_ - ema20) <= 0.7 * atr
    messages = []

    if trend_bull and pullback_ok:
        setup = "GOLD_PULLBACK"
        if alert_once(name, candle_time, setup):
            buy_limit = min(close_, ema20 + 0.2 * atr)
            msg = (
                f"🟡 <b>{meta['label']}</b> — Aur watchlist\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Trend bullish + pullback la EMA20.\n"
                f"Preț: {fmt(close_)} | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Buy Limit orientativ: <b>{fmt(buy_limit)}</b>\n"
                f"Folosește doar după ce decizi o alocare clară pentru aur."
            )
            messages.append(msg)

    return messages


# =========================
# MAIN ANALYSIS
# =========================
def analyze_symbol(name: str, meta: dict) -> list[str]:
    df = get_data(meta["yf_symbol"])
    if df.empty or len(df) < 180:
        return []

    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 180:
        return []

    df = add_indicators(df)
    if df.empty or len(df) < 80:
        return []

    asset_type = meta["type"]
    if asset_type == "ETF_CORE":
        return analyze_etf_core(name, meta, df)
    if asset_type == "SWING":
        return analyze_swing(name, meta, df)
    if asset_type == "GOLD":
        return analyze_gold(name, meta, df)
    return []


def send_daily_plan() -> None:
    total = MONTHLY_ETF_BUDGET_RON
    lines = [
        "📌 <b>Plan lunar DCA ETF</b>",
        f"Buget lunar: <b>{total:.0f} RON</b>",
        "Alocare orientativă:",
    ]
    for name, meta in SYMBOLS.items():
        if meta["type"] != "ETF_CORE":
            continue
        weight = float(meta.get("target_weight", 0))
        lines.append(f"• {name}: {weight:.0%} = <b>{total * weight:.0f} RON</b>")

    lines.append("\nRegulă: nu cumpărăm automat în aceeași zi; așteptăm EMA20/EMA50 sau zone fib.")
    send_telegram("\n".join(lines))


def run() -> None:
    send_telegram("✅ Bot DCA ETF + Swing a pornit.")
    send_daily_plan()

    while True:
        now = datetime.now(MKT_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{now}] Scan...")

        for name, meta in SYMBOLS.items():
            try:
                messages = analyze_symbol(name, meta)
                for msg in messages:
                    send_telegram(msg)
                    print(f"Alert sent: {name}")
            except Exception as e:
                print(f"Error on {name}: {e}")

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    run()
