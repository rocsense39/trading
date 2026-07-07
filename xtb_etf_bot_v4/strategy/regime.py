from market.data import get_ohlcv
from market.indicators import add_indicators

def classify_regime(cfg):
    score=50; notes=[]; syms=cfg.get('regime_symbols',{})
    for label,sym in [('S&P',syms.get('sp500','SPY')),('Nasdaq',syms.get('nasdaq','QQQ'))]:
        df=add_indicators(get_ohlcv(sym, period='9mo', interval='1d'))
        if df.empty: notes.append(f'{label}: n/a'); continue
        r=df.iloc[-1]; c,e20,e50,e150=map(float,[r.Close,r.EMA20,r.EMA50,r.EMA150])
        if c>e20>e50>e150: score+=15; notes.append(f'{label}: strong trend')
        elif c>e50>e150: score+=8; notes.append(f'{label}: positive')
        elif c<e50: score-=12; notes.append(f'{label}: weak')
    vdf=get_ohlcv(syms.get('vix','^VIX'), period='3mo', interval='1d')
    if not vdf.empty:
        v=float(vdf.iloc[-1].Close)
        if v<18: score+=10; notes.append(f'VIX calm {v:.2f}')
        elif v>25: score-=20; notes.append(f'VIX high {v:.2f}')
        else: notes.append(f'VIX neutral {v:.2f}')
    score=max(0,min(100,score))
    return ('RISK ON' if score>=70 else 'RISK OFF' if score<40 else 'NEUTRAL'), score, '; '.join(notes)
