from core.config import BotConfig
from market import data as market_data
from market.data import fetch_market


def test_fetch_market_static_fallback_has_prices(monkeypatch):
    # Keep this unit test offline and deterministic.
    monkeypatch.setattr(market_data, "get_yahoo_snapshot", lambda symbol: None)
    cfg = BotConfig.from_file("config/portfolio.json")
    result = fetch_market(cfg, allow_static_fallback=True)
    assert "SXR8" in result.prices
    assert result.prices["SXR8"].close > 0
    assert result.snapshots["SXR8"].source == "fallback_static"
