from core.allocation import deployable_cash, build_allocation_rows
from core.models import Instrument, MarketSnapshot

def snap(key, price=100):
    return MarketSnapshot(key, price, 99, 98, 97, 2, 55, 102, 95, "test")

def test_deployable_cash_uses_equity_reserve():
    dep, reserve = deployable_cash(939.06, 75.08, 0.05)
    assert round(reserve, 2) == 46.95
    assert round(dep, 2) == 28.13

def test_allocation_row_has_gap_pct():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", 0.45, 2)
    rows = build_allocation_rows(1000, [inst], {"SXR8": snap("SXR8", 100)})
    assert rows[0].gap_pct == 0.25
