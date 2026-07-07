from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.models import AllocationRow, Instrument, Sleeve
from market.indicators import Snapshot


class Decision(str, Enum):
    BUY = "BUY"
    WATCH = "WATCH"
    SKIP = "SKIP"


@dataclass(frozen=True)
class ScoreBreakdown:
    allocation: int
    regime: int
    trend: int
    momentum: int
    relative_strength: int
    sleeve: int

    @property
    def total(self) -> int:
        return max(0, min(100, self.allocation + self.regime + self.trend + self.momentum + self.relative_strength + self.sleeve))


@dataclass(frozen=True)
class ScoredCandidate:
    key: str
    instrument: Instrument
    allocation_row: AllocationRow
    snapshot: Snapshot | None
    score: int
    threshold: int
    decision: Decision
    accepted: bool
    reasons: tuple[str, ...]
    breakdown: ScoreBreakdown

    @property
    def confidence_pct(self) -> int:
        if self.threshold <= 0:
            return self.score
        return max(0, min(100, round(100 * self.score / self.threshold)))


def threshold_for_sleeve(sleeve: Sleeve) -> int:
    if sleeve == Sleeve.QUALITY:
        return 50
    if sleeve in {Sleeve.CORE, Sleeve.CORE_GROWTH}:
        return 60
    return 70


def _allocation_score(row: AllocationRow) -> tuple[int, str]:
    if row.gap_eur <= 0:
        return 0, "not underweight"
    if row.gap_pct >= 0.10:
        return 35, "very large allocation gap"
    if row.gap_pct >= 0.06:
        return 30, "large allocation gap"
    if row.gap_pct >= 0.03:
        return 22, "medium allocation gap"
    return 12, "small allocation gap"


def _regime_score(regime: str, regime_score: int) -> tuple[int, str]:
    regime = regime.upper()
    if regime == "RISK ON":
        return 20, "risk-on regime"
    if regime == "NEUTRAL":
        return 10, "neutral regime"
    if regime_score >= 55:
        return 4, "weak but improving regime"
    return -15, "risk-off regime"


def _trend_score(snap: Snapshot | None, sleeve: Sleeve) -> tuple[int, str]:
    if snap is None:
        return -20, "missing market data"
    if snap.strong_long_trend:
        return 20, "strong long trend"
    if snap.strong_short_trend:
        return 18, "strong short-term trend"
    if snap.above_ema50 and snap.above_ema150:
        return 14, "above EMA50 and EMA150"
    if snap.above_ema50:
        return 10, "above EMA50"
    if snap.above_ema150:
        return 6, "above EMA150"
    # Satellites are punished more harshly for weak trend; core can wait but still accumulate later.
    if sleeve == Sleeve.SATELLITE:
        return -15, "weak trend for satellite"
    return -8, "weak trend"


def _momentum_score(snap: Snapshot | None) -> tuple[int, str]:
    if snap is None:
        return 0, "RSI unavailable"
    rsi = snap.rsi14
    if 50 <= rsi <= 70:
        return 10, "RSI supportive"
    if 45 <= rsi < 50:
        return 5, "RSI neutral"
    if 30 <= rsi < 45:
        return 0, "RSI weak"
    if rsi < 30:
        return -5, "RSI oversold/weak"
    return 4, "RSI extended"


def _relative_strength_score(key: str, snap: Snapshot | None, benchmark: Snapshot | None, sleeve: Sleeve) -> tuple[int, str]:
    if snap is None or benchmark is None:
        return 0, "relative strength unavailable"
    if key == "SXR8":
        return 5, "benchmark/core anchor"
    # Simple relative strength proxy: distance above/below EMA50 compared with SXR8.
    own = snap.close / snap.ema50 - 1 if snap.ema50 else 0.0
    base = benchmark.close / benchmark.ema50 - 1 if benchmark.ema50 else 0.0
    diff = own - base
    if diff >= 0.01:
        return 10, "relative strength positive"
    if diff >= -0.01:
        return 4, "relative strength neutral"
    if sleeve == Sleeve.SATELLITE:
        return -8, "relative strength weak"
    return -3, "relative strength weak"


def _sleeve_score(sleeve: Sleeve) -> tuple[int, str]:
    if sleeve == Sleeve.QUALITY:
        return 8, "quality stabilizer sleeve"
    if sleeve == Sleeve.CORE:
        return 5, "core accumulation sleeve"
    if sleeve == Sleeve.CORE_GROWTH:
        return 3, "core growth sleeve"
    return 0, "satellite sleeve requires stronger evidence"


def score_candidate(
    *,
    row: AllocationRow,
    instrument: Instrument,
    snapshot: Snapshot | None,
    benchmark_snapshot: Snapshot | None,
    regime: str,
    regime_score: int,
) -> ScoredCandidate:
    sleeve = instrument.sleeve
    threshold = threshold_for_sleeve(sleeve)

    reasons: list[str] = []
    alloc_score, alloc_reason = _allocation_score(row)
    reasons.append(alloc_reason)

    regime_points, regime_reason = _regime_score(regime, regime_score)
    reasons.append(regime_reason)

    trend_points, trend_reason = _trend_score(snapshot, sleeve)
    reasons.append(trend_reason)

    momentum_points, momentum_reason = _momentum_score(snapshot)
    reasons.append(momentum_reason)

    rs_points, rs_reason = _relative_strength_score(row.key, snapshot, benchmark_snapshot, sleeve)
    reasons.append(rs_reason)

    sleeve_points, sleeve_reason = _sleeve_score(sleeve)
    reasons.append(sleeve_reason)

    breakdown = ScoreBreakdown(
        allocation=alloc_score,
        regime=regime_points,
        trend=trend_points,
        momentum=momentum_points,
        relative_strength=rs_points,
        sleeve=sleeve_points,
    )
    score = breakdown.total

    if row.gap_eur <= 0:
        decision = Decision.SKIP
        accepted = False
    elif snapshot is None:
        decision = Decision.SKIP
        accepted = False
    elif score >= threshold:
        decision = Decision.BUY
        accepted = True
    elif score >= max(35, threshold - 15):
        decision = Decision.WATCH
        accepted = False
    else:
        decision = Decision.SKIP
        accepted = False

    reasons.append(f"score {score}/threshold {threshold}")
    return ScoredCandidate(
        key=row.key,
        instrument=instrument,
        allocation_row=row,
        snapshot=snapshot,
        score=score,
        threshold=threshold,
        decision=decision,
        accepted=accepted,
        reasons=tuple(reasons),
        breakdown=breakdown,
    )


def rank_candidates(
    *,
    rows: list[AllocationRow],
    instruments: dict[str, Instrument],
    snapshots: dict[str, Snapshot],
    regime: str,
    regime_score: int,
    benchmark_key: str = "SXR8",
) -> list[ScoredCandidate]:
    benchmark = snapshots.get(benchmark_key)
    scored = [
        score_candidate(
            row=row,
            instrument=instruments[row.key],
            snapshot=snapshots.get(row.key),
            benchmark_snapshot=benchmark,
            regime=regime,
            regime_score=regime_score,
        )
        for row in rows
        if row.key in instruments
    ]
    return sorted(scored, key=lambda c: (c.accepted, c.score, c.allocation_row.gap_eur), reverse=True)


def best_buy_candidate(candidates: list[ScoredCandidate]) -> ScoredCandidate | None:
    return next((c for c in candidates if c.accepted), None)
