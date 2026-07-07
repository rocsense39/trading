# XTB ETF Bot V5.3

Decision-engine release with three gates:

1. Portfolio gate: ETF must be underweight.
2. Trend gate: price must satisfy `price > EMA20 > EMA50`.
3. Confirmation gate: a bullish candle pattern must be present.

Bullish confirmations supported:

- Bullish engulfing
- Hammer
- Piercing line
- Morning star
- Inside bar breakout
- Strong bullish candle
- 20-bar breakout

Run:

```bash
pip install -r requirements.txt
pytest -q
python main.py --once
python main.py --once --telegram
```

Telegram requires `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` environment variables.
