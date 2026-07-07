from bot.portfolio import reserve_eur, deployable_cash_eur


def test_reserve_uses_portfolio_value():
    cfg = {"settings": {"free_cash_eur": 75.08, "equity_eur": 939.06, "cash_reserve_pct": 0.05, "reserve_basis": "portfolio_value"}}
    assert round(reserve_eur(cfg, 728.64), 2) == 36.43
    assert round(deployable_cash_eur(cfg, 728.64), 2) == 38.65
