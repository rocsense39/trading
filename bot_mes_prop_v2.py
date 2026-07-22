"""
MES Prop Guard V2.0

Bot conservator de ALERTE pentru Micro E-mini S&P 500 (MES).
Nu executa ordine. Analizeaza numai lumanari inchise si trimite un plan
conditionat (Buy Stop / Sell Stop), cu risc calculat si termen de expirare.

Dependente:
    pip install pandas requests yfinance

Variabile de mediu pentru Telegram:
    TELEGRAM_TOKEN
    TELEGRAM_CHAT_ID

Pornire:
    python bot_mes_prop_v2.py
    python bot_mes_prop_v2.py --once

IMPORTANT: validati strategia pe minimum 50-100 de semnale demo. Un filtru
tehnic reduce tranzactiile slabe, dar nu garanteaza profitul.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


VERSION = "2.0.0"
CONFIG_PATH = Path("config_mes_prop_v2.json")
STATE_PATH = Path("state_mes_prop_v2.json")
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
_DATA_CACHE: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}
CACHE_SECONDS = 10 * 60

DEFAULT_CONFIG = {
    "symbol": "MES=F",
    "tradingview_symbol": "CME_MINI:MES1!",
    "scan_minutes": 15,
    "risk": {
        "max_risk_usd": 150.0,
        "point_value_usd": 5.0,
        "tick_size": 0.25,
        "min_rr": 2.0,
        "max_contracts": 1,
        "min_stop_points": 5.0,
        "max_stop_points": 30.0,
    },
    "filters": {
        "allow_long": True,
        "allow_short": True,
        "regular_session_only": True,
        "session_start_ny": "09:35",
        "session_end_ny": "15:30",
        "max_signals_per_day": 1,
        "signal_valid_hours": 3,
        "max_entry_distance_atr": 0.35,
        "vix_long_limit": 25.0,
        "vix_short_floor": 16.0,
        "require_volume_confirmation": False,
        "volume_multiple": 1.10,
    },
    "manual_blackouts": [
        # Ferestre in ora New York. Completati inainte de CPI, NFP, FOMC etc.
        # {"start": "2026-07-29 13:30", "end": "2026-07-29 14:30", "label": "FOMC"}
    ],
}


@dataclass
class Signal:
    direction: str
    entry: float
    stop: float
    target: float
    risk_points: float
    reward_points: float
    rr: float
    contracts: int
    risk_usd: float
    created_at: pd.Timestamp
    expires_at: pd.Timestamp
    reason: str


def write_default_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default.copy()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (OSError, json.JSONDecodeError):
        return default.copy()


def save_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def download(symbol: str, period: str, interval: str) -> pd.DataFrame:
    key = (symbol, period, interval)
    cached = _DATA_CACHE.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1].copy()
    df = pd.DataFrame()
    for attempt in range(2):
        try:
            df = yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=15,
            )
            if df is not None and not df.empty:
                break
        except Exception as exc:
            print(f"Download failed for {symbol} (attempt {attempt + 1}): {exc}")
        if attempt == 0:
            time.sleep(5)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not set(needed).issubset(df.columns):
        return pd.DataFrame()
    df = df[needed].dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize(UTC)
    else:
        df.index = df.index.tz_convert(UTC)
    df = df.sort_index()
    _DATA_CACHE[key] = (time.time(), df.copy())
    return df


def remove_open_hour(df: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Elimina bara 1h in curs. Yahoo timestamp-eaza bara la inceputul orei."""
    if df.empty:
        return df
    now = now or pd.Timestamp.now(tz=UTC)
    last_start = df.index[-1]
    if now < last_start + pd.Timedelta(hours=1, minutes=2):
        return df.iloc[:-1].copy()
    return df.copy()


