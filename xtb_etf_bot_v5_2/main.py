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


def fmt(x: float) -> str:
    return f"{x:.2f}"


def build_report(config_path: str | Path = "config/portfolio.json") -> str:
    cfg = BotConfig.from_file(Path(config_path))
    s = cfg.settings
    equity = float(s["equity_eur"])
    free_cash = float(s["free_cash_eur"])
    deployable, reserve = deployable_cash(equity, free_cash, float(s["cash_reserve_pct"]))

    lines: list[str] = []
    lines.append("ETF Bot V5.2 — quiet data + allocation + scoring + SL/TP")
    lines.append(f"Equity: {equity:.2f} EUR")
    lines.append(f"Free cash: {free_cash:.2f} EUR")
    lines.append(f"Reserve: {reserve:.2f} EUR")
    lines.append(f"Deployable cash: {deployable:.2f} EUR\n")

    snapshots = fetch_all(cfg.instruments, s.get("period", "9mo"), s.get("interval", "1h"))
    lines.append("Market snapshots:")
    for inst in cfg.instruments:
        snap = snapshots[inst.key]
        lines.append(f"{inst.key:<8} close={snap.close:9.3f} EMA50={snap.ema50:9.3f} EMA150={snap.ema150:9.3f} RSI14={snap.rsi14:5.1f} source={snap.source}")

    rows = build_allocation_rows(equity, cfg.instruments, snapshots)
    lines.append("Allocation gaps:")
    for r in rows:
        lines.append(f"{r.key:<8} target={r.target_weight:6.1%} actual={r.actual_weight:6.1%} gap={r.gap_eur:+8.2f} EUR gap_pct={r.gap_pct:+6.1%}")

    instruments = {i.key: i for i in cfg.instruments}
    ranked = rank_candidates(rows, instruments, snapshots, regime="RISK ON", regime_score=90)
    lines.append("
Regime: RISK ON score=90 | static module-5.2 regime")
    lines.append("Candidate rankings:")
    for c in ranked:
        lines.append(f"{c.key:<8} {c.decision:<4} score={c.score:3d} threshold={c.threshold:2d} confidence={c.confidence:3d}% — {', '.join(c.reasons)}")

    buy = next((c for c in ranked if c.decision == "BUY"), None)
    if not buy:
        lines.append("
No BUY candidate.")
        return "
".join(lines)

    row = next(r for r in rows if r.key == buy.key)
    ok, order_eur, reason = size_order(row, deployable, float(s["min_order_eur"]), float(s["max_order_eur"]))
    lines.append(f"
Best candidate: {buy.key}")
    lines.append(f"Sizing: {reason}")
    if not ok:
        return "
".join(lines)

    plan = build_trade_plan(instruments[buy.key], snapshots[buy.key], order_eur)
    lines.append(f"Proposed order: {order_eur:.2f} EUR")
    lines.append("
Trade plan:")
    lines.append(f"Action: {plan.action} {plan.key}")
    lines.append(f"Entry: {fmt(plan.entry)}")
    lines.append(f"Quantity estimate: {plan.qty_est:.5f}")
    lines.append(f"Stop Loss: {fmt(plan.stop_loss) if plan.stop_loss else 'none'}")
    lines.append(f"TP1: {fmt(plan.tp1) if plan.tp1 else 'none'}" + (f" — sell {plan.tp1_sell_pct:.0f}%" if plan.tp1 else ""))
    lines.append(f"TP2: {fmt(plan.tp2) if plan.tp2 else 'none'}" + (f" — sell {plan.tp2_sell_pct:.0f}%" if plan.tp2 else ""))
    lines.append(f"Trailing: {plan.trailing_rule}")
    lines.append(f"Reward/risk to TP1: {fmt(plan.reward_risk) if plan.reward_risk else 'n/a'}")
    return "
".join(lines)


def main():
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
