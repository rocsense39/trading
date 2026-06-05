"""
Bot_AI_Infra_Watch V1.1
Google Colab / GitHub Actions + Telegram alert bot pentru:
MES, IUHC, GNOM, BOTZ, COPX, XLUS, SGLN/IGLN/IAUP.

Botul NU cumpara automat. Trimite doar alerte si planuri orientative.
"""

import html
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

CONFIG_PATH = Path("config_ai_infra_watch.json")
STATE_PATH = Path("bot_ai_infra_state.json")
MKT_TZ = ZoneInfo("Europe/Berlin")

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 100
EMA_LONG = 200
ATR_LEN = 14
VOL_MA_LEN = 20

DEFAULT_CONFIG = {
    "settings": {
        "sleep_seconds": 900,
        "min_alert_interval_hours": 4,
        "timeframes": {"primary_interval": "4h", "secondary_interval": "1h", "period": "6mo"},
        "risk": {"min_rr": 2.0, "extended_atr_multiple": 1.5}
    },
    "symbols": {
        "MES": {"enabled": True, "yf_symbol": "MES=F", "tv_symbol": "CME_MINI:MES1!", "label": "Micro E-mini S&P 500 Futures", "currency": "USD", "preferred_timeframe": "4h"},
        "IUHC": {"enabled": True, "yf_symbol": "IUHC.L", "tv_symbol": "LSE:IUHC", "label": "iShares S&P 500 Health Care Sector UCITS ETF", "currency": "USD", "preferred_timeframe": "4h"},
        "GNOM": {"enabled": True, "yf_symbol": "GNOM.L", "tv_symbol": "LSE:GNOM", "label": "Global X Genomics & Biotechnology UCITS ETF", "currency": "USD", "preferred_timeframe": "4h"},
        "BOTZ": {"enabled": True, "yf_symbol": "BOTZ.L", "tv_symbol": "LSE:BOTZ", "label": "Global X Robotics & Artificial Intelligence UCITS ETF", "currency": "USD", "preferred_timeframe": "4h"},
        "COPX": {"enabled": True, "yf_symbol": "COPX.L", "tv_symbol": "LSE:COPX", "label": "Global X Copper Miners UCITS ETF", "currency": "USD", "preferred_timeframe": "4h", "fallback_yf_symbols": ["COPX"]},
        "XLUS": {"enabled": True, "yf_symbol": "XLUS.L", "tv_symbol": "LSE:XLUS", "label": "Invesco Utilities S&P US Select Sector UCITS ETF", "currency": "USD", "preferred_timeframe": "4h"},
        "SGLN": {"enabled": True, "yf_symbol": "SGLN.L", "tv_symbol": "LSE:SGLN", "label": "iShares Physical Gold ETC", "currency": "USD", "preferred_timeframe": "4h", "fallback_yf_symbols": ["IGLN.L", "IAUP.L"]}
    },
    "regime_symbols": {"sp500": "SPY", "nasdaq": "QQQ", "vix": "^VIX", "copper": "HG=F", "gold": "GC=F"}
}


def create_default_config_if_missing() -> None:
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        print(f"Created default config: {CONFIG_PATH}")


def load_config() -> dict:
    create_default_config_if_missing()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"alerts": {}}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return {"alerts": {}}
        state.setdefault("alerts", {})
        return state
    except Exception:
        return {"alerts": {}}


