# XTB ETF Bot V5.2

Quiet-data version: no noisy Yahoo fallback messages for `AIFS.F` / `AIFS.SG`.

Run once:

```bash
pip install -r requirements.txt
pytest -q
python main.py --once
```

Run once and send Telegram:

```bash
export TELEGRAM_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python main.py --once --telegram
```

Run continuous scan every 15 minutes:

```bash
python main.py --telegram --sleep 900
```
