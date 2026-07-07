from __future__ import annotations

import argparse
from pathlib import Path

from core.allocation import build_allocation_table, size_order
from core.config import BotConfig
from market.data import fetch_market
from strategy.scoring import best_buy_candidate, rank_candidates


def classify_simple_regime(market) -> tuple[str, int, str]:
    """Module 3 placeholder regime engine.

    Full macro regime will arrive in Module 4. For now, use SXR8 and SXRV snapshots
    as a transparent proxy so scoring is not hard-coded.
    """
    score = 50
    notes: list[str] = []
    sxr8 = market.snapshots.get("SXR8")
    sxrv = market.snapshots.get("SXRV")
    if sxr8:
        if sxr8.strong_short_trend and sxr8.above_ema150:
            score += 25
            notes.append("SXR8 strong")
        elif sxr8.above_ema50:
            score += 12
            notes.append("SXR8 positive")
        else:
            score -= 15
            notes.append("SXR8 weak")
    if sxrv:
        if sxrv.strong_short_trend and sxrv.above_ema150:
            score += 15
            notes.append("SXRV strong")
        elif sxrv.above_ema50:
            score += 5
            notes.append("SXRV positive")
        else:
            score -= 5
            notes.append("SXRV weak short-term")
    score = max(0, min(100, score))
    regime = "RISK ON" if score >= 70 else "RISK OFF" if score < 40 else "NEUTRAL"
    return regime, score, "; ".join(notes) if notes else "no regime data"


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
    regime, regime_score, regime_notes = classify_simple_regime(market)
    ranked = rank_candidates(
        rows=rows,
        instruments=cfg.instruments,
        snapshots=market.snapshots,
        regime=regime,
        regime_score=regime_score,
    )

    print("ETF Bot V4 — Module 3 scoring + allocation engine")
    print(f"Equity: {cfg.account.equity_eur:.2f} EUR")
    print(f"Free cash: {cfg.account.free_cash_eur:.2f} EUR")
    print(f"Reserve: {cfg.account.reserve_eur:.2f} EUR")
    print(f"Deployable cash: {cfg.account.deployable_cash_eur:.2f} EUR")
    print(f"Regime: {regime} score={regime_score} | {regime_notes}")
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
    row_by_key = {r.key: r for r in rows}
    for r in sorted(rows, key=lambda x: x.gap_eur, reverse=True):
        print(f"{r.key:8s} target={r.target_weight:6.1%} actual={r.actual_weight:6.1%} gap={r.gap_eur:+8.2f} EUR")

    print()
    print("ETF rankings:")
    for idx, c in enumerate(ranked, start=1):
        r = row_by_key[c.key]
        reason_text = "; ".join(c.reasons)
        print(
            f"{idx:>2}. {c.key:8s} decision={c.decision.value:5s} "
            f"score={c.score:3d}/{c.threshold:<2d} confidence={c.confidence_pct:3d}% "
            f"gap={r.gap_eur:+8.2f} EUR — {reason_text}"
        )

    best = best_buy_candidate(ranked)
    print()
    if not best:
        print("No buy candidate passed scoring threshold.")
        return

    sizing = size_order(cfg.account, best.key, best.allocation_row.gap_eur)
    print(f"Best candidate: {best.key}")
    print(f"Decision: {best.decision.value} | score={best.score}/{best.threshold} | confidence={best.confidence_pct}%")
    print(f"Sizing: {sizing.reason}")
    if sizing.accepted:
        print(f"Proposed order: {sizing.final_order_eur:.2f} EUR")


if __name__ == "__main__":
    main()
