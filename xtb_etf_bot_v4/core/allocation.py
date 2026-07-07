from __future__ import annotations

from .models import Account, AllocationRow, OrderSizing, Position, PriceSnapshot


def build_allocation_table(
    *,
    equity_eur: float,
    free_cash_eur: float,
    targets: dict[str, float],
    positions: dict[str, Position],
    prices: dict[str, PriceSnapshot],
) -> list[AllocationRow]:
    rows: list[AllocationRow] = []
    invested_value = 0.0
    values: dict[str, float] = {}

    for key in targets:
        pos = positions.get(key, Position(key=key, qty=0.0, avg_price=0.0))
        px = prices.get(key)
        value = pos.qty * px.close if px else 0.0
        values[key] = value
        invested_value += value

    # Use actual account equity as denominator. This prevents hidden portfolio-value bugs.
    denominator = equity_eur if equity_eur > 0 else invested_value + free_cash_eur

    for key, target_weight in targets.items():
        current = values[key]
        actual = current / denominator if denominator else 0.0
        target_value = target_weight * denominator
        gap = target_value - current
        rows.append(
            AllocationRow(
                key=key,
                target_weight=target_weight,
                current_value_eur=current,
                actual_weight=actual,
                target_value_eur=target_value,
                gap_eur=gap,
                underweight=gap > 0,
            )
        )
    return rows


def size_order(account: Account, key: str, allocation_gap_eur: float) -> OrderSizing:
    requested = max(0.0, allocation_gap_eur)
    deployable = account.deployable_cash_eur
    final = min(requested, deployable, account.max_order_eur)
    accepted = final >= account.min_order_eur
    if accepted:
        reason = "accepted"
    else:
        reason = (
            f"order {final:.2f} EUR below min_order_eur {account.min_order_eur:.2f}; "
            f"free_cash={account.free_cash_eur:.2f}, reserve={account.reserve_eur:.2f}, "
            f"deployable={deployable:.2f}, gap={allocation_gap_eur:.2f}"
        )
    return OrderSizing(
        key=key,
        requested_eur=requested,
        final_order_eur=final,
        deployable_cash_eur=deployable,
        reserve_eur=account.reserve_eur,
        accepted=accepted,
        reason=reason,
    )
