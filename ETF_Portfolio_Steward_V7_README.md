# ETF Portfolio Steward V7

## Ce repară față de V6

- Citește automat pozițiile deschise, equity și free margin din ultimul extras XTB PDF.
- Include ordinele BUY în așteptare în alocarea proiectată.
- Scade valoarea ordinelor BUY în așteptare din numerarul neangajat.
- Distribuie o singură dată bugetul săptămânal între ETF-uri; nu mai „oferă” aceeași sumă fiecărui ETF.
- Permite override temporar pentru situațiile în care ai modificat contul după exportarea PDF-ului.
- Nu execută tranzacții și nu setează SL/TP pentru portofoliul strategic.

## Instalare în Google Colab

```python
!pip install pandas requests yfinance pdfplumber
```

Încarcă în Colab:
- `etf_portfolio_steward_v7.py`
- `portfolio_v7.json`
- ultimul extras PDF XTB

Apoi rulează:

```python
!python etf_portfolio_steward_v7.py   --config portfolio_v7.json   --account-pdf "account_latest.pdf"   --once
```

Pentru Telegram:

```python
import os
os.environ["TELEGRAM_TOKEN"] = "TOKENUL_TAU_NOU"
os.environ["TELEGRAM_CHAT_ID"] = "CHAT_ID"
```

```python
!python etf_portfolio_steward_v7.py   --config portfolio_v7.json   --account-pdf "account_latest.pdf"   --once --telegram
```

## Situația introdusă în config

Configurația livrată conține:
- override `free_cash_eur = 150`
- două Buy Limit-uri Quality, fiecare 0.27 unități:
  - 76.60
  - 75.70
- SXR8 fără ordin nou, deoarece aștepți direcția trendului.

Important: extrasul atașat afișează deja un ordin IS3Q la 76.60. Dacă acel ordin este încă prezent în noul extras, șterge-l din `extra_pending_orders`, altfel va fi numărat de două ori. Varianta ideală este să exporți un PDF nou după toate modificările și să golești lista `extra_pending_orders`.

## Actualizarea după fiecare schimbare

După cumpărare, anulare sau închidere accidentală:

1. Exportă un nou PDF din XTB.
2. Înlocuiește PDF-ul din Colab.
3. Elimină override-urile care nu mai sunt necesare.
4. Rulează din nou botul.

## Notă despre ponderi

Configurația inițială V7 folosește:
- SXR8 43%
- SXRV 22%
- Quality 12%
- AI Infrastructure 5%
- Global Infrastructure 4%
- Emerging Markets 5%
- H411 2%
- XEON 5%
- IUHC legacy 2%

Total: 100%.
