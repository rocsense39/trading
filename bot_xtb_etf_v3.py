"""
XTB ETF Bot V3.0 — Allocation + SL/TP Discipline
=================================================

Purpose:
- Telegram alert bot for an XTB ETF portfolio.
- No single stocks, no gold, no swing module.
- Portfolio-first logic: buy only when an ETF is under target allocation.
- Different SL/TP rules for core, quality, and satellite ETFs.
- Designed for semi-manual XTB workflow: the bot tells you exactly what to place.

Run in Colab:
    %cd /content/trading
    !python bot_xtb_etf_v3.py

Environment variables:
    TELEGRAM_TOKEN
    TELEGRAM_CHAT_ID

Files created/used:
    config_xtb_etf_v3.json
    bot_xtb_etf_v3_state.json

Important:
This bot does not send orders to XTB. It creates disciplined, actionable alerts.
You must confirm fills manually, then update state/config if needed.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

CONFIG_PATH = Path("config_xtb_etf_v3.json")
STATE_PATH = Path("bot_xtb_etf_v3_state.json")
MKT_TZ = ZoneInfo("Europe/Berlin")
INTERVAL = "1h"
PERIOD = "9mo"
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 150
ATR_LEN = 20
VOL_MA_LEN = 20

DEFAULT_CONFIG: dict[str, Any] = {
    "settings": {
        "sleep_seconds": 900,
        "equity_eur": 939.06,
        "free_cash_eur": 75.08,
        "cash_reserve_pct": 0.10,
        "min_order_eur": 25.0,
        "max_order_eur": 75.0,
        "one_new_entry_per_day": True,
        "min_alert_interval_hours": 6,
        "risk_mode": "balanced",
        "default_currency": "EUR",
        "eur_usd": 1.08,
        "eur_gbp": 0.86
    },
    "regime_symbols": {
        "sp500": "SPY",
        "nasdaq": "QQQ",
        "vix": "^VIX"
    },
    "portfolio": {
        "positions": {
            "SXR8": {"qty": 0.3000, "avg_price": 703.0, "currency": "EUR"},
            "SXRV": {"qty": 0.1955, "avg_price": 1465.0, "currency": "EUR"},
            "QUALITY": {"qty": 0.0, "avg_price": 0.0, "currency": "EUR"},
            "AIINFRA": {"qty": 0.0, "avg_price": 0.0, "currency": "EUR"},
            "GINFRA": {"qty": 0.0, "avg_price": 0.0, "currency": "EUR"},
            "XMME": {"qty": 0.5, "avg_price": 80.5, "currency": "EUR"},
            "H411": {"qty": 1.4, "avg_price": 78.5, "currency": "EUR"}
        }
    },
    "etfs": {
        "SXR8": {
            "enabled": True,
            "sleeve": "core",
            "xtb_symbol": "SXR8.DE",
            "yf_symbol": "SXR8.DE",
            "label": "iShares Core S&P 500 UCITS ETF",
            "target_weight": 0.45,
            "currency": "EUR"
        },
        "SXRV": {
            "enabled": True,
            "sleeve": "core_growth",
            "xtb_symbol": "SXRV.DE",
            "yf_symbol": "SXRV.DE",
            "label": "iShares Nasdaq 100 UCITS ETF",
            "target_weight": 0.25,
            "currency": "EUR"
        },
        "QUALITY": {
            "enabled": True,
            "sleeve": "quality",
            "xtb_symbol": "REPLACE_WITH_XTB_QUALITY_ETF",
            "yf_symbol": "IWQU.DE",
            "label": "Global Quality ETF — replace symbol if needed",
            "target_weight": 0.125,
            "currency": "EUR"
        },
        "AIINFRA": {
            "enabled": True,
            "sleeve": "satellite",
            "xtb_symbol": "REPLACE_WITH_XTB_AI_INFRA_ETF",
            "yf_symbol": "XAIX.DE",
            "label": "AI / Technology Infrastructure ETF — replace symbol if needed",
            "target_weight": 0.05,
            "currency": "EUR"
        },
        "GINFRA": {
            "enabled": True,
            "sleeve": "satellite",
            "xtb_symbol": "REPLACE_WITH_XTB_GLOBAL_INFRA_ETF",
            "yf_symbol": "IGLN.DE",
            "label": "Global Infrastructure ETF — replace symbol if needed",
            "target_weight": 0.025,
            "currency": "EUR"
        },
        "XMME": {
            "enabled": True,
            "sleeve": "satellite",
            "xtb_symbol": "XMME.DE",
            "yf_symbol": "XMME.DE",
            "label": "Emerging Markets ETF",
            "target_weight": 0.05,
            "currency": "EUR"
        },
        "H411": {
            "enabled": True,
            "sleeve": "satellite",
            "xtb_symbol": "H411.DE",
            "yf_symbol": "H411.DE",
            "label": "Far East / Asia ETF",
            "target_weight": 0.05,
            "currency": "EUR"
        }
    }
}


@dataclass
class MarketSnapshot:
    close: float
    high: float
    low: float
    ema20: float
    ema50: float
    ema150: float
    atr: float
    hh20: float
    ll20: float
    rsi14: float
    volume: float
    vol_ma: float


def write_default_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        print(f"Created {CONFIG_PATH}. Edit ETF symbols before production use.")


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default.copy()


def save_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    write_default_config()
    return load_json(CONFIG_PATH, DEFAULT_CONFIG)


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH, {"alerts": {}, "orders": {}, "daily_entry": {}})


def save_state(state: dict[str, Any]) -> None:
    save_json(STATE_PATH, state)


def clean_html(message: str) -> str:
    return re.sub(r"</?b>", "", message).replace("&lt;", "<").replace("&gt;", ">")


def send_telegram(message: str) -> bool:
    token = (os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("Telegram credentials missing. Message below:\n")
        print(clean_html(message))
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            return True
        r2 = requests.post(url, json={"chat_id": chat_id, "text": clean_html(message)}, timeout=15)
        return r2.status_code == 200
    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def get_data(symbol: str, period: str = PERIOD, interval: str = INTERVAL) -> pd.DataFrame:
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        print(f"Download failed for {symbol}: {exc}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)
    need = {"Open", "High", "Low", "Close", "Volume"}
    if not need.issubset(df.columns):
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
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
    if last_ts.year == now.year and last_ts.month == now.month and last_ts.day == now.day and last_ts.hour == now.hour:
        return df.iloc[:-1].copy()
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(ATR_LEN).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["RSI14"] = 100 - (100 / (1 + rs))
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_LEN).mean()
    return df.dropna().copy()


def snapshot(symbol: str) -> MarketSnapshot | None:
    df = add_indicators(drop_incomplete_candle(get_data(symbol)))
    if df.empty or len(df) < 160:
        return None
    last = df.iloc[-1]
    return MarketSnapshot(
        close=float(last["Close"]), high=float(last["High"]), low=float(last["Low"]),
        ema20=float(last["EMA20"]), ema50=float(last["EMA50"]), ema150=float(last["EMA150"]),
        atr=float(last["ATR"]), hh20=float(last["HH20"]), ll20=float(last["LL20"]),
        rsi14=float(last["RSI14"]), volume=float(last["Volume"]), vol_ma=float(last["VOL_MA"])
    )


def fmt(x: float) -> str:
    if x is None or math.isnan(float(x)):
        return "n/a"
    x = float(x)
    return f"{x:.2f}" if abs(x) >= 10 else f"{x:.4f}"


def fx_to_eur(config: dict[str, Any], currency: str) -> float:
    currency = currency.upper()
    if currency == "EUR":
        return 1.0
    if currency == "USD":
        return 1.0 / float(config["settings"].get("eur_usd", 1.08))
    if currency == "GBP":
        return 1.0 / float(config["settings"].get("eur_gbp", 0.86))
    return 1.0


def position_value_eur(config: dict[str, Any], symbol: str, price: float, currency: str) -> float:
    pos = config.get("portfolio", {}).get("positions", {}).get(symbol, {})
    qty = float(pos.get("qty", 0.0))
    return qty * price * fx_to_eur(config, currency)


def alert_once(state: dict[str, Any], key: str, min_hours: int) -> bool:
    now = pd.Timestamp.now(tz=MKT_TZ)
    last = state.setdefault("alerts", {}).get(key)
    if last:
        try:
            diff_h = (now - pd.Timestamp(last)).total_seconds() / 3600
            if diff_h < min_hours:
                return False
        except Exception:
            pass
    state["alerts"][key] = now.isoformat()
    save_state(state)
    return True


def daily_entry_allowed(config: dict[str, Any], state: dict[str, Any]) -> bool:
    if not config["settings"].get("one_new_entry_per_day", True):
        return True
    today = datetime.now(MKT_TZ).date().isoformat()
    return state.setdefault("daily_entry", {}).get("date") != today


def mark_daily_entry(state: dict[str, Any], symbol: str) -> None:
    today = datetime.now(MKT_TZ).date().isoformat()
    state["daily_entry"] = {"date": today, "symbol": symbol}
    save_state(state)


def classify_regime(config: dict[str, Any]) -> tuple[str, int, str]:
    symbols = config.get("regime_symbols", {})
    score = 50
    notes: list[str] = []
    for label, sym in [("S&P", symbols.get("sp500", "SPY")), ("Nasdaq", symbols.get("nasdaq", "QQQ"))]:
        df = add_indicators(get_data(sym, period="9mo", interval="1d"))
        if df.empty:
            notes.append(f"{label}: n/a")
            continue
        last = df.iloc[-1]
        close, ema20, ema50, ema150 = map(float, [last["Close"], last["EMA20"], last["EMA50"], last["EMA150"]])
        if close > ema20 > ema50 > ema150:
            score += 15
            notes.append(f"{label}: strong trend")
        elif close > ema50 > ema150:
            score += 8
            notes.append(f"{label}: positive")
        elif close < ema50:
            score -= 12
            notes.append(f"{label}: weak")
    vix_df = get_data(symbols.get("vix", "^VIX"), period="3mo", interval="1d")
    if not vix_df.empty:
        vix = float(vix_df.iloc[-1]["Close"])
        if vix < 18:
            score += 10
            notes.append(f"VIX calm {fmt(vix)}")
        elif vix > 25:
            score -= 20
            notes.append(f"VIX high {fmt(vix)}")
        else:
            notes.append(f"VIX neutral {fmt(vix)}")
    score = max(0, min(100, score))
    regime = "RISK ON" if score >= 70 else "RISK OFF" if score < 40 else "NEUTRAL"
    return regime, score, "; ".join(notes)


def build_portfolio_view(config: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], float]:
    view: dict[str, dict[str, Any]] = {}
    total = float(config["settings"].get("free_cash_eur", 0.0))
    for name, meta in config["etfs"].items():
        if not meta.get("enabled", True):
            continue
        snap = snapshot(meta["yf_symbol"])
        if snap is None:
            continue
        value = position_value_eur(config, name, snap.close, meta.get("currency", "EUR"))
        view[name] = {"meta": meta, "snap": snap, "value_eur": value}
        total += value
    if total <= 0:
        total = float(config["settings"].get("equity_eur", 0.0))
    for name, item in view.items():
        target = float(item["meta"].get("target_weight", 0.0))
        actual = item["value_eur"] / total if total else 0.0
        item["actual_weight"] = actual
        item["target_value_eur"] = target * total
        item["gap_eur"] = item["target_value_eur"] - item["value_eur"]
        item["gap_pct"] = target - actual
    return view, total


def can_buy(meta: dict[str, Any], snap: MarketSnapshot, regime: str) -> tuple[bool, str]:
    sleeve = meta.get("sleeve", "satellite")
    trend_ok = snap.close > snap.ema50 > snap.ema150
    core_ok = snap.close > snap.ema150
    if sleeve in {"core", "core_growth"}:
        if not core_ok:
            return False, "core blocked: price below EMA150"
        if regime == "RISK OFF" and snap.close < snap.ema50:
            return False, "core blocked: risk-off and below EMA50"
        return True, "core allowed"
    if sleeve == "quality":
        if snap.close < snap.ema150 and regime == "RISK OFF":
            return False, "quality blocked: weak trend in risk-off"
        return True, "quality allowed"
    if regime == "RISK OFF":
        return False, "satellite blocked in risk-off"
    if not trend_ok:
        return False, "satellite blocked: trend not strong enough"
    return True, "satellite allowed"


def entry_plan(meta: dict[str, Any], snap: MarketSnapshot) -> tuple[str, float]:
    sleeve = meta.get("sleeve", "satellite")
    extended = snap.close > snap.ema20 + 1.25 * snap.atr
    breakout = snap.close > snap.hh20 and snap.volume >= 1.05 * snap.vol_ma
    if extended:
        return "BUY LIMIT", min(snap.ema20, snap.close - 0.65 * snap.atr)
    if breakout and sleeve in {"core", "core_growth", "satellite"}:
        return "BUY STOP", snap.hh20 + 0.10 * snap.atr
    if snap.close >= snap.ema20:
        return "BUY LIMIT", max(snap.ema20 - 0.15 * snap.atr, snap.ema50)
    return "BUY LIMIT", snap.ema50 + 0.10 * snap.atr


def protection_plan(meta: dict[str, Any], snap: MarketSnapshot, entry: float) -> dict[str, float | str]:
    sleeve = meta.get("sleeve", "satellite")
    if sleeve in {"core", "core_growth"}:
        stop = min(entry - 2.0 * snap.atr, snap.ema50 - 1.0 * snap.atr)
        tp1 = max(entry * 1.08, snap.ema20 + 2.0 * snap.atr)
        return {"style": "core", "sl": stop, "tp1": tp1, "tp1_sell_pct": 20, "tp2": 0.0, "trail": "EMA20 or 2 ATR after TP1; do not fully exit"}
    if sleeve == "quality":
        stop = snap.ema150 - 1.0 * snap.atr
        return {"style": "quality", "sl": stop, "tp1": 0.0, "tp1_sell_pct": 0, "tp2": 0.0, "trail": "No TP; rebalance only if weight > 15%"}
    stop = entry - 1.8 * snap.atr
    risk = max(entry - stop, 0.01)
    tp1 = max(entry * 1.08, entry + 1.5 * risk)
    tp2 = max(entry * 1.15, entry + 2.5 * risk)
    return {"style": "satellite", "sl": stop, "tp1": tp1, "tp1_sell_pct": 30, "tp2": tp2, "tp2_sell_pct": 30, "trail": "Trail remaining 40% with EMA20/ATR"}


def reward_risk_ok(prot: dict[str, float | str], entry: float) -> tuple[bool, float]:
    sl = float(prot["sl"])
    tp1 = float(prot.get("tp1", 0.0) or 0.0)
    if tp1 <= 0:
        return True, 99.0
    risk = entry - sl
    reward = tp1 - entry
    rr = reward / risk if risk > 0 else 0.0
    return rr >= 1.5, rr


def choose_best_candidate(config: dict[str, Any], state: dict[str, Any], regime: str) -> tuple[str, dict[str, Any]] | None:
    view, total = build_portfolio_view(config)
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for name, item in view.items():
        meta, snap = item["meta"], item["snap"]
        ok, reason = can_buy(meta, snap, regime)
        if not ok:
            print(f"{name}: no buy — {reason}")
            continue
        if item["gap_eur"] <= 0:
            print(f"{name}: no buy — not underweight")
            continue
        candidates.append((float(item["gap_eur"]), name, {**item, "total_eur": total, "reason": reason}))
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1], candidates[0][2]


def make_order_message(config: dict[str, Any], state: dict[str, Any], name: str, item: dict[str, Any], regime: str, score: int, details: str) -> str | None:
    meta, snap = item["meta"], item["snap"]
    order_type, entry = entry_plan(meta, snap)
    prot = protection_plan(meta, snap, entry)
    rr_ok, rr = reward_risk_ok(prot, entry)
    if not rr_ok:
        return None

    free_cash = float(config["settings"].get("free_cash_eur", 0.0))
    reserve = float(config["settings"].get("cash_reserve_pct", 0.10)) * float(item["total_eur"])
    deployable = max(0.0, free_cash - reserve)
    order_eur = min(float(item["gap_eur"]), deployable, float(config["settings"].get("max_order_eur", 75.0)))
    if order_eur < float(config["settings"].get("min_order_eur", 25.0)):
        return None
    qty = order_eur / entry if entry > 0 else 0.0

    alert_key = f"ORDER:{name}:{datetime.now(MKT_TZ).date().isoformat()}:{round(entry, 2)}"
    if not alert_once(state, alert_key, int(config["settings"].get("min_alert_interval_hours", 6))):
        return None
    mark_daily_entry(state, name)

    tp_lines = ""
    if float(prot.get("tp1", 0.0) or 0.0) > 0:
        tp_lines += f"• TP1: <b>{fmt(float(prot['tp1']))}</b> — sell {prot.get('tp1_sell_pct', 0)}%\n"
    if float(prot.get("tp2", 0.0) or 0.0) > 0:
        tp_lines += f"• TP2: <b>{fmt(float(prot['tp2']))}</b> — sell {prot.get('tp2_sell_pct', 0)}%\n"
    if not tp_lines:
        tp_lines = "• TP: <b>none</b> — use rebalance discipline\n"

    msg = (
        f"📌 <b>ETF BOT V3 — ACTION REQUIRED</b>\n"
        f"Instrument: <b>{name}</b> — {meta['label']}\n"
        f"XTB: <b>{meta['xtb_symbol']}</b> | Yahoo: <b>{meta['yf_symbol']}</b>\n"
        f"Sleeve: <b>{meta.get('sleeve')}</b> | Target: <b>{float(meta['target_weight']):.1%}</b> | Actual: <b>{float(item['actual_weight']):.1%}</b>\n"
        f"Gap: <b>{float(item['gap_eur']):.2f} EUR</b> | Portfolio est.: <b>{float(item['total_eur']):.2f} EUR</b>\n\n"
        f"Regime: <b>{regime}</b> / score {score}/100\n{details}\n\n"
        f"Order to place in XTB:\n"
        f"• Type: <b>{order_type}</b>\n"
        f"• Entry price: <b>{fmt(entry)}</b>\n"
        f"• Amount: <b>{order_eur:.2f} EUR</b>\n"
        f"• Quantity estimate: <b>{qty:.4f}</b>\n\n"
        f"Protection immediately after fill:\n"
        f"• Stop Loss: <b>{fmt(float(prot['sl']))}</b>\n"
        f"{tp_lines}"
        f"• Trailing rule: {prot['trail']}\n"
        f"• Reward/risk to TP1: <b>{rr:.2f}</b>\n\n"
        f"Rule: if filled, protection must be placed before any new buy. No polite exceptions."
    )
    return msg


def portfolio_report(config: dict[str, Any], regime: str, score: int, details: str) -> str:
    view, total = build_portfolio_view(config)
    lines = [
        "📊 <b>ETF BOT V3 — PORTFOLIO STATUS</b>",
        f"Portfolio est.: <b>{total:.2f} EUR</b>",
        f"Regime: <b>{regime}</b> / score {score}/100",
        details,
        "",
        "Allocation gaps:"
    ]
    for name, item in sorted(view.items(), key=lambda kv: kv[1]["target_weight"] if "target_weight" in kv[1] else kv[1]["meta"]["target_weight"], reverse=True):
        meta = item["meta"]
        lines.append(
            f"• {name}: target {float(meta['target_weight']):.1%}, actual {float(item['actual_weight']):.1%}, "
            f"gap {float(item['gap_eur']):+.2f} EUR"
        )
    return "\n".join(lines)


def run_once(config: dict[str, Any], state: dict[str, Any]) -> None:
    regime, score, details = classify_regime(config)
    print(f"Regime: {regime} score={score} | {details}")

    report_key = f"REPORT:{datetime.now(MKT_TZ).date().isoformat()}"
    if alert_once(state, report_key, 20):
        send_telegram(portfolio_report(config, regime, score, details))

    if not daily_entry_allowed(config, state):
        print("Daily entry already used. No new buy.")
        return

    choice = choose_best_candidate(config, state, regime)
    if choice is None:
        print("No valid candidate.")
        return
    name, item = choice
    msg = make_order_message(config, state, name, item, regime, score, details)
    if msg:
        send_telegram(msg)
    else:
        print(f"Candidate {name} rejected by sizing or reward/risk.")


def startup_message(config: dict[str, Any]) -> str:
    lines = ["✅ <b>ETF Bot V3 started</b>", "Targets:"]
    for name, meta in config["etfs"].items():
        if meta.get("enabled", True):
            lines.append(f"• {name}: <b>{float(meta['target_weight']):.1%}</b> — {meta.get('sleeve')}")
    lines.append("\nNo single stocks. No gold. One new entry/day. Mandatory SL/TP discipline.")
    return "\n".join(lines)


def run() -> None:
    config = load_config()
    state = load_state()
    send_telegram(startup_message(config))
    sleep_seconds = int(config["settings"].get("sleep_seconds", 900))
    while True:
        print(f"[{datetime.now(MKT_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}] scan")
        config = load_config()
        state = load_state()
        try:
            run_once(config, state)
        except Exception as exc:
            print(f"Run error: {exc}")
            send_telegram(f"🔴 <b>ETF Bot V3 error</b>\n{exc}")
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    run()
