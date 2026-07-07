from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .portfolio import HoldingView

@dataclass
class Candidate:
    name: str
    view: HoldingView
    score: int
    threshold: int
    reason: str


def score_candidate(cfg: dict[str, Any], view: HoldingView, regime: str, regime_score: int) -> Candidate | None:
    sleeve = view.meta.get("sleeve", "satellite")
    rules = cfg.get("sizing_rules", {}).get(sleeve, {"threshold": 70, "min_gap_eur": 5.0})
    threshold = int(rules.get("threshold", 70))
    min_gap = float(rules.get("min_gap_eur", 5.0))

    if view.gap_eur <= min_gap:
        print(f"{view.name}: no buy — not underweight")
        return None

    s = view.snap
    score = 0
    reasons: list[str] = []

    if view.gap_pct >= 0.10 or view.gap_eur >= 75:
        score += 30; reasons.append("large allocation gap")
    elif view.gap_eur >= 25:
        score += 20; reasons.append("medium allocation gap")
    else:
        score += 10; reasons.append("small allocation gap")

    if regime == "RISK ON":
        score += 25; reasons.append("risk-on regime")
    elif regime == "NEUTRAL":
        score += 10; reasons.append("neutral regime")
    else:
        if sleeve == "quality":
            score += 5; reasons.append("quality allowed in risk-off")
        else:
            score -= 25; reasons.append("risk-off penalty")

    if sleeve in {"core", "core_growth"}:
        if s.close > s.ema20 > s.ema50:
            score += 25; reasons.append("strong short-term trend")
        elif s.close > s.ema50:
            score += 15; reasons.append("above EMA50")
        elif s.close > s.ema150:
            score += 8; reasons.append("above EMA150")
        else:
            score -= 15; reasons.append("below EMA150")
    elif sleeve == "quality":
        if s.close > s.ema50:
            score += 15; reasons.append("above EMA50")
        elif s.close > s.ema150:
            score += 8; reasons.append("above EMA150")
        else:
            score -= 5; reasons.append("quality weak trend")
    else:
        if s.close > s.ema20 > s.ema50 > s.ema150:
            score += 25; reasons.append("satellite trend confirmed")
        elif s.close > s.ema50:
            score += 10; reasons.append("above EMA50")
        else:
            score -= 15; reasons.append("weak trend")

    if s.rsi14 >= 50:
        score += 10; reasons.append("RSI supportive")
    else:
        reasons.append("RSI weak")

    return Candidate(view.name, view, score, threshold, "; ".join(reasons) + f"; score {score}/threshold {threshold}")


def choose_candidate(cfg: dict[str, Any], views: dict[str, HoldingView], regime: str, regime_score: int) -> Candidate | None:
    print("Candidate scores:")
    candidates: list[Candidate] = []
    for view in views.values():
        c = score_candidate(cfg, view, regime, regime_score)
        if c is None:
            continue
        print(f"{c.name}: score={c.score} threshold={c.threshold} — {c.reason}")
        if c.score >= c.threshold:
            candidates.append(c)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c.score, c.view.gap_eur), reverse=True)
    return candidates[0]
