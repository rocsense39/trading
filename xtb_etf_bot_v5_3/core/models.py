from dataclasses import dataclass, field


@dataclass(frozen=True)
class Instrument:
    key: str
    xtb_symbol: str
    yf_symbol: str
    sleeve: str
    target_weight: float
    qty: float = 0.0
    yf_symbol_candidates: list[str] = field(default_factory=list)
    fallback_close: float | None = None
    fallback_ema20: float | None = None
    fallback_ema50: float | None = None
    fallback_ema150: float | None = None
    fallback_atr20: float | None = None
    fallback_rsi14: float | None = None
    fallback_high20: float | None = None
    fallback_low20: float | None = None


@dataclass(frozen=True)
class AllocationRow:
    key: str
    target_weight: float
    actual_weight: float
    current_value_eur: float
    target_value_eur: float
    gap_eur: float
    gap_pct: float


@dataclass(frozen=True)
class MarketSnapshot:
    key: str
    open: float
    high: float
    low: float
    close: float
    ema20: float
    ema50: float
    ema150: float
    atr20: float
    rsi14: float
    high20: float
    low20: float
    source: str = "unknown"
    confirmations: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateResult:
    key: str
    decision: str  # BUY, WATCH, HOLD
    confidence: int
    portfolio_gate: str
    trend_gate: str
    confirmation_gate: str
    reasons: list[str]
    confirmations: tuple[str, ...]


# Backward-compatible name used by older modules/tests.
ScoreResult = GateResult


@dataclass(frozen=True)
class TradePlan:
    key: str
    action: str
    order_eur: float
    qty_est: float
    entry: float
    stop_loss: float | None
    tp1: float | None
    tp1_sell_pct: float
    tp2: float | None
    tp2_sell_pct: float
    trailing_rule: str
    reward_risk: float | None
