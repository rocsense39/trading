"""
Bot_DCA V2.1 Clean
==================
Google Colab + Telegram alert bot pentru:
1) ETF DCA oportunist: SXR8, SXRV, XXME/XMME, H411, optional SGLD
2) Alerte exacte: PUNE BUY LIMIT + BUY LIMIT HIT
3) Market regime: SPY, QQQ, VIX => RISK ON / NEUTRAL / RISK OFF
4) Swing satelit: AAOI, AIFS etc. cu Buy Limit / Buy Stop / Sell Stop / TP / trailing
5) Config separat in JSON: config_portfolio.json

Rulare Colab:
%cd /content/trading
!python bot_dca_v2.py

Setare token in Colab:
import os, getpass
os.environ["TELEGRAM_TOKEN"] = getpass.getpass("TELEGRAM_TOKEN: ").strip()
os.environ["TELEGRAM_CHAT_ID"] = getpass.getpass("TELEGRAM_CHAT_ID: ").strip()
"""

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

# =========================
# GLOBAL SETTINGS
# =========================
CONFIG_PATH = Path("config_portfolio.json")
STATE_PATH = Path("bot_state.json")
MKT_TZ = ZoneInfo("Europe/Berlin")
INTERVAL = "1h"
PERIOD = "6mo"
SLEEP_SECONDS_DEFAULT = 900

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 150
ATR_LEN = 20
VOL_MA_LEN = 20


# =========================
# DEFAULT CONFIG
# =========================
DEFAULT_CONFIG = {
    "settings": {
        "monthly_budget_ron": 500,
        "cash_available_ron": 500,
        "sleep_seconds": 900,
        "eur_ron": 5.0,
        "usd_ron": 4.65,
        "min_alert_interval_hours": 4,
        "risk_mode": "balanced"
    },
    "portfolio": {
        "positions": {
            "SXR8": {"avg_price": 626.0, "qty": 0.4632, "currency": "EUR"},
            "SXRV": {"avg_price": 1315.0, "qty": 0.05, "currency": "EUR"},
            "AAOI": {"avg_price": 208.0, "qty": 0.05, "currency": "USD"}
        }
    },
    "etfs": {
        "SXR8": {
            "enabled": True,
            "xtb_symbol": "SXR8.DE",
            "yf_symbol": "SXR8.DE",
            "label": "iShares Core S&P 500 UCITS ETF",
            "target_weight": 0.45,
            "currency": "EUR"
        },
        "SXRV": {
            "enabled": True,
            "xtb_symbol": "SXRV.DE",
            "yf_symbol": "SXRV.DE",
            "label": "iShares Nasdaq 100 UCITS ETF",
            "target_weight": 0.30,
            "currency": "EUR"
        },
        "XXME": {
            "enabled": True,
            "xtb_symbol": "XXME.DE",
            "yf_symbol": "XMME.DE",
            "label": "MSCI Emerging Markets ETF",
            "target_weight": 0.15,
            "currency": "EUR"
        },
        "H411": {
            "enabled": True,
            "xtb_symbol": "H411.DE",
            "yf_symbol": "H411.DE",
            "label": "H411 ETF",
            "target_weight": 0.10,
            "currency": "EUR"
        },
        "SGLD": {
            "enabled": False,
            "xtb_symbol": "SGLD.UK",
            "yf_symbol": "SGLD.L",
            "label": "Physical Gold ETC",
            "target_weight": 0.00,
            "currency": "USD"
        }
    },
    "swings": {
        "AAOI": {
            "enabled": True,
            "xtb_symbol": "AAOI.US",
            "yf_symbol": "AAOI",
            "label": "Applied Optoelectronics",
            "max_allocation_pct": 5,
            "currency": "USD",
            "manual_stop": 195.0,
            "manual_tp1": 225.0,
            "manual_tp2": 240.0
        },
        "AIFS": {
            "enabled": False,
            "xtb_symbol": "AIFS.US",
            "yf_symbol": "AIFS.DE",
            "label": "AIFS",
            "max_allocation_pct": 3,
            "currency": "USD"
        }
    },
    "regime_symbols": {
        "sp500": "SPY",
        "nasdaq": "QQQ",
        "vix": "^VIX"
    }
}


