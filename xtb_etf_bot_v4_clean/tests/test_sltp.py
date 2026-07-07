from core.models import Instrument, MarketSnapshot, Sleeve
from strategy.sltp import build_trade_plan


def snap(close=100, ema20=98, ema50=95, ema150=90, atr=2, rsi=60, hh20=102, ll20=88):
    return MarketSnapshot("T", close, ema20, ema50, ema150, atr, rsi, hh20, ll20, "test")


def inst(key="SXR8", sleeve=Sleeve.CORE):
    return Instrument(key, key + ".DE", key + ".DE", sleeve, 0.45)


def test_core_plan_has_stop_and_partial_tp_only():
    plan = build_trade_plan(inst("SXR8", Sleeve.CORE), snap())
    assert plan.stop_loss is not None
    assert plan.tp1 is not None
    assert plan.tp1_sell_pct == 20.0
    assert plan.tp2 is None
    assert plan.reward_risk is not None and plan.reward_risk > 0


def test_quality_plan_has_no_fixed_tp():
    plan = build_trade_plan(inst("QUALITY", Sleeve.QUALITY), snap(close=77, ema20=77, ema50=76, ema150=75, atr=0.5))
    assert plan.stop_loss is not None
    assert plan.tp1 is None
    assert plan.tp2 is None
    assert plan.reward_risk is None


def test_satellite_plan_has_two_tps():
    plan = build_trade_plan(inst("AIINFRA", Sleeve.SATELLITE), snap(close=10, ema20=9.8, ema50=9.5, ema150=9.0, atr=0.2, hh20=10.4))
    assert plan.stop_loss is not None
    assert plan.tp1 is not None
    assert plan.tp2 is not None
    assert plan.tp1_sell_pct == 30.0
    assert plan.tp2_sell_pct == 30.0
    assert plan.tp2 > plan.tp1 > plan.entry > plan.stop_loss
