# Trading Bot V3

Bot profesional unificat pentru:
- ETF DCA
- Swing alerts
- AI Infrastructure watchlist
- Market regime
- Telegram alerts

## Instalare în Colab

```bash
!pip install -r requirements.txt
```

## Setare Telegram

```python
import os, getpass
os.environ["TELEGRAM_TOKEN"] = getpass.getpass("TELEGRAM_TOKEN: ").strip()
os.environ["TELEGRAM_CHAT_ID"] = getpass.getpass("TELEGRAM_CHAT_ID: ").strip()
```

## Rulare o singură scanare

```bash
RUN_FOREVER=0 python bot.py
```

## Rulare continuă

```bash
python bot.py
```

## Fișiere importante

- `bot.py` — punctul de pornire
- `config.json` — univers, alocări, setări
- `state.json` — cooldown alerte, creat automat
- `engines/` — logica de semnale
- `core/` — infrastructură: date, Telegram, config, indicatori

Botul NU cumpără automat. Trimite doar sugestii.