def save_state(state: dict) -> None:
    state.setdefault("alerts", {})
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def telegram_html(message: str) -> str:
    # Escapam orice < sau > din text, dar pastram tagurile simple <b>...</b>.
    safe = html.escape(message, quote=False)
    return safe.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
    if not token or not chat_id:
        print("Telegram TOKEN/CHAT_ID lipsă. Mesaj:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": telegram_html(message), "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code >= 400:
            print(f"Telegram HTTP {r.status_code}: {r.text[:500]}")
    except Exception as e:
        print(f"Telegram error: {e}")


def get_data(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception as e:
        print(f"Download error {symbol}: {e}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title).copy()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert(MKT_TZ)
        else:
            df.index = df.index.tz_convert(MKT_TZ)
    except Exception:
        pass
    return df


def get_data_with_fallback(meta: dict, period: str, interval: str) -> tuple[pd.DataFrame, str]:
    for sym in [meta.get("yf_symbol")] + meta.get("fallback_yf_symbols", []):
        if not sym:
            continue
        df = get_data(sym, period, interval)
        if not df.empty:
            return df, sym
    return pd.DataFrame(), meta.get("yf_symbol", "n/a")


def drop_incomplete_candle(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if df.empty or len(df) < 3:
        return df
    if interval.endswith("h"):
        try:
            hours = int(interval[:-1])
            now = datetime.now(MKT_TZ)
            last_ts = df.index[-1]
            if (now - last_ts).total_seconds() < hours * 3600:
                return df.iloc[:-1].copy()
        except Exception:
            return df
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["EMA100"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=EMA_LONG, adjust=False).mean()
    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(ATR_LEN).mean()
    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_LEN).mean()
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    return df.dropna().copy()


def fmt(x: float) -> str:
    try:
        x = float(x)
    except Exception:
        return "n/a"
    if math.isnan(x):
        return "n/a"
    if abs(x) >= 100:
        return f"{x:.2f}"
    if abs(x) >= 10:
        return f"{x:.3f}"
    return f"{x:.4f}"


def alert_once(state: dict, key: str, min_hours: int) -> bool:
    now_ts = pd.Timestamp.now(tz=MKT_TZ)
    last = state.setdefault("alerts", {}).get(key)
    if last:
        try:
            diff_hours = (now_ts - pd.Timestamp(last)).total_seconds() / 3600
            if diff_hours < min_hours:
                return False
        except Exception:
            pass
    state["alerts"][key] = now_ts.isoformat()
    save_state(state)
    return True


def classify_regime(config: dict) -> tuple[str, str]:
    syms = config.get("regime_symbols", {})
    score = 0
    details = []
    for label, sym in [("S&P", syms.get("sp500", "SPY")), ("Nasdaq", syms.get("nasdaq", "QQQ"))]:
        df = get_data(sym, "6mo", "1d")
        if df.empty or len(df) < 80:
            details.append(f"{label}: n/a")
            continue
        df = add_indicators(df)
        last = df.iloc[-1]
        c, e20, e50 = float(last["Close"]), float(last["EMA20"]), float(last["EMA50"])
        if c > e20 > e50:
            score += 1
            details.append(f"{label}: bullish")
        elif c < e50:
            score -= 1
            details.append(f"{label}: weak")
        else:
            details.append(f"{label}: neutral")
    vdf = get_data(syms.get("vix", "^VIX"), "3mo", "1d")
    if not vdf.empty:
        v = float(vdf.iloc[-1]["Close"])
        if v < 18:
            score += 1
            details.append(f"VIX: calm {fmt(v)}")
        elif v > 25:
            score -= 1
            details.append(f"VIX: high {fmt(v)}")
        else:
            details.append(f"VIX: neutral {fmt(v)}")
    if score >= 2:
        return "RISK ON", "; ".join(details)
    if score <= -1:
        return "RISK OFF", "; ".join(details)
    return "NEUTRAL", "; ".join(details)


def analyze_symbol(name: str, meta: dict, config: dict, state: dict, regime: str, regime_details: str) -> list[str]:
    settings = config["settings"]
    tf = meta.get("preferred_timeframe") or settings["timeframes"]["primary_interval"]
    period = settings["timeframes"]["period"]
    min_hours = int(settings.get("min_alert_interval_hours", 4))
    min_rr = float(settings.get("risk", {}).get("min_rr", 2.0))
    extended_mult = float(settings.get("risk", {}).get("extended_atr_multiple", 1.5))

    df, yf_used = get_data_with_fallback(meta, period, tf)
    df = drop_incomplete_candle(df, tf)
    if df.empty or len(df) < 220:
        return [f"⚠️ <b>{name}</b>: date insuficiente pentru {meta.get('yf_symbol')} pe {tf}. Verifică tickerul Yahoo Finance."]
    df = add_indicators(df)
    if df.empty:
        return []

    last, prev = df.iloc[-1], df.iloc[-2]
    close_ = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema100 = float(last["EMA100"])
    ema200 = float(last["EMA200"])
    atr = float(last["ATR"])
    vol = float(last["Volume"])
    vol_ma = float(last["VOL_MA"])
    hh20 = float(last["HH20"])

    trend_perfect = close_ > ema20 > ema50 > ema100 > ema200
    trend_ok = close_ > ema20 and close_ > ema50 and ema20 > ema50
    pullback_ema20 = trend_ok and abs(close_ - ema20) <= 0.6 * atr and close_ >= ema20
    pullback_ema50 = close_ > ema100 and abs(close_ - ema50) <= 0.8 * atr
    breakout = close_ > hh20 and float(prev["Close"]) <= float(prev["HH20"])
    volume_confirm = vol_ma > 0 and vol > 1.25 * vol_ma
    extended = trend_ok and close_ > ema20 + extended_mult * atr
    risk_warning = close_ < ema50 or ema20 < ema50

    messages = []

    if trend_perfect and alert_once(state, f"{name}:{tf}:TREND_PERFECT", min_hours):
        messages.append(
            f"✅ <b>{name} — TREND CURAT</b>\n"
            f"{meta['label']} | TV: <b>{meta.get('tv_symbol','')}</b> | Yahoo: <b>{yf_used}</b>\n"
            f"TF: <b>{tf}</b> | Regime: <b>{regime}</b>\n"
            f"Preț: <b>{fmt(close_)}</b>\n"
            f"EMA20/50/100/200: {fmt(ema20)} / {fmt(ema50)} / {fmt(ema100)} / {fmt(ema200)}\n"
            f"ATR{ATR_LEN}: <b>{fmt(atr)}</b>\n"
            f"Observație: trend bullish, dar nu cumpăra fără pullback/retest."
        )

    if breakout and (volume_confirm or close_ > ema20):
        key = f"{name}:{tf}:BREAKOUT:{round(hh20, 2)}"
        if alert_once(state, key, min_hours):
            retest_entry = max(ema20, hh20 - 0.20 * atr)
            sl = retest_entry - atr
            tp = retest_entry + min_rr * (retest_entry - sl)
            messages.append(
                f"🚀 <b>{name} — BREAKOUT, AȘTEAPTĂ RETEST</b>\n"
                f"{meta['label']} | TF: <b>{tf}</b>\n"
                f"Preț: <b>{fmt(close_)}</b> | HH20 spart: {fmt(hh20)}\n"
                f"Volum: {vol:.0f} vs medie {vol_ma:.0f}\n"
                f"Plan orientativ:\n"
                f"• Buy Limit retest: <b>{fmt(retest_entry)}</b>\n"
                f"• SL: <b>{fmt(sl)}</b>\n"
                f"• TP 2R: <b>{fmt(tp)}</b>\n"
                f"Regulă: nu chase după lumânare explozivă."
            )

    if pullback_ema20:
        entry = min(close_, ema20 + 0.20 * atr)
        sl = entry - atr
        tp = entry + min_rr * (entry - sl)
        key = f"{name}:{tf}:PULLBACK_EMA20:{round(entry, 2)}"
        if alert_once(state, key, min_hours):
            messages.append(
                f"🟢 <b>{name} — PULLBACK EMA20</b>\n"
                f"{meta['label']} | TF: <b>{tf}</b>\n"
                f"Preț: {fmt(close_)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)} | ATR: {fmt(atr)}\n"
                f"Plan 2R:\n"
                f"• Buy Limit: <b>{fmt(entry)}</b>\n"
                f"• SL: <b>{fmt(sl)}</b>\n"
                f"• TP: <b>{fmt(tp)}</b>\n"
                f"Status: setup în direcția trendului."
            )

    if pullback_ema50:
        entry = min(close_, ema50 + 0.20 * atr)
        sl = entry - atr
        tp = entry + min_rr * (entry - sl)
        key = f"{name}:{tf}:PULLBACK_EMA50:{round(entry, 2)}"
        if alert_once(state, key, min_hours):
            messages.append(
                f"🟢🟢 <b>{name} — PULLBACK EMA50</b>\n"
                f"{meta['label']} | TF: <b>{tf}</b>\n"
                f"Preț: {fmt(close_)} | EMA50: <b>{fmt(ema50)}</b> | EMA100: {fmt(ema100)} | ATR: {fmt(atr)}\n"
                f"Plan 2R:\n"
                f"• Buy Limit: <b>{fmt(entry)}</b>\n"
                f"• SL: <b>{fmt(sl)}</b>\n"
                f"• TP: <b>{fmt(tp)}</b>\n"
                f"Status: dip mai adânc, dar încă tehnic."
            )

    if extended and alert_once(state, f"{name}:{tf}:EXTENDED", min_hours):
        ema20_entry = ema20 + 0.15 * atr
        ema50_entry = ema50 + 0.20 * atr
        messages.append(
            f"🟡 <b>{name} — PREȚ EXTINS, NU CHASE</b>\n"
            f"{meta['label']} | TF: <b>{tf}</b>\n"
            f"Preț: <b>{fmt(close_)}</b> | EMA20: {fmt(ema20)} | ATR: {fmt(atr)}\n"
            f"Zone de urmărit:\n"
            f"• Pullback EMA20: <b>{fmt(ema20_entry)}</b>\n"
            f"• Pullback EMA50: <b>{fmt(ema50_entry)}</b>\n"
            f"Regulă: intrare doar pe retragere sau retest confirmat."
        )

    if risk_warning and alert_once(state, f"{name}:{tf}:RISK_WARNING", min_hours):
        messages.append(
            f"🔴 <b>{name} — PRUDENȚĂ</b>\n"
            f"{meta['label']} | TF: <b>{tf}</b>\n"
            f"Preț: {fmt(close_)} | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
            f"Condiție: preț sub EMA50 sau EMA20 < EMA50.\n"
            f"Acțiune: nu adăuga până nu revine peste medii și confirmă."
        )

    return messages


def send_startup(config: dict) -> None:
    enabled = [name for name, meta in config.get("symbols", {}).items() if meta.get("enabled", True)]
    msg = (
        "✅ <b>Bot_AI_Infra_Watch V1.1 a pornit.</b>\n"
        "Instrumente urmărite: <b>" + ", ".join(enabled) + "</b>\n"
        "Regulă: botul trimite alerte și planuri; nu cumpără automat."
    )
    send_telegram(msg)


def run_once(config: dict, state: dict) -> None:
    regime, regime_details = classify_regime(config)
    print(f"Market regime: {regime} | {regime_details}")
    for name, meta in config.get("symbols", {}).items():
        if not meta.get("enabled", True):
            continue
        try:
            for msg in analyze_symbol(name, meta, config, state, regime, regime_details):
                send_telegram(msg)
                print(f"Alert sent: {name}")
        except Exception as e:
            print(f"Error {name}: {e}")


def run() -> None:
    config = load_config()
    state = load_state()
    send_startup(config)
    while True:
        now = datetime.now(MKT_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{now}] Bot_AI_Infra_Watch scan...")
        config = load_config()
        state = load_state()
        run_once(config, state)
        time.sleep(int(config.get("settings", {}).get("sleep_seconds", 900)))


if __name__ == "__main__":
    run()
