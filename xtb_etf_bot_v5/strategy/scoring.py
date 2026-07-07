from __future__ import annotations
from dataclasses import dataclass
from core.models import AllocationRow, Instrument, MarketSnapshot, Sleeve

@dataclass(frozen=True)
class CandidateScore:
    key: str
    score: int
    threshold: int
    decision: str
    confidence: int
    reasons: list[str]
    row: AllocationRow

def threshold_for(inst: Instrument) -> int:
    if inst.sleeve in {Sleeve.CORE, Sleeve.CORE_GROWTH}:
        return 60
    if inst.sleeve == Sleeve.QUALITY:
        return 50
    return 70

def _allocation_score(row: AllocationRow) -> tuple[int, str]:
    if row.gap_eur <= 0:
        return 0, "not underweight"
    if row.gap_pct >= 0.10:
        return 35, "large allocation gap"
    if row.gap_pct >= 0.04:
        return 25, "medium allocation gap"
    if row.gap_pct > 0:
        return 12, "small allocation gap"
    return 0, "not underweight"

def _regime_score(regime: str, regime_score: int) -> tuple[int, str]:
    if regime == "RISK ON" or regime_score >= 70:
        return 20, "risk-on regime"
    if regime == "NEUTRAL" or regime_score >= 40:
        return 10, "neutral regime"
    return 0, "risk-off regime"

def _trend_score(inst: Instrument, s: MarketSnapshot) -> tuple[int, str]:
    if s.close > s.ema20 > s.ema50 > s.ema150:
        return 20, "strong trend"
    if s.close > s.ema50 > s.ema150:
        return 16, "positive trend"
    if inst.sleeve == Sleeve.QUALITY and s.close > s.ema150:
        return 10, "quality above EMA150"
    if s.close > s.ema50:
        return 8, "above EMA50"
    return 0, "weak trend"

def _rsi_score(s: MarketSnapshot) -> tuple[int, str]:
    if 50 <= s.rsi14 <= 72:
        return 10, "RSI supportive"
    if 40 <= s.rsi14 < 50:
        return 5, "RSI neutral"
    if s.rsi14 > 72:
        return 3, "RSI extended"
    return 0, "RSI weak"

def _sleeve_score(inst: Instrument) -> tuple[int, str]:
    if inst.sleeve in {Sleeve.CORE, Sleeve.QUALITY}:
        return 5, "strategic sleeve"
    return 2, "tactical sleeve"

def score_candidate(row: AllocationRow, instrument: Instrument, snapshot: MarketSnapshot, benchmark_snapshot: MarketSnapshot | None = None, regime: str = "NEUTRAL", regime_score: int = 50) -> CandidateScore:
    reasons = []
    a, ar = _allocation_score(row); reasons.append(ar)
    rg, rr = _regime_score(regime, regime_score); reasons.append(rr)
    t, tr = _trend_score(instrument, snapshot); reasons.append(tr)
    r, rs = _rsi_score(snapshot); reasons.append(rs)
    sl, sr = _sleeve_score(instrument); reasons.append(sr)
    total = min(100, a + rg + t + r + sl)
    threshold = threshold_for(instrument)
    if row.gap_eur <= 0:
        decision = "SKIP"
    elif total >= threshold:
        decision = "BUY"
    elif total >= threshold - 15:
        decision = "WATCH"
    else:
        decision = "SKIP"
    return CandidateScore(key=row.key, score=total, threshold=threshold, decision=decision, confidence=total, reasons=reasons, row=row)

def rank_candidates(rows: list[AllocationRow], instruments: dict[str, Instrument], snapshots: dict[str, MarketSnapshot], regime: str, regime_score: int) -> list[CandidateScore]:
    ranked = []
    bench = snapshots.get("SXR8")
    for row in rows:
        inst = instruments[row.key]
        snap = snapshots.get(row.key)
        if snap is None:
            continue
        ranked.append(score_candidate(row, inst, snap, bench, regime, regime_score))
    return sorted(ranked, key=lambda c: (c.decision == "BUY", c.score, c.row.gap_eur), reverse=True)
