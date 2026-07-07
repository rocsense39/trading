from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Sleeve(str, Enum):
    CORE = "core"
    CORE_GROWTH = "core_growth"
    QUALITY = "quality"
    SATELLITE = "satellite"


@dataclass(frozen=True)
class Account:
    base_currency: str
    equity_eur: float
    free_cash_eur: float
    cash_reserve_pct_of_equity: float
    min_order_eur: float
    max_order_eur: float
    one_new_entry_per_day: bool = True

    @property
    def reserve_eur(self) -> float:
        return self.equity_eur * self.cash_reserve_pct_of_equity

    @property
    def deployable_cash_eur(self) -> float:
        return max(0.0, self.free_cash_eur - self.reserve_eur)


@dataclass(frozen=True)
class Instrument:
    key: str
    xtb_symbol: str
    yf_symbol: str
    sleeve: Sleeve
    currency: str = "EUR"


@dataclass(frozen=True)
class Position:
    key: str
    qty: float
    avg_price: float


@dataclass(frozen=True)
class PriceSnapshot:
    key: str
    close: float


@dataclass(frozen=True)
class AllocationRow:
    key: str
    target_weight: float
    current_value_eur: float
    actual_weight: float
    target_value_eur: float
    gap_eur: float
    underweight: bool


@dataclass(frozen=True)
class OrderSizing:
    key: str
    requested_eur: float
    final_order_eur: float
    deployable_cash_eur: float
    reserve_eur: float
    accepted: bool
    reason: str
