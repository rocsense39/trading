from __future__ import annotations

def simple_regime() -> tuple[str, int, str]:
    # Module 3 keeps regime deterministic; Module 4 can replace with live SPY/QQQ/VIX logic.
    return "RISK ON", 90, "static module-3 regime"
