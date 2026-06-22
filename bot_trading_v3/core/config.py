from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("config.json")


def _deep_merge(default: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(default)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _default_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    config.setdefault("schema_version", "3.0")
    config.setdefault("settings", {})
    config.setdefault("portfolio", {}).setdefault("positions", {})
    config.setdefault("etfs", {})
    config.setdefault("swings", {})
    config.setdefault("ai_infra_watchlist", {})

    if "XXME" in config["etfs"] and "XMME" not in config["etfs"]:
        config["etfs"]["XMME"] = config["etfs"].pop("XXME")
        config["etfs"]["XMME"]["xtb_symbol"] = "XMME.DE"
        config["etfs"]["XMME"]["yf_symbol"] = "XMME.DE"

    config["etfs"].setdefault("AIFS", {
        "enabled": True,
        "xtb_symbol": "AIFS.DE",
        "yf_symbol": "AIFS.DE",
        "label": "iShares AI Infrastructure UCITS ETF",
        "target_weight": 0.10,
        "currency": "EUR"
    })

    config["etfs"]["AIFS"].update({
        "enabled": True,
        "xtb_symbol": "AIFS.DE",
        "yf_symbol": "AIFS.DE",
        "currency": "EUR"
    })

    config["swings"].pop("AIFS", None)

    config["portfolio"]["positions"].setdefault(
        "AIFS",
        {"avg_price": 8.43, "qty": 5.0036, "currency": "EUR"}
    )

    return config


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            "config.json lipsește. Rulează botul din folderul proiectului bot_trading_v3."
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    normalized = normalize_config(config)
    if normalized != config:
        backup = Path("config.backup_before_v3_migration.json")
        with backup.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)
        print(f"Config migrat. Backup: {backup}")

    return normalized
