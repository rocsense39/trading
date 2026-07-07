# XTB ETF Bot V4 Clean — Module 4

Adds SL/TP discipline to the working Module 3 scoring engine.

Run:

```bash
pip install -r requirements.txt
pytest -q
python main.py --once
```

Module 4 adds:
- Core ETF plan: SL + partial TP1 only, no full exit.
- Quality ETF plan: SL + no fixed TP, rebalance discipline.
- Satellite ETF plan: SL + TP1/TP2 + trailing remainder.
