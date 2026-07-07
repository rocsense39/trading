from __future__ import annotations

import argparse
from pathlib import Path

from core.allocation import build_allocation_table, size_order
from core.config import BotConfig
from market.data import fetch_market


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/portfolio.json")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-static-fallback", action="store_true", help="Fail missing market data instead of using static fallback prices.")
    args = parser.parse_args()

    cfg = BotConfig.from_file(Path(args.config))
    market = fetch_market(cfg, allow_static_fallback=not args.no_static_fallback)

    rows = build_allocation_table(
        equity_eur=cfg.account.equity_eur,
        free_cash_eur=cfg.account.free_cash_eur,
        targets=cfg.targets,
        positions=cfg.positions,
        prices=market.prices,
    )

    print("ETF Bot V4 — Module 2 market data + allocation engine")
    print(f"Equity: {cfg.account.equity_eur:.2f} EUR")
    print(f"Free cash: {cfg.account.free_cash_eur:.2f} EUR")
    print(f"Reserve: {cfg.account.reserve_eur:.2f} EUR")
    print(f"Deployable cash: {cfg.account.deployable_cash_eur:.2f} EUR")
    print()

    print("Market snapshots:")
    for key in cfg.targets:
        snap = market.snapshots.get(key)
        if snap is None:
            print(f"{key:8s} missing — {market.missing.get(key, 'unknown reason')}")
            continue
        warning = " ⚠ fallback" if snap.source != "yahoo" else ""
        print(
            f"{key:8s} close={snap.close:9.3f} EMA50={snap.ema50:9.3f} "
            f"EMA150={snap.ema150:9.3f} RSI14={snap.rsi14:5.1f} source={snap.source}{warning}"
        )

    print()
    print("Allocation gaps:")
    for r in sorted(rows, key=lambda x: x.gap_eur, reverse=True):
        print(f"{r.key:8s} target={r.target_weight:6.1%} actual={r.actual_weight:6.1%} gap={r.gap_eur:+8.2f} EUR")

    best = max((r for r in rows if r.underweight), key=lambda r: r.gap_eur, default=None)
    print()
    if not best:
        print("No underweight ETF.")
        return
    sizing = size_order(cfg.account, best.key, best.gap_eur)
    print(f"Best candidate: {best.key}")
    print(f"Sizing: {sizing.reason}")
    if sizing.accepted:
        print(f"Proposed order: {sizing.final_order_eur:.2f} EUR")


if __name__ == "__main__":
    main()
