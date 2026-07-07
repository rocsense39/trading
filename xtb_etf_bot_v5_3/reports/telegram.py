from __future__ import annotations

import os
import requests


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for i in range(0, len(text), 3900):
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": text[i:i+3900]}, timeout=15)
            ok = ok and r.status_code == 200
        except Exception:
            ok = False
    return ok
