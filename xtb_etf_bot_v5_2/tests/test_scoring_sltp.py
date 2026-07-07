from core.models import AllocationRow, Instrument, MarketSnapshot
from strategy.scoring import score_candidate
from strategy.sltp import build_trade_plan

def snap():
    return MarketSnapshot("SXR8", 100, 99, 98, 97, 2, 60, 102, 95, "test")

def test_core_buy_candidate_scores_buy():
    row = AllocationRow("SXR8", .45, .25, 250, 450, 200, .20)
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", .45, 2.5)
    score = score_candidate(row, inst, snap())
    assert score.decision == "BUY"
    assert score.score >= 60

def test_sltp_core_has_stop_and_tp1():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", .45, 2.5)
    plan = build_trade_plan(inst, snap(), 28.13)
    assert plan.stop_loss is not None
    assert plan.tp1 is not None
    assert plan.tp1_sell_pct == 20
