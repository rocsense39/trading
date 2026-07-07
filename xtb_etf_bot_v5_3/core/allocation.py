from .models import AllocationRow, Instrument, MarketSnapshot

def deployable_cash(equity: float, free_cash: float, reserve_pct: float) -> tuple[float, float]:
    reserve = equity * reserve_pct
    return max(0.0, free_cash - reserve), reserve

def build_allocation_rows(equity: float, instruments: list[Instrument], snapshots: dict[str, MarketSnapshot]) -> list[AllocationRow]:
    rows: list[AllocationRow] = []
    for inst in instruments:
        snap = snapshots[inst.key]
        current = inst.qty * snap.close
        target = equity * inst.target_weight
        actual_weight = current / equity if equity else 0.0
        gap = target - current
        rows.append(AllocationRow(
            key=inst.key,
            target_weight=inst.target_weight,
            actual_weight=actual_weight,
            current_value_eur=current,
            target_value_eur=target,
            gap_eur=gap,
            gap_pct=inst.target_weight - actual_weight,
        ))
    return sorted(rows, key=lambda r: r.gap_eur, reverse=True)

def size_order(row: AllocationRow, deployable: float, min_order: float, max_order: float) -> tuple[bool, float, str]:
    amount = min(row.gap_eur, deployable, max_order)
    if row.gap_eur <= 0:
        return False, 0.0, "not underweight"
    if amount < min_order:
        return False, amount, f"order {amount:.2f} EUR below min_order_eur {min_order:.2f}"
    return True, amount, "accepted"
