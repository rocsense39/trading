from core.models import AllocationRow, Instrument, MarketSnapshot, ScoreResult

THRESHOLDS = {"core": 60, "core_growth": 60, "quality": 50, "satellite": 70}


def score_candidate(row: AllocationRow, instrument: Instrument, snapshot: MarketSnapshot, regime="RISK ON", regime_score=90) -> ScoreResult:
    score = 0
    reasons: list[str] = []
    fallback_penalty = snapshot.source.startswith("fallback") or snapshot.source.startswith("static_fallback")
    if row.gap_eur <= 0:
        reasons.append("not underweight")
    elif row.gap_pct >= 0.10:
        score += 35; reasons.append("large allocation gap")
    elif row.gap_pct >= 0.04:
        score += 25; reasons.append("medium allocation gap")
    else:
        score += 12; reasons.append("small allocation gap")

    if regime == "RISK ON":
        score += 20; reasons.append("risk-on regime")
    elif regime == "NEUTRAL":
        score += 10; reasons.append("neutral regime")
    else:
        reasons.append("risk-off regime")

    sleeve = instrument.sleeve
    if sleeve in {"core", "core_growth"}:
        if snapshot.close > snapshot.ema50 > snapshot.ema150:
            score += 20; reasons.append("strong trend")
        elif snapshot.close > snapshot.ema50:
            score += 12; reasons.append("positive short-term trend")
        else:
            reasons.append("weak trend")
    elif sleeve == "quality":
        if snapshot.close > snapshot.ema150:
            score += 15; reasons.append("quality above EMA150")
        else:
            score += 5; reasons.append("quality defensive but technically weak")
    else:
        if snapshot.close > snapshot.ema20 > snapshot.ema50 > snapshot.ema150:
            score += 20; reasons.append("strong tactical trend")
        elif snapshot.close > snapshot.ema50:
            score += 10; reasons.append("positive trend")
        else:
            reasons.append("weak trend")

    if snapshot.rsi14 >= 50:
        score += 10; reasons.append("RSI supportive")
    elif snapshot.rsi14 >= 35:
        score += 4; reasons.append("RSI neutral/weak")
    else:
        reasons.append("RSI weak")

    if sleeve in {"core", "quality"}:
        score += 5; reasons.append("strategic sleeve")
    else:
        reasons.append("tactical sleeve")

    if fallback_penalty:
        score -= 25
        reasons.append("fallback data: signal not trusted")

    score = max(0, min(100, score))
    threshold = THRESHOLDS.get(sleeve, 70)
    decision = "BUY" if score >= threshold and row.gap_eur > 0 else "SKIP"
    return ScoreResult(row.key, decision, score, threshold, score, reasons)


def rank_candidates(rows, instruments: dict[str, Instrument], snapshots: dict[str, MarketSnapshot], regime="RISK ON", regime_score=90):
    scored = [score_candidate(row, instruments[row.key], snapshots[row.key], regime, regime_score) for row in rows]
    return sorted(scored, key=lambda x: (x.decision == "BUY", x.score), reverse=True)
