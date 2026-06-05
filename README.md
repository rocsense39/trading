# Bot AI Infrastructure Watch

Rulează alerte Telegram pentru MES, IUHC, GNOM, BOTZ, COPX, XLUS și SGLN/IGLN/IAUP.

## Colab

```python
!pip install -q yfinance pandas requests
import os, getpass
os.environ["TELEGRAM_TOKEN"] = getpass.getpass("TELEGRAM_TOKEN: ").strip()
os.environ["TELEGRAM_CHAT_ID"] = getpass.getpass("TELEGRAM_CHAT_ID: ").strip()
```

Apoi:
```bash
!python bot_ai_infra_watch.py
```

Botul nu tranzacționează automat. Trimite doar alerte și planuri orientative.
