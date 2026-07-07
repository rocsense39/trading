from __future__ import annotations
import argparse
from pathlib import Path
from core.config import BotConfig
from core.allocation import build_allocation_rows, deployable_cash, size_order
from market.data import fetch_all
from strategy.scoring import rank_candidates
from strategy.sltp import build_trade_plan


def fmt(x: float) -> str:
    return f"{x:.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/portfolio.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig.from_file(Path(args.config))
    s = cfg.settings
    equity = float(s["equity_eur"])
    free_cash = float(s["free_cash_eur"])
    deployable, reserve = deployable_cash(equity, free_cash, float(s["cash_reserve_pct"]))

    print("ETF Bot V5.1 — real-data-safe allocation + scoring + SL/TP")
    print(f"Equity: {equity:.2f} EUR")
    print(f"Free cash: {free_cash:.2f} EUR")
    print(f"Reserve: {reserve:.2f} EUR")
    print(f"Deployable cash: {deployable:.2f} EUR\n")

    snapshots = fetch_all(cfg.instruments, s.get("period", "9mo"), s.get("interval", "1h"))
    print("Market snapshots:")
    for inst in cfg.instruments:
        snap = snapshots[inst.key]
        print(f"{inst.key:<8} close={snap.close:9.3f} EMA50={snap.ema50:9.3f} EMA150={snap.ema150:9.3f} RSI14={snap.rsi14:5.1f} source={snap.source}")

    rows = build_allocation_rows(equity, cfg.instruments, snapshots)
    print("\nAllocation gaps:")
    for r in rows:
        print(f"{r.key:<8} target={r.target_weight:6.1%} actual={r.actual_weight:6.1%} gap={r.gap_eur:+8.2f} EUR gap_pct={r.gap_pct:+6.1%}")

    instruments = {i.key: i for i in cfg.instruments}
    ranked = rank_candidates(rows, instruments, snapshots, regime="RISK ON", regime_score=90)
    print("\nRegime: RISK ON score=90 | static module-4 regime")
    print("Candidate rankings:")
    for c in ranked:
        print(f"{c.key:<8} {c.decision:<4} score={c.score:3d} threshold={c.threshold:2d} confidence={c.confidence:3d}% — {', '.join(c.reasons)}")

    buy = next((c for c in ranked if c.decision == "BUY"), None)
    if not buy:
        print("\nNo BUY candidate.")
        return
    row = next(r for r in rows if r.key == buy.key)
    ok, order_eur, reason = size_order(row, deployable, float(s["min_order_eur"]), float(s["max_order_eur"]))
    print(f"\nBest candidate: {buy.key}")
    print(f"Sizing: {reason}")
    if not ok:
        return
    plan = build_trade_plan(instruments[buy.key], snapshots[buy.key], order_eur)
    print(f"Proposed order: {order_eur:.2f} EUR")
    print("\nTrade plan:")
    print(f"Action: {plan.action} {plan.key}")
    print(f"Entry: {fmt(plan.entry)}")
    print(f"Quantity estimate: {plan.qty_est:.5f}")
    print(f"Stop Loss: {fmt(plan.stop_loss) if plan.stop_loss else 'none'}")
    print(f"TP1: {fmt(plan.tp1) if plan.tp1 else 'none'}" + (f" — sell {plan.tp1_sell_pct:.0f}%" if plan.tp1 else ""))
    print(f"TP2: {fmt(plan.tp2) if plan.tp2 else 'none'}" + (f" — sell {plan.tp2_sell_pct:.0f}%" if plan.tp2 else ""))
    print(f"Trailing: {plan.trailing_rule}")
    print(f"Reward/risk to TP1: {fmt(plan.reward_risk) if plan.reward_risk else 'n/a'}")

if __name__ == "__main__":
    main()
