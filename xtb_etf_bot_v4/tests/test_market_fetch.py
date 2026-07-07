from core.config import BotConfig
from market.data import fetch_market


def test_fetch_market_static_fallback_has_prices():
    cfg = BotConfig.from_file("config/portfolio.json")
    result = fetch_market(cfg, allow_static_fallback=True)
    assert "SXR8" in result.prices
    assert result.prices["SXR8"].close > 0
