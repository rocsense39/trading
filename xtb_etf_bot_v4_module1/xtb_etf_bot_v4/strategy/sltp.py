def entry_plan(meta, snap):
    sleeve=meta.get('sleeve','satellite')
    extended=snap.close > snap.ema20 + 1.25*snap.atr
    breakout=snap.close > snap.hh20 and snap.volume >= 1.05*snap.vol_ma
    if extended:
        return 'BUY LIMIT', min(snap.ema20, snap.close-0.65*snap.atr)
    if breakout and sleeve in {'core','core_growth','satellite'}:
        return 'BUY STOP', snap.hh20+0.10*snap.atr
    if snap.close>=snap.ema20:
        return 'BUY LIMIT', max(snap.ema20-0.15*snap.atr, snap.ema50)
    return 'BUY LIMIT', snap.ema50+0.10*snap.atr

def protection_plan(meta, snap, entry):
    sleeve=meta.get('sleeve','satellite')
    if sleeve in {'core','core_growth'}:
        sl=min(entry-2*snap.atr, snap.ema50-1*snap.atr); tp1=max(entry*1.08, snap.ema20+2*snap.atr)
        return {'style':'core','sl':sl,'tp1':tp1,'tp1_sell_pct':20,'tp2':0,'trail':'After TP1, trail with EMA20 or 2 ATR; do not fully exit.'}
    if sleeve=='quality':
        return {'style':'quality','sl':snap.ema150-snap.atr,'tp1':0,'tp1_sell_pct':0,'tp2':0,'trail':'No TP; rebalance only if weight > 15%.'}
    sl=entry-1.8*snap.atr; risk=max(entry-sl,0.01)
    return {'style':'satellite','sl':sl,'tp1':max(entry*1.08,entry+1.5*risk),'tp1_sell_pct':30,'tp2':max(entry*1.15,entry+2.5*risk),'tp2_sell_pct':30,'trail':'Trail remaining 40% with EMA20/ATR.'}

def reward_risk_ok(prot, entry):
    tp1=float(prot.get('tp1') or 0)
    if tp1<=0: return True,99.0
    risk=entry-float(prot['sl']); reward=tp1-entry
    rr=reward/risk if risk>0 else 0
    return rr>=1.5, rr
