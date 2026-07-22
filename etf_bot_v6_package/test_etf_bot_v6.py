import json
from pathlib import Path

import pandas as pd

import etf_bot_v6_long_term as bot


def test_config_weights_total_100_percent():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    assert round(sum(x["target_weight"] for x in cfg["instruments"]), 8) == 1.0


def test_closed_daily_removes_today(monkeypatch):
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=260, freq="D")
    base = pd.Series(range(260), index=idx, dtype=float) + 100
    raw = pd.DataFrame({"Open": base, "High": base + 1, "Low": base - 1, "Close": base, "Volume": 1000})
    class YF:
        @staticmethod
        def download(*args, **kwargs):
            return raw.copy()
    monkeypatch.setattr(bot, "yf", YF)
    bot._CACHE.clear()
    result = bot.download("TEST")
    assert result.index[-1].date() < date_today()


def date_today():
    from datetime import date
    return date.today()


def test_core_has_no_stop_or_take_profit_concept():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    text = Path(bot.__file__).read_text(encoding="utf-8")
    assert "stop_loss" not in text
    assert "take_profit" not in text
    assert cfg["settings"]["rebalance_band_abs"] == 0.02


def test_stale_configuration_pauses():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    inst = bot.instruments_from_config(cfg)[0]
    decision, reason, multiplier = bot.decision_for(inst, 0.2, 0.2, None, "RISK ON", cfg, True)
    assert decision == "PAUSE"
    assert multiplier == 0


def test_legacy_is_review_not_buy():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    inst = bot.instruments_from_config(cfg)[-1]
    decision, _, _ = bot.decision_for(inst, 0.2, -0.2, None, "RISK ON", cfg, False)
    assert decision == "REVIEW"


def test_iuhc_target_is_two_percent_and_never_buy():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    item = next(x for x in cfg["instruments"] if x["key"] == "IUHC_LEGACY")
    assert item["target_weight"] == 0.02
    assert item["allow_buy"] is False


def test_weekly_order_range_is_material():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    assert cfg["settings"]["min_order_eur"] == 25.0
    assert cfg["settings"]["max_order_eur"] == 100.0


def test_extended_price_waits():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    inst = bot.instruments_from_config(cfg)[0]
    snap = bot.Snapshot(120, 100, 98, 90, 5, 75, 120, 100, "test")
    decision, _, _ = bot.decision_for(inst, 0.1, 0.3, snap, "RISK ON", cfg, False)
    assert decision == "WAIT"


def test_missing_data_never_buys_reserve():
    cfg = bot.load_config(Path(__file__).with_name("portfolio_v6_long_term.json"))
    inst = next(i for i in bot.instruments_from_config(cfg) if i.sleeve == "reserve")
    decision, _, multiplier = bot.decision_for(inst, 0.0, 0.05, None, "RISK ON", cfg, False)
    assert decision == "PAUSE"
    assert multiplier == 0
