from core.models import AllocationRow, Instrument, MarketSnapshot
from strategy.scoring import score_candidate, rank_candidates


def snap(close=105, ema20=103, ema50=101, ema150=99, rsi=58, confirmations=("Bullish engulfing",), source="yahoo"):
    return MarketSnapshot("SXR8", 104, 106, 103, close, ema20, ema50, ema150, 2, rsi, 107, 95, source, confirmations)


def row(key="SXR8", gap=200, gap_pct=.20):
    return AllocationRow(key, .45, .25, 250, 450, gap, gap_pct)


def test_buy_requires_all_three_gates():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", .45, 2.5)
    result = score_candidate(row(), inst, snap())
    assert result.decision == "BUY"
    assert result.portfolio_gate.startswith("✅")
    assert result.trend_gate.startswith("✅")
    assert result.confirmation_gate.startswith("✅")


def test_no_candle_confirmation_becomes_watch_not_buy():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", .45, 2.5)
    result = score_candidate(row(), inst, snap(confirmations=()))
    assert result.decision == "WATCH"
    assert result.confirmation_gate.startswith("⏳")


def test_trend_gate_requires_price_above_ema20_above_ema50():
    inst = Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", .45, 2.5)
    result = score_candidate(row(), inst, snap(close=100, ema20=103, ema50=101, ema150=99))
    assert result.decision == "HOLD"
    assert result.trend_gate.startswith("❌")


def test_fallback_data_cannot_be_buy():
    inst = Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", "satellite", .05, 0)
    r = AllocationRow("AIINFRA", .05, 0, 0, 50, 47, .05)
    result = score_candidate(r, inst, snap(source="static_fallback"))
    assert result.decision != "BUY"
    assert result.confidence <= 20


def test_rank_candidates_prefers_confirmed_core_buy():
    rows = [row("SXR8", 200, .20), AllocationRow("QUALITY", .125, 0, 0, 125, 120, .125)]
    instruments = {
        "SXR8": Instrument("SXR8", "SXR8.DE", "SXR8.DE", "core", .45, 2.5),
        "QUALITY": Instrument("QUALITY", "IS3Q.DE", "IS3Q.DE", "quality", .125, 0),
    }
    snapshots = {
        "SXR8": snap(),
        "QUALITY": MarketSnapshot("QUALITY", 76, 77, 75, 76, 78, 77, 75, 1, 30, 79, 74, "yahoo", ()),
    }
    ranked = rank_candidates(rows, instruments, snapshots)
    assert ranked[0].key == "SXR8"
    assert ranked[0].decision == "BUY"
