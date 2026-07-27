"""ETF Portfolio Steward V7.0

Long-term XTB portfolio assistant.

Key V7 changes
--------------
1. Reads the latest XTB account PDF directly:
   - balance / equity / free margin
   - open positions
   - pending BUY orders
2. Pending BUY orders are treated as committed cash and included in projected
   allocation, preventing duplicate purchases.
3. Manual overrides remain available for last-minute changes after the PDF was
   exported.
4. Generates one portfolio-level weekly deployment plan instead of assigning
   the full cash amount independently to several ETFs.
5. Never executes trades and never creates SL/TP for strategic holdings.

Colab example
-------------
!pip install pandas requests yfinance pdfplumber
!python etf_portfolio_steward_v7.py \
    --config portfolio_v7.json \
    --account-pdf "account_latest.pdf" \
    --once --telegram
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

try:
    import pdfplumber
except ImportError as exc:
    raise SystemExit("Install dependency: pip install pdfplumber") from exc


VERSION = "7.0.0"
STATE_PATH = Path("etf_steward_v7_state.json")
_CACHE: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}


@dataclass(frozen=True)
class Instrument:
    key: str
    xtb_symbols: tuple[str, ...]
    yf_symbol: str
    sleeve: str
    target_weight: float
    allow_buy: bool = True
    currency: str = "EUR"


@dataclass
class Position:
    position_id: str
    symbol: str
    qty: float
    open_price: float
    market_price: float
    purchase_value: float
    gross_pl: float


@dataclass
class PendingOrder:
    order_id: str
    symbol: str
    qty: float
    price: float
    side: str
    order_type: str


@dataclass
class AccountSnapshot:
    exported_at: datetime
    balance_eur: float
    equity_eur: float
    free_cash_eur: float
    positions: list[Position] = field(default_factory=list)
    pending_orders: list[PendingOrder] = field(default_factory=list)


@dataclass(frozen=True)
class MarketSnapshot:
    close: float
    ema20: float
    ema50: float
    ema200: float
    atr20: float
    rsi14: float
    weekly_close: float
    weekly_ema40: float


@dataclass
class PortfolioRow:
    key: str
    sleeve: str
    target_weight: float
    current_value: float
    pending_value: float
    projected_value: float
    actual_weight: float
    projected_weight: float
    gap_eur: float
    decision: str
    reason: str
    score: int
    proposed_eur: float = 0.0


def load_config(path: str | Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if not {"settings", "instruments"}.issubset(cfg):
        raise ValueError("Config requires 'settings' and 'instruments'.")
    total = sum(float(x["target_weight"]) for x in cfg["instruments"])
    if not math.isclose(total, 1.0, abs_tol=0.0001):
        raise ValueError(f"Target weights must total 100%; currently {total:.2%}.")
    return cfg


def instruments_from_config(cfg: dict) -> list[Instrument]:
    result: list[Instrument] = []
    for item in cfg["instruments"]:
        symbols = item.get("xtb_symbols") or [item["key"]]
        result.append(
            Instrument(
                key=str(item["key"]),
                xtb_symbols=tuple(str(x).upper() for x in symbols),
                yf_symbol=str(item["yf_symbol"]),
                sleeve=str(item["sleeve"]),
                target_weight=float(item["target_weight"]),
                allow_buy=bool(item.get("allow_buy", True)),
                currency=str(item.get("currency", "EUR")).upper(),
            )
        )
    return result


_FLOAT = r"-?\d+(?:\.\d+)?"


def _extract_header(text: str) -> tuple[datetime, float, float, float]:
    stamp_match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})", text)
    if not stamp_match:
        raise ValueError("Could not read export timestamp from XTB PDF.")
    exported_at = datetime.strptime(
        f"{stamp_match.group(1)} {stamp_match.group(2)}", "%d/%m/%Y %H:%M:%S"
    )

    marker = re.search(
        rf"Balance\s+Equity\s+Margin\s+Free margin\s+Margin level\s+"
        rf"({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})",
        text,
        flags=re.IGNORECASE,
    )
    if not marker:
        raise ValueError("Could not read balance/equity/free margin from XTB PDF.")
    balance = float(marker.group(1))
    equity = float(marker.group(2))
    free_cash = float(marker.group(4))
    return exported_at, balance, equity, free_cash


def _parse_open_positions(text: str) -> list[Position]:
    positions: list[Position] = []
    in_section = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if "OPEN POSITION HISTORY" in line:
            in_section = True
            continue
        if in_section and (
            "PENDING ORDERS HISTORY" in line
            or "CASH OPERATION HISTORY" in line
            or line.startswith("Total ")
        ):
            break
        if not in_section:
            continue

        # XTB row:
        # id symbol BUY qty date time open market purchase ... grossPL
        match = re.match(
            rf"^(\d+)\s+([A-Z0-9._-]+)\s+(BUY|SELL)\s+({_FLOAT})\s+"
            rf"\d{{2}}/\d{{2}}/\d{{4}}\s+\d{{2}}:\d{{2}}:\d{{2}}\s+"
            rf"({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+"
            rf"(?:{_FLOAT}\s+){{4,7}}({_FLOAT})(?:\s|$)",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            positions.append(
                Position(
                    position_id=match.group(1),
                    symbol=match.group(2).upper(),
                    qty=float(match.group(4)),
                    open_price=float(match.group(5)),
                    market_price=float(match.group(6)),
                    purchase_value=float(match.group(7)),
                    gross_pl=float(match.group(8)),
                )
            )
    return positions


def _parse_pending_orders(text: str) -> list[PendingOrder]:
    orders: list[PendingOrder] = []
    in_section = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if "PENDING ORDERS HISTORY" in line:
            in_section = True
            continue
        if in_section and "CASH OPERATION HISTORY" in line:
            break
        if not in_section:
            continue

        # PDF extraction may place columns in slightly different order.
        # Minimum reliable fields: ID, symbol, qty, price, order type, BUY/SELL.
        match = re.match(
            rf"^(\d+)\s+([A-Z0-9._-]+)\s+({_FLOAT})\s+({_FLOAT})\s+"
            rf"({_FLOAT})\s+({_FLOAT})\s+(limit|stop)\s+.*?\s+(BUY|SELL)\b",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            orders.append(
                PendingOrder(
                    order_id=match.group(1),
                    symbol=match.group(2).upper(),
                    qty=float(match.group(3)),
                    price=float(match.group(5)),
                    order_type=match.group(7).lower(),
                    side=match.group(8).upper(),
                )
            )
    return orders


def parse_xtb_pdf(path: str | Path) -> AccountSnapshot:
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    full_text = "\n".join(pages)
    exported_at, balance, equity, free_cash = _extract_header(full_text)
    return AccountSnapshot(
        exported_at=exported_at,
        balance_eur=balance,
        equity_eur=equity,
        free_cash_eur=free_cash,
        positions=_parse_open_positions(full_text),
        pending_orders=_parse_pending_orders(full_text),
    )


def apply_overrides(account: AccountSnapshot, cfg: dict) -> AccountSnapshot:
    """Apply only explicit, current overrides.

    Example:
      "overrides": {
        "free_cash_eur": 150.0,
        "equity_eur": null,
        "ignore_pending_order_ids": ["123"],
        "extra_pending_orders": [
          {"symbol":"IS3Q.DE","qty":0.26,"price":76.60,"side":"BUY","order_type":"limit"}
        ]
      }
    """
    o = cfg.get("overrides", {})
    if o.get("free_cash_eur") is not None:
        account.free_cash_eur = float(o["free_cash_eur"])
    if o.get("equity_eur") is not None:
        account.equity_eur = float(o["equity_eur"])

    ignored = {str(x) for x in o.get("ignore_pending_order_ids", [])}
    account.pending_orders = [
        x for x in account.pending_orders if x.order_id not in ignored
    ]

    for index, item in enumerate(o.get("extra_pending_orders", []), start=1):
        account.pending_orders.append(
            PendingOrder(
                order_id=f"manual-{index}",
                symbol=str(item["symbol"]).upper(),
                qty=float(item["qty"]),
                price=float(item["price"]),
                side=str(item.get("side", "BUY")).upper(),
                order_type=str(item.get("order_type", "limit")).lower(),
            )
        )
    return account


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
    # Use closed daily bars only.
    if len(frame) and pd.Timestamp(frame.index[-1]).date() >= date.today():
        frame = frame.iloc[:-1]
    _CACHE[key] = (time.time(), frame.copy())
    return frame


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    out = df.copy()
    for length in (20, 50, 200):
        out[f"EMA{length}"] = out.Close.ewm(span=length, adjust=False).mean()
    prev = out.Close.shift(1)
    tr = pd.concat(
        [(out.High - out.Low), (out.High - prev).abs(), (out.Low - prev).abs()],
        axis=1,
    ).max(axis=1)
    out["ATR20"] = tr.rolling(20).mean()
    delta = out.Close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["RSI14"] = (100 - 100 / (1 + rs)).fillna(50.0)
    return out.dropna()


def market_snapshot(symbol: str) -> Optional[MarketSnapshot]:
    daily = add_indicators(download(symbol))
    if len(daily) < 40:
        return None
    weekly = daily.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()
    weekly["EMA40"] = weekly.Close.ewm(span=40, adjust=False).mean()
    if len(weekly) < 40:
        return None
    d, w = daily.iloc[-1], weekly.iloc[-1]
    return MarketSnapshot(
        close=float(d.Close),
        ema20=float(d.EMA20),
        ema50=float(d.EMA50),
        ema200=float(d.EMA200),
        atr20=float(d.ATR20),
        rsi14=float(d.RSI14),
        weekly_close=float(w.Close),
        weekly_ema40=float(w.EMA40),
    )


def eur_rate(currency: str) -> Optional[float]:
    currency = currency.upper()
    if currency == "EUR":
        return 1.0
    direct = download(f"{currency}EUR=X", "1mo", "1d")
    if not direct.empty:
        return float(direct.iloc[-1].Close)
    inverse = download(f"EUR{currency}=X", "1mo", "1d")
    if not inverse.empty and float(inverse.iloc[-1].Close) > 0:
        return 1.0 / float(inverse.iloc[-1].Close)
    return None


def dynamic_regime() -> tuple[str, int, str]:
    score = 0
    notes: list[str] = []
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

    regime = (
        "STRONG RISK ON" if score >= 90
        else "RISK ON" if score >= 70
        else "NEUTRAL" if score >= 45
        else "RISK OFF"
    )
    return regime, score, "; ".join(notes)


def values_from_account(
    account: AccountSnapshot,
    instruments: list[Instrument],
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    symbol_to_key: dict[str, str] = {}
    for inst in instruments:
        for symbol in inst.xtb_symbols:
            symbol_to_key[symbol] = inst.key

    current = {inst.key: 0.0 for inst in instruments}
    pending = {inst.key: 0.0 for inst in instruments}
    warnings: list[str] = []

    for pos in account.positions:
        key = symbol_to_key.get(pos.symbol)
        if key is None:
            warnings.append(f"Unmapped open position: {pos.symbol}")
            continue
        current[key] += pos.qty * pos.market_price

    for order in account.pending_orders:
        if order.side != "BUY":
            continue
        key = symbol_to_key.get(order.symbol)
        if key is None:
            warnings.append(f"Unmapped pending order: {order.symbol}")
            continue
        pending[key] += order.qty * order.price

    return current, pending, warnings


def score_and_decision(
    inst: Instrument,
    actual_weight: float,
    projected_weight: float,
    gap_weight: float,
    snap: Optional[MarketSnapshot],
    regime: str,
    cfg: dict,
) -> tuple[int, str, str, float]:
    s = cfg["settings"]
    band = float(s["rebalance_band_abs"])

    if not inst.allow_buy:
        return 0, "REVIEW", "legacy holding; purchases disabled", 0.0
    if gap_weight < -band:
        return 0, "REBALANCE REVIEW", "projected allocation is above target band", 0.0
    if gap_weight <= band:
        return 30, "HOLD", "projected allocation is inside target band", 0.0
    if snap is None:
        return 0, "PAUSE", "reliable market data unavailable", 0.0

    score = 0
    reasons: list[str] = []

    # Allocation: max 40
    allocation_score = min(40, max(0, round(gap_weight / max(inst.target_weight, 0.01) * 40)))
    score += allocation_score
    reasons.append(f"underweight by {gap_weight:.1%}")

    # Daily/weekly trend: max 35
    weekly_ok = snap.weekly_close >= snap.weekly_ema40
    if snap.close >= snap.ema200:
        score += 12
    if snap.close >= snap.ema50:
        score += 10
    if snap.ema20 >= snap.ema50:
        score += 7
    if weekly_ok:
        score += 6

    # Regime: max 15
    if regime == "STRONG RISK ON":
        score += 15
    elif regime == "RISK ON":
        score += 12
    elif regime == "NEUTRAL":
        score += 5

    # Entry quality: max 10, with extension penalty
    extended = snap.close > snap.ema20 + float(s["extended_atr_multiple"]) * snap.atr20
    if extended or snap.rsi14 >= float(s.get("rsi_wait_level", 72)):
        score -= 20
        reasons.append("price is extended")
    elif snap.close <= snap.ema20 + 0.35 * snap.atr20:
        score += 10
        reasons.append("price is near EMA20")
    else:
        score += 5

    if inst.sleeve == "satellite":
        aligned = snap.close > snap.ema50 > snap.ema200 and weekly_ok
        if regime not in {"RISK ON", "STRONG RISK ON"} or not aligned:
            return min(score, 55), "PAUSE", "satellite trend/regime is not fully aligned", 0.0

    score = max(0, min(100, score))
    if score >= int(s["execute_score"]):
        return score, "ACCUMULATE", "; ".join(reasons), 1.0
    if score >= int(s["small_score"]):
        return score, "ACCUMULATE SMALL", "; ".join(reasons), float(s["small_order_multiplier"])
    if score >= int(s["wait_score"]):
        return score, "WAIT", "; ".join(reasons), 0.0
    return score, "HOLD", "; ".join(reasons), 0.0


def allocate_cash(rows: list[PortfolioRow], uncommitted_cash: float, cfg: dict) -> None:
    """Allocate cash once across all eligible rows.

    This fixes the V6 issue where each instrument could appear to receive the
    same deployable cash independently.
    """
    s = cfg["settings"]
    weekly_cap = min(
        uncommitted_cash,
        float(s["max_weekly_deployment_eur"]),
        uncommitted_cash * float(s["deployable_fraction"]),
    )
    if weekly_cap < float(s["min_order_eur"]):
        return

    candidates = [
        r for r in rows
        if r.decision in {"ACCUMULATE", "ACCUMULATE SMALL"} and r.gap_eur > 0
    ]
    candidates.sort(key=lambda r: (r.score, r.gap_eur), reverse=True)

    remaining = weekly_cap
    max_orders = int(s["max_new_orders_per_week"])
    orders_used = 0
    for row in candidates:
        if remaining < float(s["min_order_eur"]) or orders_used >= max_orders:
            break
        multiplier = (
            1.0 if row.decision == "ACCUMULATE"
            else float(s["small_order_multiplier"])
        )
        proposed = min(
            remaining,
            row.gap_eur,
            float(s["max_order_eur"]) * multiplier,
        )
        if proposed >= float(s["min_order_eur"]):
            row.proposed_eur = round(proposed, 2)
            remaining -= proposed
            orders_used += 1


def build_report(config_path: str | Path, account_pdf: str | Path) -> str:
    cfg = load_config(config_path)
    instruments = instruments_from_config(cfg)
    account = apply_overrides(parse_xtb_pdf(account_pdf), cfg)

    age_hours = (datetime.now() - account.exported_at).total_seconds() / 3600
    stale = age_hours > float(cfg["settings"]["max_snapshot_age_hours"])

    regime, regime_score, regime_notes = dynamic_regime()
    current, pending, warnings = values_from_account(account, instruments)
    market = {inst.key: market_snapshot(inst.yf_symbol) for inst in instruments}

    pending_total = sum(pending.values())
    uncommitted_cash = max(0.0, account.free_cash_eur - pending_total)

    rows: list[PortfolioRow] = []
    for inst in instruments:
        current_value = current.get(inst.key, 0.0)
        pending_value = pending.get(inst.key, 0.0)
        projected_value = current_value + pending_value
        actual_weight = current_value / account.equity_eur if account.equity_eur else 0.0
        projected_weight = projected_value / account.equity_eur if account.equity_eur else 0.0
        gap_weight = inst.target_weight - projected_weight
        gap_eur = max(0.0, inst.target_weight * account.equity_eur - projected_value)

        if stale:
            score, decision, reason, _ = 0, "PAUSE", "account PDF is stale", 0.0
        else:
            score, decision, reason, _ = score_and_decision(
                inst,
                actual_weight,
                projected_weight,
                gap_weight,
                market.get(inst.key),
                regime,
                cfg,
            )

        rows.append(
            PortfolioRow(
                key=inst.key,
                sleeve=inst.sleeve,
                target_weight=inst.target_weight,
                current_value=current_value,
                pending_value=pending_value,
                projected_value=projected_value,
                actual_weight=actual_weight,
                projected_weight=projected_weight,
                gap_eur=gap_eur,
                decision=decision,
                reason=reason,
                score=score,
            )
        )

    allocate_cash(rows, uncommitted_cash, cfg)
    rows.sort(key=lambda x: (x.proposed_eur > 0, x.score, x.gap_eur), reverse=True)

    lines = [
        f"📊 ETF Portfolio Steward V{VERSION}",
        "Latest XTB snapshot → pending-order awareness → weekly capital deployment",
        "",
        "🌍 Market",
        f"Regime: {regime} ({regime_score}/100) | {regime_notes}",
        "",
        "💰 Portfolio",
        f"Snapshot: {account.exported_at:%Y-%m-%d %H:%M} ({age_hours:.1f}h old)",
        f"Balance: €{account.balance_eur:.2f} | Equity: €{account.equity_eur:.2f}",
        f"Free cash: €{account.free_cash_eur:.2f}",
        f"Pending BUY commitments: €{pending_total:.2f}",
        f"Uncommitted cash: €{uncommitted_cash:.2f}",
    ]
    if stale:
        lines.append("🔴 PAUSE: export a fresh XTB statement before acting.")
    if warnings:
        lines.append("⚠️ Mapping: " + " | ".join(sorted(set(warnings))))

    lines.extend(["", "🧭 Decisions (pending orders included)"])
    icons = {
        "ACCUMULATE": "🟢",
        "ACCUMULATE SMALL": "🟢",
        "WAIT": "🟡",
        "PAUSE": "🔴",
        "REBALANCE REVIEW": "🟠",
        "REVIEW": "🟠",
        "HOLD": "⚪",
    }
    for row in rows:
        lines.append(
            f"{icons.get(row.decision, '⚪')} {row.key:<11} {row.decision:<17} "
            f"score {row.score:>3}/100 | target {row.target_weight:>5.1%} | "
            f"actual {row.actual_weight:>5.1%} | projected {row.projected_weight:>5.1%}"
        )
        if row.pending_value > 0:
            lines.append(f"   Pending BUY already counted: €{row.pending_value:.2f}")
        lines.append(f"   Gap after pending orders: €{row.gap_eur:.2f} | {row.reason}")
        if row.proposed_eur:
            lines.append(f"   Proposed NEW contribution this week: €{row.proposed_eur:.2f}")

    total_proposed = sum(x.proposed_eur for x in rows)
    hold_cash = max(0.0, uncommitted_cash - total_proposed)
    lines.extend(
        [
            "",
            "🪙 Liquidity plan",
            f"New deployment proposed: €{total_proposed:.2f}",
            f"Cash retained: €{hold_cash:.2f}",
            "",
            "📌 Rules",
            "• Pending BUY orders count toward projected allocation and committed cash.",
            "• One portfolio-level deployment budget per week; cash is not duplicated across ETFs.",
            "• No automatic sale, stop-loss or take-profit for strategic ETF holdings.",
            "• REVIEW is not a sell instruction.",
            "• Export a new XTB PDF after executions, cancellations or accidental closures.",
        ]
    )
    return "\n".join(lines)


def send_telegram_if_changed(report: str) -> bool:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
    state: dict = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    if state.get("digest") == digest:
        return False

    ok = True
    for start in range(0, len(report), 3900):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": report[start:start + 3900]},
                timeout=15,
            )
            ok = ok and response.status_code == 200
            if response.status_code != 200:
                print(f"Telegram HTTP {response.status_code}: {response.text[:300]}")
        except Exception as exc:
            print(f"Telegram error: {exc}")
            ok = False

    if ok:
        STATE_PATH.write_text(
            json.dumps(
                {"digest": digest, "sent_at": datetime.now().isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="portfolio_v7.json")
    parser.add_argument("--account-pdf", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--sleep", type=int, default=21600)
    args = parser.parse_args()

    while True:
        report = build_report(args.config, args.account_pdf)
        print(report)
        if args.telegram:
            print(f"Telegram sent: {send_telegram_if_changed(report)}")
        if args.once:
            break
        time.sleep(max(3600, args.sleep))


if __name__ == "__main__":
    main()
