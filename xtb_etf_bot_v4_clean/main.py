from __future__ import annotations
import argparse
from pathlib import Path
from core.config import BotConfig
from core.allocation import allocation_rows, deployable_cash_eur, cash_reserve_eur, propose_order_eur
from market.yahoo import fetch_snapshot
from core.models import MarketSnapshot
from strategy.regime import simple_regime
from strategy.scoring import rank_candidates
from strategy.sltp import build_trade_plan

FALLBACK_PRICES = {
    "SXR8": 708.38, "SXRV": 1475.40, "QUALITY": 76.90,
    "AIINFRA": 9.637, "GINFRA": 6.204, "XMME": 80.346, "H411": 79.52
}

def fallback_snapshot(key: str, price: float) -> MarketSnapshot:
    return MarketSnapshot(key, price, price*0.998, price*0.996, price*0.990, price*0.01, 55.0, price*1.02, price*0.98, "fallback")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/portfolio.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig.from_file(Path(args.config))
    settings = cfg.settings
    equity = float(settings["equity_eur"])
    free_cash = float(settings["free_cash_eur"])
    reserve_pct = float(settings["cash_reserve_pct"])
    reserve = cash_reserve_eur(equity, reserve_pct)
    deployable = deployable_cash_eur(free_cash, equity, reserve_pct)

    print("ETF Bot V4 Clean — Module 4 SL/TP engine")
    print(f"Equity: {equity:.2f} EUR")
    print(f"Free cash: {free_cash:.2f} EUR")
    print(f"Reserve: {reserve:.2f} EUR")
    print(f"Deployable cash: {deployable:.2f} EUR\n")

    snapshots = {}
    print("Market snapshots:")
    for key, inst in cfg.instruments.items():
        snap = fetch_snapshot(inst.yf_symbol) or fallback_snapshot(key, FALLBACK_PRICES.get(key, inst.avg_price or 1.0))
        snapshots[key] = snap
        print(f"{key:8s} close={snap.close:9.3f} EMA50={snap.ema50:9.3f} EMA150={snap.ema150:9.3f} RSI14={snap.rsi14:5.1f} source={snap.source}")

    rows = allocation_rows(cfg.instruments, snapshots, equity)
    print("\nAllocation gaps:")
    for r in rows:
        print(f"{r.key:8s} target={r.target_weight:6.1%} actual={r.actual_weight:6.1%} gap={r.gap_eur:+8.2f} EUR gap_pct={r.gap_pct:+6.1%}")

    regime, regime_score, detail = simple_regime()
    ranked = rank_candidates(rows, cfg.instruments, snapshots, regime, regime_score)
    print(f"\nRegime: {regime} score={regime_score} | {detail}")
    print("Candidate rankings:")
    for c in ranked:
        print(f"{c.key:8s} {c.decision:5s} score={c.score:3d} threshold={c.threshold:2d} confidence={c.confidence:3d}% — {', '.join(c.reasons)}")

    buy = next((c for c in ranked if c.decision == "BUY"), None)
    if not buy:
        print("\nNo BUY candidate.")
        return
    ok, amount, reason = propose_order_eur(buy.row, deployable, float(settings["min_order_eur"]), float(settings["max_order_eur"]))
    print(f"\nBest candidate: {buy.key}")
    print(f"Sizing: {reason}")
    if ok:
        print(f"Proposed order: {amount:.2f} EUR")
        inst = cfg.instruments[buy.key]
        plan = build_trade_plan(inst, snapshots[buy.key])
        print("\nSL/TP discipline:")
        print(f"Order type: {plan.order_type}")
        print(f"Entry: {plan.entry:.4f}")
        if plan.stop_loss is not None:
            print(f"Stop Loss: {plan.stop_loss:.4f}")
        if plan.tp1 is not None:
            print(f"TP1: {plan.tp1:.4f} — sell {plan.tp1_sell_pct:.0f}%")
        else:
            print("TP1: none")
        if plan.tp2 is not None:
            print(f"TP2: {plan.tp2:.4f} — sell {plan.tp2_sell_pct:.0f}%")
        else:
            print("TP2: none")
        if plan.reward_risk is not None:
            print(f"Reward/risk to TP1: {plan.reward_risk:.2f}")
        print(f"Trailing: {plan.trailing_rule}")
        print("Notes: " + "; ".join(plan.notes))
    else:
        print("No order proposed.")

if __name__ == "__main__":
    main()
