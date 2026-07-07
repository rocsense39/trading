from core.allocation import deployable_cash, size_order
from core.models import AllocationRow


def test_deployable_cash_reserves_from_equity():
    deployable, reserve = deployable_cash(939.06, 75.08, 0.05)
    assert round(reserve, 2) == 46.95
    assert round(deployable, 2) == 28.13


def test_size_order_accepts_valid_small_order():
    row = AllocationRow("SXR8", .45, .25, 250, 450, 200, .20)
    ok, amount, reason = size_order(row, 28.13, 10, 50)
    assert ok is True
    assert round(amount, 2) == 28.13
    assert reason == "accepted"
