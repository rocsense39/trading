# ETF Portfolio Steward V6.0

This version is designed for long-term ETF accumulation, not swing trading.

## Main changes

- Closed Daily and Weekly data instead of 1h candles.
- Dynamic SPY/QQQ/VIX regime instead of permanent `RISK ON 90`.
- No stop-loss, take-profit or trailing stop for strategic ETF holdings.
- Rebalancing bands and controlled contributions.
- Persistent Telegram deduplication.
- Stale holdings protection: recommendations pause after seven days unless the
  account quantities, equity and cash are updated.
- Foreign listings are converted to EUR.
- Missing data never receives a synthetic price.

## Colab

Upload these files into the same Colab session:

- `etf_bot_v6_long_term.py`
- `portfolio_v6_long_term.json`

Then run:

```python
!pip install pandas requests yfinance
!python etf_bot_v6_long_term.py --config portfolio_v6_long_term.json --once
```

Telegram:

```python
import os
os.environ["TELEGRAM_TOKEN"] = "..."
os.environ["TELEGRAM_CHAT_ID"] = "..."
!python etf_bot_v6_long_term.py --config portfolio_v6_long_term.json --once --telegram
```

## Operational rule

Update `holdings_as_of`, `equity_eur`, `free_cash_eur` and every position
quantity after an executed order or a new XTB statement. `REVIEW` and
`REBALANCE REVIEW` are prompts for analysis, never automatic sell instructions.