def remove_open_daily(df: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    if df.empty:
        return df
    now = now or pd.Timestamp.now(tz=UTC)
    last_ny_date = df.index[-1].tz_convert(NY).date()
    if last_ny_date >= now.tz_convert(NY).date():
        return df.iloc[:-1].copy()
    return df.copy()


def resample_h4(hourly: pd.DataFrame) -> pd.DataFrame:
    """Construieste H4 din H1; evita dependenta de intervalul Yahoo '4h'."""
    if hourly.empty:
        return hourly
    data = hourly.tz_convert(NY)
    grouped = data.resample("4h", origin="start_day", offset="1h")
    out = grouped.agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    out["_bars"] = grouped["Close"].count()
    # Ultimul grup partial nu devine semnal H4. Acceptam 3 bare in grupurile
    # afectate de pauza zilnica a futures, dar nu 1-2 bare incomplete.
    out = out[out["_bars"] >= 3].drop(columns="_bars")
    return out.dropna(subset=["Open", "High", "Low", "Close"])


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for length in (20, 50, 100, 200):
        out[f"EMA{length}"] = out["Close"].ewm(span=length, adjust=False).mean()
    prev = out["Close"].shift(1)
    tr = pd.concat(
        [(out["High"] - out["Low"]), (out["High"] - prev).abs(), (out["Low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    out["ATR"] = tr.rolling(14).mean()
    out["VOL_MA"] = out["Volume"].rolling(20).mean()
    out["HH20"] = out["High"].shift(1).rolling(20).max()
    out["LL20"] = out["Low"].shift(1).rolling(20).min()
    return out.dropna().copy()


def parse_hhmm(value: str) -> clock_time:
    hour, minute = (int(part) for part in value.split(":"))
    return clock_time(hour, minute)


def in_session(now_ny: datetime, cfg: dict) -> bool:
    f = cfg["filters"]
    if not f.get("regular_session_only", True):
        return True
    if now_ny.weekday() >= 5:
        return False
    return parse_hhmm(f["session_start_ny"]) <= now_ny.time() <= parse_hhmm(f["session_end_ny"])


def blackout_label(now_ny: datetime, cfg: dict) -> Optional[str]:
    for item in cfg.get("manual_blackouts", []):
        try:
            start = datetime.strptime(item["start"], "%Y-%m-%d %H:%M").replace(tzinfo=NY)
            end = datetime.strptime(item["end"], "%Y-%m-%d %H:%M").replace(tzinfo=NY)
            if start <= now_ny <= end:
                return item.get("label", "eveniment economic")
        except (KeyError, TypeError, ValueError):
            continue
    return None


def market_regime() -> tuple[str, str, Optional[float]]:
    score = 0
    details: list[str] = []
    for label, symbol in (("SPY", "SPY"), ("QQQ", "QQQ")):
        df = indicators(remove_open_daily(download(symbol, "1y", "1d")))
        if df.empty:
            details.append(f"{label}=n/a")
            continue
        row = df.iloc[-1]
        if row.Close > row.EMA20 > row.EMA50:
            score += 1
            details.append(f"{label}=bull")
        elif row.Close < row.EMA20 < row.EMA50:
            score -= 1
            details.append(f"{label}=bear")
        else:
            details.append(f"{label}=neutral")
    vix_df = remove_open_daily(download("^VIX", "3mo", "1d"))
    vix = float(vix_df.iloc[-1].Close) if not vix_df.empty else None
    if vix is not None:
        details.append(f"VIX={vix:.1f}")
    regime = "BULL" if score == 2 else "BEAR" if score == -2 else "NEUTRAL"
    return regime, "; ".join(details), vix


def bullish_confirmation(row: pd.Series, previous: pd.Series) -> bool:
    body = max(abs(row.Close - row.Open), 0.25)
    candle_range = max(row.High - row.Low, 0.25)
    lower_wick = min(row.Open, row.Close) - row.Low
    close_high = (row.Close - row.Low) / candle_range >= 0.65
    rejection = row.Close > row.Open and lower_wick >= 0.8 * body and close_high
    reclaim = previous.Close <= previous.EMA20 and row.Close > row.EMA20 and row.Close > row.Open
    return bool(rejection or reclaim)


def bearish_confirmation(row: pd.Series, previous: pd.Series) -> bool:
    body = max(abs(row.Close - row.Open), 0.25)
    candle_range = max(row.High - row.Low, 0.25)
    upper_wick = row.High - max(row.Open, row.Close)
    close_low = (row.High - row.Close) / candle_range >= 0.65
    rejection = row.Close < row.Open and upper_wick >= 0.8 * body and close_low
    reclaim = previous.Close >= previous.EMA20 and row.Close < row.EMA20 and row.Close < row.Open
    return bool(rejection or reclaim)


def touched_support(h1: pd.DataFrame) -> bool:
    recent = h1.iloc[-3:]
    return bool(((recent.Low <= recent.EMA20) & (recent.High >= recent.EMA20)).any() or
                ((recent.Low <= recent.EMA50) & (recent.High >= recent.EMA50)).any())


def touched_resistance(h1: pd.DataFrame) -> bool:
    recent = h1.iloc[-3:]
    return bool(((recent.Low <= recent.EMA20) & (recent.High >= recent.EMA20)).any() or
                ((recent.Low <= recent.EMA50) & (recent.High >= recent.EMA50)).any())


def round_tick(value: float, tick: float, upward: bool) -> float:
    scaled = value / tick
    return (math.ceil(scaled) if upward else math.floor(scaled)) * tick


def build_signal(direction: str, h1: pd.DataFrame, cfg: dict, now: pd.Timestamp) -> tuple[Optional[Signal], str]:
    risk = cfg["risk"]
    filters = cfg["filters"]
    tick = float(risk["tick_size"])
    point_value = float(risk["point_value_usd"])
    row = h1.iloc[-1]
    swing = h1.iloc[-6:]

    if filters.get("require_volume_confirmation", False):
        if row.Volume < float(filters["volume_multiple"]) * row.VOL_MA:
            return None, "volum insuficient"

    if direction == "LONG":
        entry = round_tick(float(row.High) + tick, tick, True)
        stop = round_tick(float(swing.Low.min()) - 2 * tick, tick, False)
        risk_points = entry - stop
        next_barrier = float(h1.iloc[-21:-1].High.max())
        room = next_barrier - entry if next_barrier > entry else math.inf
    else:
        entry = round_tick(float(row.Low) - tick, tick, False)
        stop = round_tick(float(swing.High.max()) + 2 * tick, tick, True)
        risk_points = stop - entry
        next_barrier = float(h1.iloc[-21:-1].Low.min())
        room = entry - next_barrier if next_barrier < entry else math.inf

    entry_distance = abs(entry - float(row.Close))
    max_entry_distance = float(filters["max_entry_distance_atr"]) * float(row.ATR)
    if entry_distance > max_entry_distance:
        return None, f"trigger prea departe de inchidere ({entry_distance:.2f}p)"

    if risk_points < float(risk["min_stop_points"]):
        return None, f"stop prea mic ({risk_points:.2f}p)"
    if risk_points > float(risk["max_stop_points"]):
        return None, f"stop prea mare ({risk_points:.2f}p)"

    contracts = min(
        int(float(risk["max_risk_usd"]) // (risk_points * point_value)),
        int(risk["max_contracts"]),
    )
    if contracts < 1:
        return None, f"1 MES ar risca {risk_points * point_value:.2f} USD"

    rr = float(risk["min_rr"])
    reward_points = rr * risk_points
    # Rezistenta/suportul anterior trebuie sa permita cel putin 1.5R.
    if room < 1.5 * risk_points:
        return None, f"spatiu insuficient pana la bariera ({room:.2f}p)"

    target_raw = entry + reward_points if direction == "LONG" else entry - reward_points
    target = round_tick(target_raw, tick, direction == "LONG")
    expires = now + pd.Timedelta(hours=float(filters["signal_valid_hours"]))
    reason = "respingere/reclaim H1 dupa atingerea EMA, aliniata cu Daily si H4"
    return Signal(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        risk_points=risk_points,
        reward_points=reward_points,
        rr=rr,
        contracts=contracts,
        risk_usd=risk_points * point_value * contracts,
        created_at=now,
        expires_at=expires,
        reason=reason,
    ), "ok"


def evaluate(cfg: dict, now: Optional[pd.Timestamp] = None) -> tuple[Optional[Signal], str]:
    now = now or pd.Timestamp.now(tz=UTC)
    now_ny = now.tz_convert(NY).to_pydatetime()
    if not in_session(now_ny, cfg):
        return None, "in afara sesiunii configurate"
    blocked = blackout_label(now_ny, cfg)
    if blocked:
        return None, f"blackout activ: {blocked}"

    raw_h1 = remove_open_hour(download(cfg["symbol"], "60d", "1h"), now)
    daily = indicators(remove_open_daily(download(cfg["symbol"], "1y", "1d"), now))
    h4 = indicators(resample_h4(raw_h1))
    h1 = indicators(raw_h1)
    if len(daily) < 30 or len(h4) < 30 or len(h1) < 30:
        return None, "date insuficiente"

    d, four, one, previous = daily.iloc[-1], h4.iloc[-1], h1.iloc[-1], h1.iloc[-2]
    regime, regime_details, vix = market_regime()
    long_trend = d.Close > d.EMA50 and four.Close > four.EMA20 > four.EMA50 > four.EMA200
    short_trend = d.Close < d.EMA50 and four.Close < four.EMA20 < four.EMA50 < four.EMA200

    long_vix_ok = vix is None or vix <= float(cfg["filters"]["vix_long_limit"])
    short_vix_ok = vix is None or vix >= float(cfg["filters"]["vix_short_floor"])

    if cfg["filters"].get("allow_long", True) and regime == "BULL" and long_trend and long_vix_ok:
        if touched_support(h1) and bullish_confirmation(one, previous):
            signal, reason = build_signal("LONG", h1, cfg, now)
            return signal, reason if signal else f"LONG respins: {reason}"

    if cfg["filters"].get("allow_short", True) and regime == "BEAR" and short_trend and short_vix_ok:
        if touched_resistance(h1) and bearish_confirmation(one, previous):
            signal, reason = build_signal("SHORT", h1, cfg, now)
            return signal, reason if signal else f"SHORT respins: {reason}"

    return None, f"fara setup | {regime_details} | D close={d.Close:.2f} | H4 close={four.Close:.2f}"


def telegram_send(text: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
    if not token or not chat_id:
        print(text)
        return
    safe = html.escape(text, quote=False).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, json={"chat_id": chat_id, "text": safe, "parse_mode": "HTML"}, timeout=15)
    response.raise_for_status()


def signal_message(signal: Signal, cfg: dict) -> str:
    order = "BUY STOP" if signal.direction == "LONG" else "SELL STOP"
    expiry_ny = signal.expires_at.tz_convert(NY).strftime("%H:%M NY")
    return (
        f"✅ <b>MES PROP — SEMNAL VALID {signal.direction}</b>\n"
        f"Ordin conditionat: <b>{order} {signal.entry:.2f}</b>\n"
        f"SL: <b>{signal.stop:.2f}</b> | TP: <b>{signal.target:.2f}</b>\n"
        f"Cantitate: <b>{signal.contracts} MES</b>\n"
        f"Risc: <b>{signal.risk_usd:.2f} USD</b> ({signal.risk_points:.2f} puncte)\n"
        f"R/R: <b>1:{signal.rr:.2f}</b>\n"
        f"Expira: <b>{expiry_ny}</b> — anuleaza ordinul daca nu este activat.\n"
        f"Motiv: {signal.reason}\n"
        f"TV: {cfg['tradingview_symbol']}\n"
        "Regula: nu mari cantitatea si nu indeparta stopul."
    )


def can_emit(state: dict, cfg: dict, now: pd.Timestamp) -> bool:
    day = now.tz_convert(NY).strftime("%Y-%m-%d")
    if state.get("day") != day:
        state.clear()
        state.update({"day": day, "signals": 0, "last_bar": None})
    return int(state.get("signals", 0)) < int(cfg["filters"]["max_signals_per_day"])


def run_once(cfg: dict, state: dict) -> None:
    now = pd.Timestamp.now(tz=UTC)
    if not can_emit(state, cfg, now):
        print("Daily signal limit reached")
        return
    signal, status = evaluate(cfg, now)
    print(f"[{now.isoformat()}] {status}")
    if signal is None:
        return
    bar_key = signal.created_at.floor("h").isoformat() + ":" + signal.direction
    if state.get("last_bar") == bar_key:
        return
    telegram_send(signal_message(signal, cfg))
    state["signals"] = int(state.get("signals", 0)) + 1
    state["last_bar"] = bar_key
    save_json(STATE_PATH, state)


def main() -> None:
    parser = argparse.ArgumentParser(description="MES Prop Guard V2")
    parser.add_argument("--once", action="store_true", help="Ruleaza o singura scanare")
    args = parser.parse_args()
    write_default_config()
    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
    state = load_json(STATE_PATH, {"day": "", "signals": 0, "last_bar": None})
    print(f"MES Prop Guard V{VERSION} started")
    while True:
        try:
            run_once(cfg, state)
        except Exception as exc:
            print(f"Scan error: {type(exc).__name__}: {exc}")
        if args.once:
            break
        time.sleep(max(60, int(cfg.get("scan_minutes", 15)) * 60))
        cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)


if __name__ == "__main__":
    main()
