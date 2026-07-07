def threshold(sleeve):
    return 50 if sleeve=='quality' else 60 if sleeve in {'core','core_growth'} else 70

def score_candidate(view, regime, regime_score):
    snap=view.snap; sleeve=view.meta.get('sleeve','satellite')
    score=0; reasons=[]
    if view.gap_eur <= 0: return None, ['not underweight']
    if view.gap_pct > 0.08: score+=30; reasons.append('large allocation gap')
    elif view.gap_pct > 0.03: score+=20; reasons.append('medium allocation gap')
    else: score+=10; reasons.append('small allocation gap')
    if regime=='RISK ON': score+=20; reasons.append('risk-on regime')
    elif regime=='NEUTRAL': score+=10; reasons.append('neutral regime')
    else: score-=20; reasons.append('risk-off regime')
    if snap.close>snap.ema20>snap.ema50: score+=20; reasons.append('strong short-term trend')
    elif snap.close>snap.ema50: score+=12; reasons.append('above EMA50')
    elif snap.close>snap.ema150: score+=6; reasons.append('above EMA150')
    else: score-=12; reasons.append('weak trend')
    if snap.rsi14>=50: score+=10; reasons.append('RSI supportive')
    else: reasons.append('RSI weak')
    if sleeve=='quality': score+=10
    if sleeve=='satellite' and snap.close<snap.ema50: score-=10
    score=max(0,min(100,score))
    return score,reasons
