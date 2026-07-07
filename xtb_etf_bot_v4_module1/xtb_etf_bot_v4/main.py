from __future__ import annotations

import argparse
from pathlib import Path

from core.allocation import build_allocation_table, size_order
from core.config import BotConfig
from core.models import PriceSnapshot

# Temporary static prices for Module 1. Module 2 will replace this with market data.
STATIC_PRICES = {
    "SXR8": 709.28,
    "SXRV": 1490.80,
    "QUALITY": 76.98,
    "AIINFRA": 9.788,
    "GINFRA": 6.145,
    "XMME": 82.192,
    "H411": 81.63,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/portfolio.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig.from_file(Path(args.config))
    prices = {k: PriceSnapshot(key=k, close=v) for k, v in STATIC_PRICES.items()}

    rows = build_allocation_table(
        equity_eur=cfg.account.equity_eur,
        free_cash_eur=cfg.account.free_cash_eur,
        targets=cfg.targets,
        positions=cfg.positions,
        prices=prices,
    )

    print("ETF Bot V4 — Module 1 allocation engine")
    print(f"Equity: {cfg.account.equity_eur:.2f} EUR")
    print(f"Free cash: {cfg.account.free_cash_eur:.2f} EUR")
    print(f"Reserve: {cfg.account.reserve_eur:.2f} EUR")
    print(f"Deployable cash: {cfg.account.deployable_cash_eur:.2f} EUR")
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
