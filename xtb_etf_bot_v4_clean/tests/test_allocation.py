from core.allocation import cash_reserve_eur, deployable_cash_eur, allocation_rows, propose_order_eur
from core.models import Instrument, Sleeve, MarketSnapshot

def test_deployable_cash_uses_equity_reserve():
    assert round(cash_reserve_eur(939.06, 0.05), 2) == 46.95
    assert round(deployable_cash_eur(75.08, 939.06, 0.05), 2) == 28.13

def test_allocation_row_has_gap_pct():
    inst = {"SXR8": Instrument("SXR8", "SXR8.DE", "SXR8.DE", Sleeve.CORE, 0.45, qty=0.3, avg_price=700)}
    snap = {"SXR8": MarketSnapshot("SXR8", 700, 690, 680, 650, 5, 60, 710, 680)}
    row = allocation_rows(inst, snap, 1000)[0]
    assert hasattr(row, "gap_pct")
    assert round(row.gap_pct, 2) == 0.24

def test_sizing_accepts_small_account():
    inst = {"SXR8": Instrument("SXR8", "SXR8.DE", "SXR8.DE", Sleeve.CORE, 0.45, qty=0.3, avg_price=700)}
    snap = {"SXR8": MarketSnapshot("SXR8", 700, 690, 680, 650, 5, 60, 710, 680)}
    row = allocation_rows(inst, snap, 939.06)[0]
    ok, amount, _ = propose_order_eur(row, 28.13, 10, 50)
    assert ok
    assert round(amount, 2) == 28.13
