from core.models import AllocationRow, Instrument, Sleeve
from market.indicators import Snapshot
from strategy.scoring import Decision, rank_candidates, score_candidate, threshold_for_sleeve


def snap(close=100, ema20=98, ema50=95, ema150=90, rsi=60):
    return Snapshot(
        symbol="T",
        close=close,
        high=close + 1,
        low=close - 1,
        ema20=ema20,
        ema50=ema50,
        ema150=ema150,
        atr20=2,
        hh20=101,
        ll20=90,
        rsi14=rsi,
        volume=1000,
        vol_ma20=900,
        rows=200,
        source="test",
    )


def row(key="SXR8", gap=200, gap_pct=0.20, target=0.45, actual=0.25):
    return AllocationRow(
        key=key,
        target_weight=target,
        current_value_eur=actual * 1000,
        actual_weight=actual,
        target_value_eur=target * 1000,
        gap_eur=gap,
        underweight=gap > 0,
    )


def test_thresholds_by_sleeve():
    assert threshold_for_sleeve(Sleeve.CORE) == 60
    assert threshold_for_sleeve(Sleeve.CORE_GROWTH) == 60
    assert threshold_for_sleeve(Sleeve.QUALITY) == 50
    assert threshold_for_sleeve(Sleeve.SATELLITE) == 70


def test_core_with_large_gap_and_good_trend_is_buy():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", Sleeve.CORE)
    c = score_candidate(row=row(), instrument=inst, snapshot=snap(), benchmark_snapshot=snap(), regime="RISK ON", regime_score=80)
    assert c.decision == Decision.BUY
    assert c.score >= c.threshold


def test_overweight_candidate_is_skipped_even_if_trend_good():
    inst = Instrument("SXRV", "SXRV.DE", "SXRV.DE", Sleeve.CORE_GROWTH)
    c = score_candidate(row=row("SXRV", gap=-50, gap_pct=-0.05), instrument=inst, snapshot=snap(), benchmark_snapshot=snap(), regime="RISK ON", regime_score=80)
    assert c.decision == Decision.SKIP
    assert not c.accepted


def test_satellite_needs_stronger_evidence():
    inst = Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", Sleeve.SATELLITE)
    weak = snap(close=95, ema20=98, ema50=100, ema150=101, rsi=35)
    c = score_candidate(row=row("AIINFRA", gap=47, gap_pct=0.05, target=0.05, actual=0), instrument=inst, snapshot=weak, benchmark_snapshot=snap(), regime="RISK ON", regime_score=80)
    assert c.decision != Decision.BUY
    assert c.score < c.threshold


def test_rank_candidates_puts_buy_candidates_first():
    rows = [row("SXR8", gap=200, gap_pct=0.20), row("AIINFRA", gap=47, gap_pct=0.05)]
    instruments = {
        "SXR8": Instrument("SXR8", "SXR8.DE", "SXR8.DE", Sleeve.CORE),
        "AIINFRA": Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", Sleeve.SATELLITE),
    }
    snapshots = {"SXR8": snap(), "AIINFRA": snap(close=95, ema20=98, ema50=100, ema150=101, rsi=35)}
    ranked = rank_candidates(rows=rows, instruments=instruments, snapshots=snapshots, regime="RISK ON", regime_score=80)
    assert ranked[0].key == "SXR8"
    assert ranked[0].decision == Decision.BUY
