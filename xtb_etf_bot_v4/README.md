# XTB ETF Bot V4

Portfolio-first ETF alert bot. It does not place live orders by default. It produces one disciplined order alert with SL/TP instructions.

Run in Colab:

```python
%cd /content
!unzip -o xtb_etf_bot_v4.zip
%cd xtb_etf_bot_v4
!pip install -r requirements.txt
!python main.py --once
```

Telegram is optional. Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` as environment variables.
