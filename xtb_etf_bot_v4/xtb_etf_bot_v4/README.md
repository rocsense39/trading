# XTB ETF Bot V4

Module 1: configuration, typed models, allocation gaps, and cash sizing.

This module deliberately fixes the V3 bug where the bot showed only ~€2 deployable cash despite €75.08 free cash.
With equity €939.06 and 5% reserve, reserve is €46.95 and deployable cash is €28.13.

## Run in Colab

```python
%cd /content/trading
!python xtb_etf_bot_v4/main.py --once
```

## Test

```python
%cd /content/trading/xtb_etf_bot_v4
!pytest -q
```
