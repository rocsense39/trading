"""ETF Portfolio Steward V6.0 - long-term XTB portfolio assistant.

The bot does not execute trades. It uses closed daily candles, portfolio
allocation, a dynamic market regime and persistent alert deduplication.
It intentionally does NOT create stop-loss or take-profit levels for long-term
ETF holdings.

Colab:
    !pip install pandas requests yfinance
    !python etf_bot_v6_long_term.py --config portfolio_v6_long_term.json --once
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf


VERSION = "6.0.0"
STATE_PATH = Path("etf_bot_v6_state.json")
_CACHE: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}


@dataclass(frozen=True)
class Position:
    xtb_symbol: str
    yf_symbol: str
    qty: float
    currency: str


@dataclass(frozen=True)
class Instrument:
    key: str
    sleeve: str
    target_weight: float
    allow_buy: bool
    positions: tuple[Position, ...]


@dataclass(frozen=True)
class Snapshot:
    close: float
    ema20: float
    ema50: float
    ema200: float
    atr20: float
    rsi14: float
    weekly_close: float
    weekly_ema40: float
    source: str


@dataclass
class Row:
    key: str
    sleeve: str
    target_weight: float
    actual_weight: float
    value_eur: float
    gap_eur: float
    gap_weight: float
    decision: str
    reason: str
    order_eur: float = 0.0


def load_config(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    required = {"settings", "instruments"}
    if not required.issubset(cfg):
        raise ValueError("Config requires settings and instruments")
    total = sum(float(item["target_weight"]) for item in cfg["instruments"])
    if not math.isclose(total, 1.0, abs_tol=0.0001):
        raise ValueError(f"Target weights must total 100%, currently {total:.2%}")
    return cfg


def instruments_from_config(cfg: dict) -> list[Instrument]:
    result = []
    for item in cfg["instruments"]:
        positions = tuple(Position(**p) for p in item.get("positions", []))
        result.append(
            Instrument(
                key=item["key"],
                sleeve=item["sleeve"],
                target_weight=float(item["target_weight"]),
                allow_buy=bool(item.get("allow_buy", True)),
                positions=positions,
            )
        )
    return result


def download(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    key = (symbol, period, interval)
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < 1800:
        return cached[1].copy()
    frame = pd.DataFrame()
    for attempt in range(2):
        try:
            frame = yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=15,
            )
            if frame is not None and not frame.empty:
                break
        except Exception as exc:
            print(f"Data warning {symbol}: {exc}")
        if attempt == 0:
            time.sleep(4)
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [c[0] for c in frame.columns]
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not set(needed).issubset(frame.columns):
        return pd.DataFrame()
    frame = frame[needed].dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
    # Daily Yahoo bar for today may still be changing. Use closed bars only.
    if len(frame) and pd.Timestamp(frame.index[-1]).date() >= date.today():
        frame = frame.iloc[:-1]
    _CACHE[key] = (time.time(), frame.copy())
    return frame


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or not {"Open", "High", "Low", "Close"}.issubset(df.columns):
        return pd.DataFrame()
    out = df.copy()
    for length in (20, 50, 200):
        out[f"EMA{length}"] = out.Close.ewm(span=length, adjust=False).mean()
    prev = out.Close.shift(1)
    tr = pd.concat(
        [(out.High - out.Low), (out.High - prev).abs(), (out.Low - prev).abs()], axis=1
    ).max(axis=1)
    out["ATR20"] = tr.rolling(20).mean()
    delta = out.Close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["RSI14"] = (100 - 100 / (1 + rs)).fillna(50.0)
    return out.dropna()


def snapshot(symbol: str) -> Optional[Snapshot]:
    daily = add_indicators(download(symbol))
    if len(daily) < 30:
        return None
    weekly = daily.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()
    weekly["EMA40"] = weekly.Close.ewm(span=40, adjust=False).mean()
    if len(weekly) < 40:
        return None
    d, w = daily.iloc[-1], weekly.iloc[-1]
    return Snapshot(
        close=float(d.Close),
        ema20=float(d.EMA20),
        ema50=float(d.EMA50),
        ema200=float(d.EMA200),
        atr20=float(d.ATR20),
        rsi14=float(d.RSI14),
        weekly_close=float(w.Close),
        weekly_ema40=float(w.EMA40),
        source="yahoo_closed_daily",
    )


def eur_rate(currency: str) -> Optional[float]:
    """Return EUR value of one currency unit."""
    currency = currency.upper()
    if currency == "EUR":
        return 1.0
    symbol = f"{currency}EUR=X"
    df = download(symbol, "1mo", "1d")
    if not df.empty:
        return float(df.iloc[-1].Close)
    # Inverse is a safe second route (e.g. EURUSD=X).
    inverse = download(f"EUR{currency}=X", "1mo", "1d")
    if not inverse.empty and float(inverse.iloc[-1].Close) > 0:
        return 1.0 / float(inverse.iloc[-1].Close)
    return None


def dynamic_regime() -> tuple[str, int, str]:
    score = 0
    notes = []
    for label, symbol in (("SPY", "SPY"), ("QQQ", "QQQ")):
        df = add_indicators(download(symbol))
        if len(df) < 25:
            notes.append(f"{label}=n/a")
            continue
        row = df.iloc[-1]
        slope = float(df.iloc[-1].EMA50 - df.iloc[-21].EMA50)
        if row.Close > row.EMA200:
            score += 25
        if row.Close > row.EMA50 and slope > 0:
            score += 15
        notes.append(f"{label}={'bull' if row.Close > row.EMA50 else 'weak'}")
    vix = download("^VIX", "6mo", "1d")
    if not vix.empty:
        value = float(vix.iloc[-1].Close)
        score += 20 if value < 25 else 10 if value < 32 else 0
        notes.append(f"VIX={value:.1f}")
    regime = "RISK ON" if score >= 70 else "NEUTRAL" if score >= 45 else "RISK OFF"
    return regime, score, "; ".join(notes)


def config_age_days(cfg: dict) -> int:
    as_of = datetime.strptime(cfg["settings"]["holdings_as_of"], "%Y-%m-%d").date()
    return (date.today() - as_of).days


def current_values(
    instruments: list[Instrument],
) -> tuple[dict[str, float], dict[str, Snapshot], list[str]]:
    values: dict[str, float] = {}
    snaps: dict[str, Snapshot] = {}
    warnings: list[str] = []
    for inst in instruments:
        total = 0.0
        representative: Optional[Snapshot] = None
        for pos in inst.positions:
            snap = snapshot(pos.yf_symbol)
            fx = eur_rate(pos.currency)
            if snap is None or fx is None:
                warnings.append(f"{inst.key}: missing data for {pos.yf_symbol}/{pos.currency}")
                continue
            total += pos.qty * snap.close * fx
            representative = representative or snap
        values[inst.key] = total
        if representative:
            snaps[inst.key] = representative
    return values, snaps, warnings


def decision_for(
    inst: Instrument,
    actual_weight: float,
    gap_weight: float,
    snap: Optional[Snapshot],
    regime: str,
    cfg: dict,
    stale: bool,
) -> tuple[str, str, float]:
    s = cfg["settings"]
    band = float(s["rebalance_band_abs"])
    if stale:
        return "PAUSE", "holdings configuration is stale", 0.0
    if not inst.allow_buy:
        return "REVIEW", "legacy/non-strategic holding; no automatic purchase", 0.0
    if inst.target_weight == 0:
        return "REVIEW", "zero strategic target; manual review only", 0.0
    if gap_weight < -band:
        return "REBALANCE REVIEW", "above target band; do not sell automatically", 0.0
    if gap_weight <= band:
        return "HOLD", "inside allocation band", 0.0
    if snap is None:
        return "PAUSE", "reliable market data unavailable", 0.0
    if inst.sleeve == "reserve":
        return "ACCUMULATE", "reserve sleeve is underweight", 1.0
    extended = snap.close > snap.ema20 + float(s["extended_atr_multiple"]) * snap.atr20
    weekly_ok = snap.weekly_close >= snap.weekly_ema40
    daily_ok = snap.close >= snap.ema200
    if extended or snap.rsi14 >= 72:
        return "WAIT", "underweight but price is extended", 0.0
    if inst.sleeve == "satellite":
        if regime != "RISK ON" or not (snap.close > snap.ema50 > snap.ema200 and weekly_ok):
            return "PAUSE", "satellite requires risk-on plus aligned Daily/Weekly trend", 0.0
        return "ACCUMULATE", "underweight satellite with aligned trend", 1.0
    if regime == "RISK OFF" or not daily_ok or not weekly_ok:
        multiplier = float(s.get("core_risk_off_multiplier", 0.5))
        if multiplier <= 0:
            return "WAIT", "underweight core, but long-term trend/regime is weak", 0.0
        return "ACCUMULATE SMALL", "underweight core during weak regime", multiplier
    return "ACCUMULATE", "underweight and Daily/Weekly conditions acceptable", 1.0


def build_report(config_path: str | Path) -> str:
    cfg = load_config(config_path)
    s = cfg["settings"]
    instruments = instruments_from_config(cfg)
    equity = float(s["equity_eur"])
    free_cash = float(s["free_cash_eur"])
    stale_days = config_age_days(cfg)
    stale = stale_days > int(s["max_config_age_days"])
    regime, regime_score, regime_notes = dynamic_regime()
    values, snaps, warnings = current_values(instruments)

    reserve_value = sum(values[i.key] for i in instruments if i.sleeve == "reserve")
    reserve_target = equity * float(s["cash_reserve_pct"])
    cash_needed = max(0.0, reserve_target - reserve_value)
    deployable = max(0.0, free_cash - cash_needed)

    rows: list[Row] = []
    for inst in instruments:
        value = values.get(inst.key, 0.0)
        actual = value / equity if equity else 0.0
        gap_weight = inst.target_weight - actual
        gap_eur = inst.target_weight * equity - value
        decision, reason, multiplier = decision_for(
            inst, actual, gap_weight, snaps.get(inst.key), regime, cfg, stale
        )
        order = 0.0
        if decision.startswith("ACCUMULATE"):
            order = min(max(0.0, gap_eur), deployable, float(s["max_order_eur"])) * multiplier
            if order < float(s["min_order_eur"]):
                reason += f"; available order €{order:.2f} is below minimum"
                decision = "HOLD CASH"
                order = 0.0
        rows.append(Row(inst.key, inst.sleeve, inst.target_weight, actual, value, gap_eur, gap_weight, decision, reason, order))

    priority = {"ACCUMULATE": 5, "ACCUMULATE SMALL": 4, "WAIT": 3, "PAUSE": 2, "REBALANCE REVIEW": 2, "REVIEW": 2, "HOLD CASH": 1, "HOLD": 0}
    rows.sort(key=lambda r: (priority.get(r.decision, 0), r.gap_eur), reverse=True)

    lines = [
        f"📊 ETF Portfolio Steward V{VERSION}",
        "Long-term allocation → Daily/Weekly trend → controlled contribution",
        "",
        "🌍 Market",
        f"Regime: {regime} ({regime_score}/100) | {regime_notes}",
        "",
        "💰 Portfolio",
        f"Equity: €{equity:.2f} | Free cash: €{free_cash:.2f}",
        f"Reserve assets: €{reserve_value:.2f} | Reserve target: €{reserve_target:.2f}",
        f"Deployable cash: €{deployable:.2f}",
        f"Holdings updated: {s['holdings_as_of']} ({stale_days} days ago)",
    ]
    if stale:
        lines.append("🔴 PAUSE: update quantities/equity/cash before any purchase.")
    if warnings:
        lines.append("⚠️ Data: " + " | ".join(warnings))
    lines.extend(["", "🧭 Decisions"])
    icons = {"ACCUMULATE": "🟢", "ACCUMULATE SMALL": "🟢", "WAIT": "🟡", "PAUSE": "🔴", "REBALANCE REVIEW": "🟠", "REVIEW": "🟠", "HOLD CASH": "⚪", "HOLD": "⚪"}
    for row in rows:
        lines.append(
            f"{icons.get(row.decision, '⚪')} {row.key:<9} {row.decision:<16} "
            f"target {row.target_weight:>5.1%} | actual {row.actual_weight:>5.1%} | gap {row.gap_eur:+.2f} EUR"
        )
        lines.append(f"   {row.reason}")
        if row.order_eur:
            lines.append(f"   Proposed contribution: €{row.order_eur:.2f} (no SL/TP)")
    lines.extend(
        [
            "",
            "📌 Rules",
            "• No automatic sale, stop-loss or take-profit for strategic ETF holdings.",
            "• Update account quantities after every executed order.",
            "• One contribution decision per week; ignore intraday candle noise.",
            "• REVIEW is not a sell instruction.",
        ]
    )
    return "\n".join(lines)


def send_telegram_if_changed(report: str) -> bool:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    if state.get("digest") == digest:
        return False
    if not token or not chat_id:
        return False
    ok = True
    for start in range(0, len(report), 3900):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": report[start : start + 3900]},
                timeout=15,
            )
            ok = ok and response.status_code == 200
        except Exception:
            ok = False
    if ok:
        STATE_PATH.write_text(json.dumps({"digest": digest, "sent_at": datetime.now().isoformat()}), encoding="utf-8")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="portfolio_v6_long_term.json")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--sleep", type=int, default=21600, help="Loop delay; default six hours")
    args = parser.parse_args()
    while True:
        report = build_report(args.config)
        print(report)
        if args.telegram:
            print(f"Telegram sent: {send_telegram_if_changed(report)}")
        if args.once:
            break
        time.sleep(max(3600, args.sleep))


if __name__ == "__main__":
    main()
