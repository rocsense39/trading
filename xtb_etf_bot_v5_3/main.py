from __future__ import annotations

import argparse
import time
from pathlib import Path

from core.config import BotConfig
from core.allocation import build_allocation_rows, deployable_cash, size_order
from market.data import fetch_all
from strategy.scoring import rank_candidates
from strategy.sltp import build_trade_plan
from reports.telegram import send_telegram


def fmt(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{float(x):.2f}"


def eur(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"€{float(x):.2f}"


def decision_icon(decision: str) -> str:
    if decision == "BUY":
        return "🟢"
    if decision == "WATCH":
        return "🟡"
    return "⚪"


def build_report(config_path: str | Path = "config/portfolio.json") -> str:
    cfg = BotConfig.from_file(Path(config_path))
    s = cfg.settings

    equity = float(s["equity_eur"])
    free_cash = float(s["free_cash_eur"])
    cash_reserve_pct = float(s["cash_reserve_pct"])
    min_order_eur = float(s["min_order_eur"])
    max_order_eur = float(s["max_order_eur"])

    deployable, reserve = deployable_cash(equity, free_cash, cash_reserve_pct)

    snapshots = fetch_all(cfg.instruments, s.get("period", "9mo"), s.get("interval", "1h"))
    rows = build_allocation_rows(equity, cfg.instruments, snapshots)
    instruments = {i.key: i for i in cfg.instruments}

    # V5.3 keeps regime static; dynamic regime comes in the next release.
    regime = "RISK ON"
    regime_score = 90
    ranked = rank_candidates(rows, instruments, snapshots, regime=regime, regime_score=regime_score)

    lines: list[str] = []
    lines.append("📊 ETF Bot V5.3")
    lines.append("3-gate decision engine: Allocation → Trend → Candle confirmation")
    lines.append("")

    lines.append("🟢 Market")
    lines.append(f"Regime: {regime} ({regime_score}/100)")
    lines.append("")

    lines.append("💰 Portfolio")
    lines.append(f"Equity: {eur(equity)}")
    lines.append(f"Free cash: {eur(free_cash)}")
    lines.append(f"Reserve: {eur(reserve)}")
    lines.append(f"Deployable: {eur(deployable)}")
    lines.append("")

    lines.append("🚦 Gate decisions")
    for c in ranked:
        lines.append(f"{decision_icon(c.decision)} {c.key:<8} {c.decision:<5} | confidence {c.confidence:>3}%")
        lines.append(f"   Portfolio: {c.portfolio_gate} | Trend: {c.trend_gate} | Candle: {c.confirmation_gate}")
        if c.confirmations:
            lines.append(f"   Pattern: {', '.join(c.confirmations)}")
    lines.append("")

    # BUY requires all three gates. WATCH means allocation + trend passed, but candle confirmation is missing.
    buy = next((c for c in ranked if c.decision == "BUY"), None)
    watch = next((c for c in ranked if c.decision == "WATCH"), None)

    if not buy:
        lines.append("⚪ No confirmed BUY today.")
        lines.append("")
        if watch:
            lines.append("🟡 Best watchlist candidate")
            lines.append(f"ETF: {watch.key}")
            lines.append("Reason: allocation and trend are acceptable, but no bullish candle confirmation yet.")
            lines.append("Action: wait for hammer, bullish engulfing, morning star, inside-bar breakout, or strong bullish candle.")
        else:
            lines.append("Reason: no ETF passed the allocation + trend gates.")
        lines.append("")
        lines.append("📌 Allocation gaps")
        for r in rows:
            lines.append(f"{r.key:<8} target {r.target_weight:>5.1%} | actual {r.actual_weight:>5.1%} | gap {r.gap_eur:+.2f} EUR")
        return "\n".join(lines)

    row = next(r for r in rows if r.key == buy.key)
    ok, order_eur, reason = size_order(row, deployable, min_order_eur, max_order_eur)

    lines.append("⭐ Confirmed BUY")
    lines.append(f"ETF: {buy.key}")
    lines.append(f"Confidence: {buy.confidence}%")
    lines.append(f"Reason: {', '.join(buy.reasons)}")
    lines.append("")

    lines.append("💶 Sizing")
    lines.append(f"Status: {reason}")
    if not ok:
        lines.append("No order proposed because sizing failed.")
        return "\n".join(lines)

    lines.append(f"Proposed order: {eur(order_eur)}")
    lines.append("")

    plan = build_trade_plan(instruments[buy.key], snapshots[buy.key], order_eur)

    lines.append("📋 Trade plan")
    lines.append(f"Action: {plan.action} {plan.key}")
    lines.append(f"Entry: {fmt(plan.entry)}")
    lines.append(f"Quantity estimate: {plan.qty_est:.5f}")
    lines.append(f"Stop Loss: {fmt(plan.stop_loss) if plan.stop_loss else 'none'}")
    if plan.tp1:
        lines.append(f"TP1: {fmt(plan.tp1)} — sell {plan.tp1_sell_pct:.0f}%")
    else:
        lines.append("TP1: none")
    if plan.tp2:
        lines.append(f"TP2: {fmt(plan.tp2)} — sell {plan.tp2_sell_pct:.0f}%")
    else:
        lines.append("TP2: none")
    lines.append("")

    lines.append("🔁 Management")
    lines.append(f"Trailing: {plan.trailing_rule}")
    lines.append(f"Reward/risk to TP1: {fmt(plan.reward_risk) if plan.reward_risk else 'n/a'}")
    lines.append("")

    lines.append("📌 Allocation gaps")
    for r in rows:
        lines.append(f"{r.key:<8} target {r.target_weight:>5.1%} | actual {r.actual_weight:>5.1%} | gap {r.gap_eur:+.2f} EUR")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/portfolio.json")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--telegram", action="store_true", help="Send report to Telegram if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are set")
    parser.add_argument("--sleep", type=int, default=900, help="Seconds between scans in loop mode")
    args = parser.parse_args()

    while True:
        report = build_report(args.config)
        print(report)
        if args.telegram:
            sent = send_telegram(report)
            print(f"Telegram sent: {sent}")
        if args.once:
            break
        time.sleep(args.sleep)


if __name__ == "__main__":
    main()
