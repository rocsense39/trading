from core.models import AllocationRow, Instrument, MarketSnapshot, Sleeve
from strategy.scoring import score_candidate, rank_candidates

def row(key="SXR8", gap=200, gap_pct=0.20, target=0.45, actual=0.25):
    return AllocationRow(key, target, 250.0, actual, 450.0, gap, gap_pct, gap > 0)

def snap(close=110, ema20=108, ema50=105, ema150=100, rsi=61):
    return MarketSnapshot("S", close, ema20, ema50, ema150, 2, rsi, 112, 100)

def test_core_with_large_gap_and_good_trend_is_buy():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", Sleeve.CORE, 0.45)
    c = score_candidate(row=row(), instrument=inst, snapshot=snap(), regime="RISK ON", regime_score=90)
    assert c.decision == "BUY"
    assert c.score >= 60

def test_satellite_needs_stronger_evidence():
    inst = Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", Sleeve.SATELLITE, 0.05)
    weak = snap(close=95, ema20=98, ema50=100, ema150=101, rsi=35)
    c = score_candidate(row=row("AIINFRA", gap=47, gap_pct=0.05, target=0.05, actual=0), instrument=inst, snapshot=weak, regime="RISK ON", regime_score=80)
    assert c.decision != "BUY"

def test_rank_candidates_puts_buy_candidates_first():
    rows = [row("SXR8", gap=200, gap_pct=0.20), row("AIINFRA", gap=47, gap_pct=0.05, target=0.05, actual=0)]
    instruments = {
        "SXR8": Instrument("SXR8", "SXR8.DE", "SXR8.DE", Sleeve.CORE, 0.45),
        "AIINFRA": Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", Sleeve.SATELLITE, 0.05),
    }
    snapshots = {"SXR8": snap(), "AIINFRA": snap(close=95, ema20=98, ema50=100, ema150=101, rsi=35)}
    ranked = rank_candidates(rows, instruments, snapshots, regime="RISK ON", regime_score=80)
    assert ranked[0].key == "SXR8"
