from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class Sleeve(str, Enum):
    CORE = "core"
    CORE_GROWTH = "core_growth"
    QUALITY = "quality"
    SATELLITE = "satellite"

@dataclass(frozen=True)
class Instrument:
    key: str
    xtb_symbol: str
    yf_symbol: str
    sleeve: Sleeve
    target_weight: float
    qty: float = 0.0
    avg_price: float = 0.0

@dataclass(frozen=True)
class AllocationRow:
    key: str
    target_weight: float
    current_value_eur: float
    actual_weight: float
    target_value_eur: float
    gap_eur: float
    gap_pct: float
    underweight: bool

@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    close: float
    ema20: float
    ema50: float
    ema150: float
    atr20: float
    rsi14: float
    hh20: float
    ll20: float
    source: str = "unknown"
