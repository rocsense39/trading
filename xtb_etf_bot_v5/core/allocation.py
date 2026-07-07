from __future__ import annotations
from .models import AllocationRow, Instrument, MarketSnapshot

def cash_reserve_eur(equity_eur: float, reserve_pct: float) -> float:
    return max(0.0, equity_eur * reserve_pct)

def deployable_cash_eur(free_cash_eur: float, equity_eur: float, reserve_pct: float) -> float:
    return max(0.0, free_cash_eur - cash_reserve_eur(equity_eur, reserve_pct))

def allocation_rows(instruments: dict[str, Instrument], snapshots: dict[str, MarketSnapshot], equity_eur: float) -> list[AllocationRow]:
    rows: list[AllocationRow] = []
    for key, inst in instruments.items():
        snap = snapshots.get(key)
        price = snap.close if snap else inst.avg_price
        current_value = inst.qty * price
        actual_weight = current_value / equity_eur if equity_eur > 0 else 0.0
        target_value = inst.target_weight * equity_eur
        gap = target_value - current_value
        gap_pct = inst.target_weight - actual_weight
        rows.append(AllocationRow(
            key=key,
            target_weight=inst.target_weight,
            current_value_eur=current_value,
            actual_weight=actual_weight,
            target_value_eur=target_value,
            gap_eur=gap,
            gap_pct=gap_pct,
            underweight=gap > 0,
        ))
    return sorted(rows, key=lambda r: r.gap_eur, reverse=True)

def propose_order_eur(row: AllocationRow, deployable_cash: float, min_order_eur: float, max_order_eur: float) -> tuple[bool, float, str]:
    amount = min(max_order_eur, deployable_cash, max(0.0, row.gap_eur))
    if amount < min_order_eur:
        return False, amount, f"order {amount:.2f} EUR below min_order_eur {min_order_eur:.2f}"
    return True, amount, "accepted"
