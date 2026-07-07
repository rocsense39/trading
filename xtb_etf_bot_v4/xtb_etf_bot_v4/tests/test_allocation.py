from core.allocation import size_order
from core.models import Account


def test_deployable_cash_uses_equity_reserve_not_free_cash_percentage_bug():
    account = Account(
        base_currency="EUR",
        equity_eur=939.06,
        free_cash_eur=75.08,
        cash_reserve_pct_of_equity=0.05,
        min_order_eur=10.0,
        max_order_eur=50.0,
    )
    sizing = size_order(account, "SXR8", allocation_gap_eur=115.35)
    assert round(account.reserve_eur, 2) == 46.95
    assert round(account.deployable_cash_eur, 2) == 28.13
    assert sizing.accepted
    assert round(sizing.final_order_eur, 2) == 28.13
