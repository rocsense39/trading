from core.models import AllocationRow, Instrument, MarketSnapshot
from strategy.scoring import score_candidate


def test_fallback_data_does_not_create_false_satellite_buy():
    row = AllocationRow("AIINFRA", 0.05, 0.0, 0.0, 50.0, 50.0, 0.05)
    inst = Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", "satellite", 0.05)
    snap = MarketSnapshot("AIINFRA", 100, 99, 98, 97, 1.5, 55, 102, 96, "fallback_no_data")
    result = score_candidate(row, inst, snap, regime="RISK ON", regime_score=90)
    assert result.decision == "SKIP"
    assert "fallback data: signal not trusted" in result.reasons
