from __future__ import annotations

import os
import re
import requests


def _strip_html(text: str) -> str:
    text = re.sub(r"</?b>", "", text)
    return (
        text.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
    )


def send_telegram(message: str) -> bool:
    token = (os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()

    if not token or not chat_id:
        print("Telegram token/chat_id lipsă. Mesaj:")
        print(_strip_html(message))
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        print("Telegram status:", r.status_code)
        print("Telegram response:", r.text[:500])
        if r.status_code == 200:
            return True

        fallback = {
            "chat_id": chat_id,
            "text": _strip_html(message),
            "disable_web_page_preview": True,
        }
        r2 = requests.post(url, json=fallback, timeout=15)
        print("Telegram fallback status:", r2.status_code)
        print("Telegram fallback response:", r2.text[:500])
        return r2.status_code == 200

    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False