# =========================
# CONFIG + STATE
# =========================
def create_default_config_if_missing() -> None:
    if CONFIG_PATH.exists():
        return
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
            return json.load(f)
    except Exception:
        return {"alerts": {}}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# =========================
# TELEGRAM
# =========================
def strip_html_tags(message: str) -> str:
    """Fallback simplu pentru Telegram când parse_mode=HTML eșuează."""
    return (
        message
        .replace("<b>", "")
        .replace("</b>", "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def send_telegram(message: str) -> bool:
    token = (os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()

    if not token or not chat_id:
        print("Telegram TOKEN/CHAT_ID lipsă. Mesaj:")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        print("Telegram status:", r.status_code)
        print("Telegram response:", r.text[:500])

        if r.status_code == 200:
            return True

        # Dacă HTML-ul pică din cauza caracterelor < sau >, retrimitem plain text.
        plain_payload = {
            "chat_id": chat_id,
            "text": strip_html_tags(message),
            "disable_web_page_preview": True,
        }
        r2 = requests.post(url, json=plain_payload, timeout=15)
        print("Telegram fallback status:", r2.status_code)
        print("Telegram fallback response:", r2.text[:500])
        return r2.status_code == 200

    except Exception as e:
        print(f"Telegram error: {e}")
        return False


# =========================
# DATA
# =========================
def get_data(symbol: str, period: str = PERIOD, interval: str = INTERVAL) -> pd.DataFrame:
    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
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
    df = df.copy()
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
    df["HH20"] = df["High"].shift(1).rolling(20).max()
    df["LL20"] = df["Low"].shift(1).rolling(20).min()
    df["SWING_HIGH_80"] = df["High"].rolling(80).max()
    df["SWING_LOW_80"] = df["Low"].rolling(80).min()

    return df.dropna().copy()


# =========================
# UTILS
# =========================
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
        return f"{x:.2f}"
    return f"{x:.4f}"


def get_fx(config: dict, currency: str) -> float:
    settings = config.get("settings", {})
    currency = currency.upper()
    if currency == "RON":
        return 1.0
    if currency == "EUR":
        return float(settings.get("eur_ron", 5.0))
    if currency == "USD":
        return float(settings.get("usd_ron", 4.65))
    return 1.0


def ron_to_asset_amount(config: dict, ron: float, price: float, currency: str) -> float:
    fx = get_fx(config, currency)
    if price <= 0 or fx <= 0:
        return 0.0
    return ron / (price * fx)


def alert_once(state: dict, key: str, min_hours: int) -> bool:
    now_ts = pd.Timestamp.now(tz=MKT_TZ)
    last = state.setdefault("alerts", {}).get(key)
    if last:
        try:
            last_time = pd.Timestamp(last)
            diff_hours = (now_ts - last_time).total_seconds() / 3600
            if diff_hours < min_hours:
                return False
        except Exception:
            pass
    state["alerts"][key] = now_ts.isoformat()
    save_state(state)
    return True


def position_info(config: dict, symbol: str) -> dict:
    return config.get("portfolio", {}).get("positions", {}).get(symbol, {})


def estimate_portfolio_value_ron(config: dict, latest_prices: dict[str, tuple[float, str]]) -> float:
    total = 0.0
    positions = config.get("portfolio", {}).get("positions", {})
    for sym, pos in positions.items():
        qty = float(pos.get("qty", 0))
        currency = pos.get("currency", "EUR")
        price = latest_prices.get(sym, (float(pos.get("avg_price", 0)), currency))[0]
        total += qty * price * get_fx(config, currency)
    total += float(config.get("settings", {}).get("cash_available_ron", 0))
    return total


def fib_zones(low: float, high: float) -> dict[str, float]:
    move = high - low
    return {
        "23.6%": high - 0.236 * move,
        "38.2%": high - 0.382 * move,
        "50.0%": high - 0.500 * move,
    }


# =========================
# MARKET REGIME
# =========================
def classify_market_regime(config: dict) -> tuple[str, str]:
    symbols = config.get("regime_symbols", {})
    sp = symbols.get("sp500", "SPY")
    qqq = symbols.get("nasdaq", "QQQ")
    vix = symbols.get("vix", "^VIX")

    score = 0
    details = []

    for label, symbol in [("S&P", sp), ("Nasdaq", qqq)]:
        df = get_data(symbol, period="6mo", interval="1d")
        if df.empty or len(df) < 80:
            details.append(f"{label}: n/a")
            continue
        df = add_indicators(df)
        last = df.iloc[-1]
        close_ = float(last["Close"])
        ema20 = float(last["EMA20"])
        ema50 = float(last["EMA50"])
        if close_ > ema20 > ema50:
            score += 1
            details.append(f"{label}: bullish")
        elif close_ < ema50:
            score -= 1
            details.append(f"{label}: weak")
        else:
            details.append(f"{label}: neutral")

    vix_df = get_data(vix, period="3mo", interval="1d")
    if not vix_df.empty:
        vix_last = float(vix_df.iloc[-1]["Close"])
        if vix_last < 18:
            score += 1
            details.append(f"VIX: calm {fmt(vix_last)}")
        elif vix_last > 25:
            score -= 1
            details.append(f"VIX: high {fmt(vix_last)}")
        else:
            details.append(f"VIX: neutral {fmt(vix_last)}")

    if score >= 2:
        return "RISK ON", "; ".join(details)
    if score <= -1:
        return "RISK OFF", "; ".join(details)
    return "NEUTRAL", "; ".join(details)


# =========================
# ETF DCA ENGINE
# =========================
def analyze_etf(name: str, meta: dict, config: dict, state: dict, regime: str, regime_details: str) -> list[str]:
    df = get_data(meta["yf_symbol"])
    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 180:
        return []
    df = add_indicators(df)
    if df.empty:
        return []

    last = df.iloc[-1]
    min_hours = int(config.get("settings", {}).get("min_alert_interval_hours", 4))

    close_ = float(last["Close"])
    high_ = float(last["High"])
    low_ = float(last["Low"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema150 = float(last["EMA150"])
    atr = float(last["ATR"])
    high80 = float(last["SWING_HIGH_80"])
    low80 = float(last["SWING_LOW_80"])

    monthly_budget = float(config["settings"].get("monthly_budget_ron", 500))
    cash_available = float(config["settings"].get("cash_available_ron", monthly_budget))
    target_weight = float(meta.get("target_weight", 0))
    allocation_ron = min(cash_available, monthly_budget * target_weight)

    currency = meta.get("currency", "EUR")
    trend_ok = close_ > ema50 > ema150
    strong_trend = close_ > ema20 > ema50 > ema150
    extended = close_ > ema20 + 1.2 * atr
    near_ema20 = abs(close_ - ema20) <= 0.65 * atr
    near_ema50 = abs(close_ - ema50) <= 0.85 * atr
    zones = fib_zones(low80, high80)

    if regime == "RISK OFF":
        allocation_ron *= 0.50
    elif regime == "NEUTRAL":
        allocation_ron *= 0.75

    messages = []

    # 1) PLAN: anunta ce BuyLimit poti seta acum
    if trend_ok and close_ > ema20 and allocation_ron > 0:
        key = f"{name}:ETF_BUYLIMIT_PLAN"
        if alert_once(state, key, min_hours):
            fib23 = zones["23.6%"]
            fib38 = zones["38.2%"]

            candidates = [x for x in [ema20, fib23] if x < close_]
            primary_limit = max(candidates) if candidates else min(ema20, close_ * 0.995)

            secondary_candidates = [x for x in [ema50, fib38] if x < primary_limit]
            secondary_limit = max(secondary_candidates) if secondary_candidates else min(ema50, fib38)

            qty_primary = ron_to_asset_amount(config, allocation_ron * 0.60, primary_limit, currency)
            qty_secondary = ron_to_asset_amount(config, allocation_ron * 0.40, secondary_limit, currency)

            msg = (
                f"📌 <b>{name} — PUNE BUY LIMIT DCA</b>\n"
                f"{meta['label']}\n"
                f"XTB: <b>{meta['xtb_symbol']}</b> | Yahoo: <b>{meta['yf_symbol']}</b>\n"
                f"Regime: <b>{regime}</b> ({regime_details})\n\n"
                f"Preț actual: <b>{fmt(close_)}</b>\n"
                f"EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)} | ATR: {fmt(atr)}\n\n"
                f"Ordin(e) Buy Limit recomandate:\n"
                f"• Principal 60%: <b>{fmt(primary_limit)}</b> | buget {allocation_ron * 0.60:.0f} RON | qty est. {qty_primary:.4f}\n"
                f"• Secundar 40%: <b>{fmt(secondary_limit)}</b> | buget {allocation_ron * 0.40:.0f} RON | qty est. {qty_secondary:.4f}\n\n"
                f"Logică: DCA oportunist sub prețul curent, nu market chase."
            )
            messages.append(msg)

    # 2) HIT: anunta cand pretul atinge zona de BuyLimit
    if trend_ok and allocation_ron > 0:
        fib23 = zones["23.6%"]
        fib38 = zones["38.2%"]
        primary_limit = max([x for x in [ema20, fib23] if x < max(close_, high_)] or [ema20])
        secondary_limit = max([x for x in [ema50, fib38] if x < primary_limit] or [min(ema50, fib38)])

        if low_ <= primary_limit <= high_:
            key = f"{name}:ETF_BUYLIMIT_HIT_PRIMARY:{round(primary_limit, 2)}"
            if alert_once(state, key, min_hours):
                qty = ron_to_asset_amount(config, allocation_ron * 0.60, primary_limit, currency)
                msg = (
                    f"🔔 <b>{name} — BUY LIMIT HIT</b>\n"
                    f"Prețul a atins zona principală DCA.\n"
                    f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                    f"Buy Limit principal: <b>{fmt(primary_limit)}</b>\n"
                    f"Buget: <b>{allocation_ron * 0.60:.0f} RON</b> | Qty est.: <b>{qty:.4f}</b>\n"
                    f"Regime: <b>{regime}</b>"
                )
                messages.append(msg)

        if low_ <= secondary_limit <= high_:
            key = f"{name}:ETF_BUYLIMIT_HIT_SECONDARY:{round(secondary_limit, 2)}"
            if alert_once(state, key, min_hours):
                qty = ron_to_asset_amount(config, allocation_ron * 0.40, secondary_limit, currency)
                msg = (
                    f"🔔🟢 <b>{name} — BUY LIMIT DEEP HIT</b>\n"
                    f"Prețul a atins zona secundară DCA.\n"
                    f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                    f"Buy Limit secundar: <b>{fmt(secondary_limit)}</b>\n"
                    f"Buget: <b>{allocation_ron * 0.40:.0f} RON</b> | Qty est.: <b>{qty:.4f}</b>\n"
                    f"Regime: <b>{regime}</b>"
                )
                messages.append(msg)

    # 3) EXTENDED: nu chase, seteaza limite
    if strong_trend and extended:
        key = f"{name}:ETF_EXTENDED"
        if alert_once(state, key, min_hours):
            qty_236 = ron_to_asset_amount(config, allocation_ron, zones["23.6%"], currency)
            msg = (
                f"🟡 <b>{name} — DCA WAIT / SET LIMITS</b>\n"
                f"{meta['label']}\n"
                f"XTB: <b>{meta['xtb_symbol']}</b> | Yahoo: <b>{meta['yf_symbol']}</b>\n"
                f"Regime: <b>{regime}</b> ({regime_details})\n\n"
                f"Preț: <b>{fmt(close_)}</b> | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Status: trend bullish, dar preț extins. Nu chase.\n\n"
                f"Buy Limit zones:\n"
                f"• 23.6%: <b>{fmt(zones['23.6%'])}</b> | qty est.: {qty_236:.4f}\n"
                f"• 38.2%: <b>{fmt(zones['38.2%'])}</b>\n"
                f"• 50.0%: <b>{fmt(zones['50.0%'])}</b>\n"
                f"Alocare disponibilă pentru {name}: <b>{allocation_ron:.0f} RON</b>"
            )
            messages.append(msg)

    # 4) ENTRY la EMA20
    if trend_ok and near_ema20 and close_ >= ema20:
        key = f"{name}:ETF_EMA20_ENTRY"
        if alert_once(state, key, min_hours):
            buy_limit = min(close_, ema20 + 0.15 * atr)
            qty = ron_to_asset_amount(config, allocation_ron, buy_limit, currency)
            invalid = ema50 - 0.8 * atr
            msg = (
                f"🟢 <b>{name} — DCA ENTRY</b>\n"
                f"{meta['label']}\n"
                f"XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Regime: <b>{regime}</b>\n\n"
                f"Reason: pullback la EMA20 în trend ascendent\n"
                f"Preț: {fmt(close_)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n\n"
                f"Ordin sugerat:\n"
                f"• Buy Limit: <b>{fmt(buy_limit)}</b>\n"
                f"• Buget: <b>{allocation_ron:.0f} RON</b>\n"
                f"• Cantitate estimată: <b>{qty:.4f}</b>\n"
                f"• Invalidation tehnică: sub {fmt(invalid)}"
            )
            messages.append(msg)

    # 5) ENTRY la EMA50
    if close_ > ema150 and near_ema50:
        key = f"{name}:ETF_EMA50_ENTRY"
        if alert_once(state, key, min_hours):
            buy_limit = min(close_, ema50 + 0.2 * atr)
            qty = ron_to_asset_amount(config, allocation_ron, buy_limit, currency)
            msg = (
                f"🟢🟢 <b>{name} — DCA STRONGER DIP</b>\n"
                f"{meta['label']}\n"
                f"Regime: <b>{regime}</b>\n\n"
                f"Reason: pullback la EMA50 / dip mai bun\n"
                f"Preț: {fmt(close_)} | EMA50: <b>{fmt(ema50)}</b> | EMA150: {fmt(ema150)}\n\n"
                f"Ordin sugerat:\n"
                f"• Buy Limit: <b>{fmt(buy_limit)}</b>\n"
                f"• Buget: <b>{allocation_ron:.0f} RON</b>\n"
                f"• Cantitate estimată: <b>{qty:.4f}</b>"
            )
            messages.append(msg)

    # 6) RISK WARNING
    if close_ < ema50 and float(last["EMA20"]) < ema50:
        key = f"{name}:ETF_RISK_WARNING"
        if alert_once(state, key, min_hours):
            msg = (
                f"🔴 <b>{name} — DCA PRUDENȚĂ</b>\n"
                f"Preț sub EMA50 și EMA20 &lt; EMA50.\n"
                f"Preț: {fmt(close_)} | EMA20: {fmt(float(last['EMA20']))} | EMA50: {fmt(ema50)}\n"
                f"Regime: <b>{regime}</b>\n"
                f"Sugestie: doar tranșe mici sau așteaptă stabilizare."
            )
            messages.append(msg)

    return messages


# =========================
# SWING ENGINE
# =========================
def analyze_swing(name: str, meta: dict, config: dict, state: dict, regime: str) -> list[str]:
    if regime == "RISK OFF":
        return []

    df = get_data(meta["yf_symbol"])
    df = drop_incomplete_candle(df)
    if df.empty or len(df) < 180:
        return []
    df = add_indicators(df)
    if df.empty:
        return []

    last = df.iloc[-1]
    prev = df.iloc[-2]
    min_hours = int(config.get("settings", {}).get("min_alert_interval_hours", 4))

    close_ = float(last["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    atr = float(last["ATR"])
    vol = float(last["Volume"])
    vol_ma = float(last["VOL_MA"])
    hh20 = float(last["HH20"])
    ll20 = float(last["LL20"])

    pos = position_info(config, name)
    avg = float(pos.get("avg_price", 0)) if pos else 0
    qty_pos = float(pos.get("qty", 0)) if pos else 0

    max_alloc = float(meta.get("max_allocation_pct", 5))
    currency = meta.get("currency", "USD")

    latest_prices = {name: (close_, currency)}
    portfolio_value = estimate_portfolio_value_ron(config, latest_prices)
    max_trade_ron = portfolio_value * max_alloc / 100

    volume_ok = vol_ma > 0 and vol > 1.2 * vol_ma
    trend_bull = close_ > ema20 > ema50
    breakout = trend_bull and close_ > hh20
    pullback = trend_bull and abs(close_ - ema20) <= 0.8 * atr
    invalidation = close_ < ema50 or close_ < ll20

    messages = []

    if breakout and (volume_ok or atr > float(prev["ATR"])):
        key = f"{name}:SWING_BREAKOUT"
        if alert_once(state, key, min_hours):
            entry = close_ + 0.10 * atr
            sl = float(meta.get("manual_stop") or max(ema20 - 1.2 * atr, close_ - 2.0 * atr))
            risk = max(entry - sl, 0.01)
            tp1 = float(meta.get("manual_tp1") or entry + 1.5 * risk)
            tp2 = float(meta.get("manual_tp2") or entry + 2.5 * risk)
            qty = ron_to_asset_amount(config, max_trade_ron, entry, currency)
            msg = (
                f"🚀 <b>{name} — SWING BREAKOUT</b>\n"
                f"{meta['label']} | XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Regime: <b>{regime}</b>\n"
                f"Preț: {fmt(close_)} | EMA20: {fmt(ema20)} | EMA50: {fmt(ema50)}\n"
                f"Volum: {vol:.0f} vs medie {vol_ma:.0f}\n\n"
                f"Ordin orientativ:\n"
                f"• Buy Stop: <b>{fmt(entry)}</b>\n"
                f"• Sell Stop: <b>{fmt(sl)}</b>\n"
                f"• Sell Limit TP1: <b>{fmt(tp1)}</b>\n"
                f"• Sell Limit TP2: <b>{fmt(tp2)}</b>\n"
                f"• Max alocare: {max_alloc:.1f}% ≈ {max_trade_ron:.0f} RON\n"
                f"• Qty estimată: {qty:.4f}"
            )
            messages.append(msg)

    if pullback:
        key = f"{name}:SWING_PULLBACK"
        if alert_once(state, key, min_hours):
            entry = min(close_, ema20 + 0.20 * atr)
            sl = float(meta.get("manual_stop") or (ema50 - 1.0 * atr))
            risk = max(entry - sl, 0.01)
            tp1 = float(meta.get("manual_tp1") or entry + 1.5 * risk)
            tp2 = float(meta.get("manual_tp2") or entry + 2.5 * risk)
            qty = ron_to_asset_amount(config, max_trade_ron, entry, currency)
            msg = (
                f"🟢 <b>{name} — SWING PULLBACK</b>\n"
                f"{meta['label']} | XTB: <b>{meta['xtb_symbol']}</b>\n"
                f"Regime: <b>{regime}</b>\n"
                f"Preț: {fmt(close_)} | EMA20: <b>{fmt(ema20)}</b> | EMA50: {fmt(ema50)}\n"
                f"Poziție actuală: avg {fmt(avg)} | qty {qty_pos}\n\n"
                f"Ordin orientativ:\n"
                f"• Buy Limit: <b>{fmt(entry)}</b>\n"
                f"• Sell Stop: <b>{fmt(sl)}</b>\n"
                f"• Sell Limit TP1: <b>{fmt(tp1)}</b>\n"
                f"• Sell Limit TP2: <b>{fmt(tp2)}</b>\n"
                f"• Max alocare: {max_alloc:.1f}% ≈ {max_trade_ron:.0f} RON\n"
                f"• Qty estimată: {qty:.4f}"
            )
            messages.append(msg)

    if qty_pos > 0 and avg > 0:
        pnl_pct = (close_ / avg - 1) * 100
        if pnl_pct >= 8:
            key = f"{name}:SWING_TRAIL_8"
            if alert_once(state, key, min_hours):
                trail = max(avg, ema20 - 0.5 * atr)
                msg = (
                    f"🔵 <b>{name} — TRAILING STOP</b>\n"
                    f"Poziția este aprox. +{pnl_pct:.1f}% față de avg {fmt(avg)}.\n"
                    f"Sugestie: ridică stop spre breakeven / tehnic.\n"
                    f"Stop orientativ: <b>{fmt(trail)}</b>"
                )
                messages.append(msg)

    if invalidation:
        key = f"{name}:SWING_INVALIDATION"
        if alert_once(state, key, min_hours):
            msg = (
                f"🔴 <b>{name} — SWING INVALIDATION</b>\n"
                f"Preț: {fmt(close_)} | EMA50: {fmt(ema50)} | LL20: {fmt(ll20)}\n"
                f"Evită add. Verifică Sell Stop."
            )
            messages.append(msg)

    return messages


# =========================
# REPORTS
# =========================
def send_startup_plan(config: dict) -> None:
    monthly = float(config["settings"].get("monthly_budget_ron", 500))
    cash = float(config["settings"].get("cash_available_ron", monthly))
    lines = [
        "✅ <b>Bot_DCA V2.1 a pornit.</b>",
        f"Buget lunar: <b>{monthly:.0f} RON</b>",
        f"Cash disponibil luna asta: <b>{cash:.0f} RON</b>",
        "",
        "📌 <b>Alocare ETF:</b>"
    ]
    for name, meta in config.get("etfs", {}).items():
        if not meta.get("enabled", True):
            continue
        w = float(meta.get("target_weight", 0))
        lines.append(f"• {name}: {w:.0%} = <b>{monthly * w:.0f} RON</b>")

    lines.append("\nRegulă: botul trimite PUNE BUY LIMIT + BUY LIMIT HIT; nu cumpără automat.")
    send_telegram("\n".join(lines))


def weekly_report_if_needed(config: dict, state: dict, regime: str, regime_details: str) -> None:
    now = datetime.now(MKT_TZ)
    if now.weekday() != 6 or now.hour < 18:
        return
    key = f"weekly_report:{now.date()}"
    if not alert_once(state, key, 24):
        return

    lines = [
        "📊 <b>Weekly Bot_DCA Review</b>",
        f"Regime: <b>{regime}</b>",
        regime_details,
        "",
        "ETF: așteaptă EMA20/EMA50/Fib; evită chase după lumânări extinse.",
        "Swing: doar 1-5%, cu Sell Stop setat din start."
    ]
    send_telegram("\n".join(lines))


# =========================
# MAIN LOOP
# =========================
def run_once(config: dict, state: dict) -> None:
    regime, regime_details = classify_market_regime(config)
    print(f"Market regime: {regime} | {regime_details}")

    for name, meta in config.get("etfs", {}).items():
        if not meta.get("enabled", True):
            continue
        try:
            for msg in analyze_etf(name, meta, config, state, regime, regime_details):
                ok = send_telegram(msg)
                print(f"ETF alert {'sent' if ok else 'FAILED'}: {name}")
        except Exception as e:
            print(f"ETF error {name}: {e}")

    for name, meta in config.get("swings", {}).items():
        if not meta.get("enabled", True):
            continue
        try:
            for msg in analyze_swing(name, meta, config, state, regime):
                ok = send_telegram(msg)
                print(f"Swing alert {'sent' if ok else 'FAILED'}: {name}")
        except Exception as e:
            print(f"Swing error {name}: {e}")

    weekly_report_if_needed(config, state, regime, regime_details)


def run() -> None:
    config = load_config()
    state = load_state()
    send_startup_plan(config)

    sleep_seconds = int(config.get("settings", {}).get("sleep_seconds", SLEEP_SECONDS_DEFAULT))
    while True:
        now = datetime.now(MKT_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{now}] Bot_DCA V2.1 scan...")
        config = load_config()
        state = load_state()
        run_once(config, state)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    run()
