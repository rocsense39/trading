from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import load_config
from core.state import load_state
from core.telegram import send_telegram
from core.utils import esc, enabled_items
from engines.market_regime import classify_market_regime
from engines.etf_dca import build_etf_signal
from engines.swing import build_swing_signal
from engines.ai_infra import build_ai_infra_signal


TZ = ZoneInfo("Europe/Berlin")


def startup_message(config: dict) -> str:
    settings = config["settings"]
    monthly = float(settings.get("monthly_budget_ron", 500))
    cash = float(settings.get("cash_available_ron", monthly))

    lines = [
        "✅ <b>Trading Bot V3 a pornit.</b>",
        f"Buget lunar: <b>{monthly:.0f} RON</b>",
        f"Cash disponibil: <b>{cash:.0f} RON</b>",
        "",
        "📌 <b>ETF DCA:</b>",
    ]

    total_weight = 0.0
    for name, meta in enabled_items(config.get("etfs", {})):
        weight = float(meta.get("target_weight", 0))
        total_weight += weight
        lines.append(
            f"• {esc(name)}: {weight:.0%} = <b>{monthly * weight:.0f} RON</b> | "
            f"XTB {esc(meta.get('xtb_symbol', 'n/a'))}"
        )

    if abs(total_weight - 1.0) > 0.01:
        lines.append("")
        lines.append(f"⚠️ Suma alocărilor ETF este {total_weight:.1%}, nu 100%.")

    lines += [
        "",
        "🧠 Module active: ETF DCA, Swing, AI Infrastructure Watch, Market Regime.",
        "Botul NU cumpără automat; trimite doar semnale."
    ]
    return "\n".join(lines)


def run_once(config: dict, state: dict) -> None:
    regime, regime_details = classify_market_regime(config)
    print(f"Market regime: {regime} | {regime_details}")

    for name, meta in enabled_items(config.get("etfs", {})):
        try:
            msg = build_etf_signal(name, meta, config, state, regime, regime_details)
            if msg:
                ok = send_telegram(msg)
                print(f"ETF alert {'sent' if ok else 'FAILED'}: {name}")
        except Exception as exc:
            print(f"ETF error {name}: {exc}")

    for name, meta in enabled_items(config.get("swings", {})):
        try:
            msg = build_swing_signal(name, meta, config, state, regime)
            if msg:
                ok = send_telegram(msg)
                print(f"Swing alert {'sent' if ok else 'FAILED'}: {name}")
        except Exception as exc:
            print(f"Swing error {name}: {exc}")

    for name, meta in enabled_items(config.get("ai_infra_watchlist", {})):
        try:
            msg = build_ai_infra_signal(name, meta, config, state, regime, regime_details)
            if msg:
                ok = send_telegram(msg)
                print(f"AI infra alert {'sent' if ok else 'FAILED'}: {name}")
        except Exception as exc:
            print(f"AI infra error {name}: {exc}")


def main() -> None:
    config = load_config()
    state = load_state()

    today_key = f"startup:{config.get('schema_version', '3.0')}:{datetime.now(TZ).date()}"
    if config["settings"].get("send_startup_message", True) and state.get("startup_key") != today_key:
        if send_telegram(startup_message(config)):
            state["startup_key"] = today_key
            state.save()

    run_forever = os.getenv("RUN_FOREVER", "1") != "0"
    sleep_seconds = int(config["settings"].get("sleep_seconds", 900))

    while True:
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{now}] Trading Bot V3 scan...")
        run_once(config, state)

        if not run_forever:
            break

        time.sleep(sleep_seconds)
        config = load_config()
        state = load_state()


if __name__ == "__main__":
    main()
