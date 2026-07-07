from __future__ import annotations

from core.models import AllocationRow, GateResult, Instrument, MarketSnapshot


def _portfolio_gate(row: AllocationRow) -> tuple[bool, str, list[str]]:
    if row.gap_eur <= 0 or row.gap_pct <= 0:
        return False, "❌ FAIL", ["not underweight"]
    if row.gap_pct >= 0.10:
        return True, "✅ PASS", ["large allocation gap"]
    if row.gap_pct >= 0.04:
        return True, "✅ PASS", ["medium allocation gap"]
    return True, "✅ PASS", ["small allocation gap"]


def _trend_gate(inst: Instrument, snap: MarketSnapshot) -> tuple[bool, str, list[str]]:
    reasons: list[str] = []
    source_bad = snap.source.startswith("fallback") or snap.source.startswith("static_fallback")
    if source_bad:
        return False, "❌ FAIL", ["fallback data: signal not trusted"]

    # User-requested core criterion: price > EMA20 > EMA50.
    short_trend = snap.close > snap.ema20 > snap.ema50
    long_ok = snap.close > snap.ema150
    ema150_ok = snap.ema50 > snap.ema150

    if short_trend:
        reasons.append("price > EMA20 > EMA50")
    else:
        reasons.append("trend not aligned: need price > EMA20 > EMA50")

    if long_ok:
        reasons.append("price above EMA150")
    else:
        reasons.append("price below EMA150")

    if inst.sleeve == "satellite":
        if short_trend and long_ok and ema150_ok:
            reasons.append("satellite long trend confirmed")
            return True, "✅ PASS", reasons
        return False, "❌ FAIL", reasons

    # Core and quality: strict short trend + price above EMA150. EMA50 > EMA150 is a bonus, not hard.
    if short_trend and long_ok:
        if ema150_ok:
            reasons.append("EMA50 above EMA150")
        else:
            reasons.append("EMA50 not yet above EMA150")
        return True, "✅ PASS", reasons

    return False, "❌ FAIL", reasons


def _confirmation_gate(snap: MarketSnapshot) -> tuple[bool, str, list[str]]:
    if snap.confirmations:
        return True, "✅ PASS", ["confirmation: " + ", ".join(snap.confirmations)]
    return False, "⏳ WAIT", ["waiting for bullish candle confirmation"]


def _rsi_note(snap: MarketSnapshot) -> str:
    if snap.rsi14 >= 55:
        return f"RSI supportive ({snap.rsi14:.1f})"
    if snap.rsi14 >= 35:
        return f"RSI neutral/weak ({snap.rsi14:.1f})"
    return f"RSI weak/oversold ({snap.rsi14:.1f})"


def evaluate_candidate(
    row: AllocationRow,
    instrument: Instrument,
    snapshot: MarketSnapshot,
    regime: str = "RISK ON",
    regime_score: int = 90,
) -> GateResult:
    reasons: list[str] = []

    portfolio_ok, portfolio_gate, portfolio_reasons = _portfolio_gate(row)
    reasons.extend(portfolio_reasons)

    trend_ok, trend_gate, trend_reasons = _trend_gate(instrument, snapshot)
    reasons.extend(trend_reasons)

    confirmation_ok, confirmation_gate, confirmation_reasons = _confirmation_gate(snapshot)
    reasons.extend(confirmation_reasons)

    if regime == "RISK OFF" and instrument.sleeve == "satellite":
        trend_ok = False
        trend_gate = "❌ FAIL"
        reasons.append("satellite blocked in risk-off")
    elif regime == "RISK ON":
        reasons.append("risk-on regime")
    elif regime == "NEUTRAL":
        reasons.append("neutral regime")
    else:
        reasons.append("risk-off regime")

    reasons.append(_rsi_note(snapshot))

    if portfolio_ok and trend_ok and confirmation_ok:
        decision = "BUY"
        confidence = 95
    elif portfolio_ok and trend_ok:
        decision = "WATCH"
        confidence = 70
    elif portfolio_ok:
        decision = "HOLD"
        confidence = 40
    else:
        decision = "HOLD"
        confidence = 20

    # Gentle adjustments for regime and RSI, without overriding gates.
    if regime == "RISK ON":
        confidence += 3
    elif regime == "RISK OFF":
        confidence -= 15
    if snapshot.rsi14 >= 55:
        confidence += 2
    elif snapshot.rsi14 < 30:
        confidence -= 5
    if snapshot.source.startswith("fallback") or snapshot.source.startswith("static_fallback"):
        confidence = min(confidence, 20)

    confidence = max(0, min(100, confidence))

    return GateResult(
        key=row.key,
        decision=decision,
        confidence=confidence,
        portfolio_gate=portfolio_gate,
        trend_gate=trend_gate,
        confirmation_gate=confirmation_gate,
        reasons=reasons,
        confirmations=snapshot.confirmations,
    )


# Backward-compatible function name.
def score_candidate(row: AllocationRow, instrument: Instrument, snapshot: MarketSnapshot, regime="RISK ON", regime_score=90) -> GateResult:
    return evaluate_candidate(row, instrument, snapshot, regime, regime_score)


def rank_candidates(rows, instruments: dict[str, Instrument], snapshots: dict[str, MarketSnapshot], regime="RISK ON", regime_score=90):
    results = [evaluate_candidate(row, instruments[row.key], snapshots[row.key], regime, regime_score) for row in rows]
    decision_rank = {"BUY": 3, "WATCH": 2, "HOLD": 1}

    def sort_key(result: GateResult):
        row = next(r for r in rows if r.key == result.key)
        inst = instruments[result.key]
        sleeve_priority = {"core": 3, "quality": 2, "core_growth": 2, "satellite": 1}.get(inst.sleeve, 1)
        return (decision_rank.get(result.decision, 0), sleeve_priority, row.gap_eur, result.confidence)

    return sorted(results, key=sort_key, reverse=True)
