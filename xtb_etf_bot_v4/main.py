import argparse, json, time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from broker.portfolio import build_view, deployable_cash
from reports.telegram import send
from storage.state import State
from strategy.regime import classify_regime
from strategy.scoring import score_candidate, threshold
from strategy.sltp import entry_plan, protection_plan, reward_risk_ok

MKT_TZ=ZoneInfo('Europe/Berlin')
CONFIG=Path('config/portfolio.json')

def fmt(x): return f'{float(x):.2f}'

def load_config(): return json.loads(CONFIG.read_text())

def startup(cfg):
    lines=['✅ <b>ETF Bot V4 started</b>','Targets:']
    for n,m in cfg['etfs'].items():
        if m.get('enabled',True): lines.append(f'• {n}: <b>{float(m["target_weight"]):.1%}</b> — {m.get("sleeve")}')
    lines.append('\nNo single stocks. No gold. One new entry/day. Mandatory SL/TP discipline.')
    return '\n'.join(lines)

def portfolio_report(cfg, views, total, regime, score, details):
    lines=['📊 <b>ETF BOT V4 — PORTFOLIO STATUS</b>',f'Portfolio est.: <b>{total:.2f} EUR</b>',f'Regime: <b>{regime}</b> / score {score}/100',details,'','Allocation gaps:']
    for n,v in sorted(views.items(), key=lambda kv: kv[1].target_weight, reverse=True):
        lines.append(f'• {n}: target {v.target_weight:.1%}, actual {v.actual_weight:.1%}, gap {v.gap_eur:+.2f} EUR')
    cash,reserve=deployable_cash(cfg)
    lines += ['', f'Cash: free {cfg["settings"].get("free_cash_eur",0):.2f} EUR | reserve {reserve:.2f} EUR | deployable {cash:.2f} EUR']
    return '\n'.join(lines)

def order_message(cfg, name, v, regime, score, details, deployable):
    meta=v.meta; snap=v.snap
    typ,entry=entry_plan(meta,snap); prot=protection_plan(meta,snap,entry); ok,rr=reward_risk_ok(prot,entry)
    if not ok: return None, f'{name}: rejected — reward/risk {rr:.2f} below 1.50'
    min_order=float(cfg['settings'].get('min_order_eur',10)); max_order=float(cfg['settings'].get('max_order_eur',50))
    amount=min(v.gap_eur, deployable, max_order)
    if amount < min_order: return None, f'{name}: rejected — order {amount:.2f} EUR below min_order_eur {min_order:.2f}; deployable={deployable:.2f}, gap={v.gap_eur:.2f}'
    qty=amount/entry if entry>0 else 0
    tp_lines=''
    if float(prot.get('tp1') or 0)>0: tp_lines += f'• TP1: <b>{fmt(prot["tp1"])}</b> — sell {prot.get("tp1_sell_pct",0)}%\n'
    if float(prot.get('tp2') or 0)>0: tp_lines += f'• TP2: <b>{fmt(prot["tp2"])}</b> — sell {prot.get("tp2_sell_pct",0)}%\n'
    if not tp_lines: tp_lines='• TP: <b>none</b> — rebalance discipline only\n'
    msg=(f'📌 <b>ETF BOT V4 — ACTION REQUIRED</b>\n'
         f'Instrument: <b>{name}</b> — {meta["label"]}\nXTB: <b>{meta["xtb_symbol"]}</b> | Yahoo: <b>{meta["yf_symbol"]}</b>\n'
         f'Sleeve: <b>{meta.get("sleeve")}</b> | Target: <b>{v.target_weight:.1%}</b> | Actual: <b>{v.actual_weight:.1%}</b>\n'
         f'Gap: <b>{v.gap_eur:.2f} EUR</b>\n\nRegime: <b>{regime}</b> / score {score}/100\n{details}\n\n'
         f'Order to place in XTB:\n• Type: <b>{typ}</b>\n• Entry price: <b>{fmt(entry)}</b>\n• Amount: <b>{amount:.2f} EUR</b>\n• Qty estimate: <b>{qty:.4f}</b>\n\n'
         f'Protection immediately after fill:\n• Stop Loss: <b>{fmt(prot["sl"])}</b>\n{tp_lines}• Trail: {prot["trail"]}\n• Reward/risk to TP1: <b>{rr:.2f}</b>\n\nNo protection = no next buy.')
    return msg, None

def run_once():
    cfg=load_config(); state=State(); regime,regime_score,details=classify_regime(cfg)
    print(f'Regime: {regime} score={regime_score} | {details}')
    views,total=build_view(cfg)
    if state.alert_once('REPORT:'+datetime.now(MKT_TZ).date().isoformat(),20): send(portfolio_report(cfg,views,total,regime,regime_score,details))
    if not state.daily_allowed(cfg['settings'].get('one_new_entry_per_day',True)):
        print('Daily entry already used.'); return
    print('Candidate scores:')
    ranked=[]
    for n,v in views.items():
        sc,reasons=score_candidate(v,regime,regime_score)
        if sc is None:
            print(f'{n}: no buy — {"; ".join(reasons)}'); continue
        th=threshold(v.meta.get('sleeve'))
        print(f'{n}: score={sc} threshold={th} — {"; ".join(reasons)}; score {sc}/threshold {th}')
        if sc>=th: ranked.append((sc,v.gap_eur,n,v))
    if not ranked: print('No valid candidate.'); return
    ranked.sort(reverse=True)
    deployable,reserve=deployable_cash(cfg)
    name,v=ranked[0][2],ranked[0][3]
    msg,err=order_message(cfg,name,v,regime,regime_score,details,deployable)
    if err: print(err); print(f'Candidate {name} rejected by sizing or reward/risk.'); return
    if state.alert_once(f'ORDER:{name}:{datetime.now(MKT_TZ).date().isoformat()}', int(cfg['settings'].get('min_alert_interval_hours',6))):
        send(msg); state.mark_daily(name)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--once',action='store_true'); args=ap.parse_args()
    cfg=load_config(); send(startup(cfg))
    while True:
        print(f'[{datetime.now(MKT_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")}] scan')
        run_once()
        if args.once: break
        time.sleep(int(cfg['settings'].get('sleep_seconds',900)))
if __name__=='__main__': main()
