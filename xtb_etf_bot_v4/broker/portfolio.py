from dataclasses import dataclass
from market.data import get_snapshot

@dataclass
class PositionView:
    name: str; meta: dict; snap: object; value_eur: float
    target_weight: float; actual_weight: float; gap_eur: float; gap_pct: float


def fx_to_eur(cfg, currency):
    currency=(currency or 'EUR').upper()
    if currency=='EUR': return 1.0
    if currency=='USD': return 1.0/float(cfg['settings'].get('eur_usd',1.08))
    if currency=='GBP': return 1.0/float(cfg['settings'].get('eur_gbp',0.86))
    return 1.0


def position_value(cfg, name, price, currency):
    pos=cfg.get('positions',{}).get(name,{})
    return float(pos.get('qty',0))*price*fx_to_eur(cfg,currency)


def build_view(cfg):
    free_cash=float(cfg['settings'].get('free_cash_eur',0))
    views={}; invested=0.0
    for name,meta in cfg['etfs'].items():
        if not meta.get('enabled',True): continue
        snap=get_snapshot(meta['yf_symbol'])
        if not snap:
            print(f'{name}: no market data'); continue
        val=position_value(cfg,name,snap.close,meta.get('currency','EUR'))
        invested+=val; views[name]={'meta':meta,'snap':snap,'value_eur':val}
    total=invested+free_cash
    # Never let portfolio total exceed configured equity lower than holdings, but use real visible invested+cash for allocation math.
    if total<=0: total=float(cfg['settings'].get('equity_eur',0))
    out={}
    for name,item in views.items():
        target=float(item['meta'].get('target_weight',0))
        actual=item['value_eur']/total if total else 0
        gap=target*total-item['value_eur']
        out[name]=PositionView(name,item['meta'],item['snap'],item['value_eur'],target,actual,gap,target-actual)
    return out,total


def deployable_cash(cfg):
    equity=float(cfg['settings'].get('equity_eur',0))
    free=float(cfg['settings'].get('free_cash_eur',0))
    reserve_pct=float(cfg['settings'].get('cash_reserve_pct_of_equity',0.05))
    reserve=reserve_pct*equity
    return max(0.0, free-reserve), reserve
