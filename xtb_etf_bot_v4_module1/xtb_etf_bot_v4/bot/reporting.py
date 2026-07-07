from __future__ import annotations
import os, re, requests
from .portfolio import HoldingView
from .risk import OrderPlan


def fmt(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:.2f}" if abs(x) >= 10 else f"{x:.4f}"


def clean_html(s: str) -> str:
    return re.sub(r"</?b>", "", s).replace("&lt;", "<").replace("&gt;", ">")


def send_telegram(message: str) -> bool:
    token = (os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("Telegram credentials missing. Message below:\n")
        print(clean_html(message))
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True
        }, timeout=15)
        if r.status_code == 200:
            return True
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": clean_html(message)}, timeout=15)
    except Exception as exc:
        print(f"Telegram error: {exc}")
    return False


def portfolio_report(views: dict[str, HoldingView], portfolio_value: float, regime: str, score: int, details: str) -> str:
    lines = [
        "📊 <b>ETF BOT V4 — PORTFOLIO STATUS</b>",
        f"Portfolio est.: <b>{portfolio_value:.2f} EUR</b>",
        f"Regime: <b>{regime}</b> / score {score}/100",
        details, "", "Allocation gaps:"
    ]
    for v in sorted(views.values(), key=lambda x: x.target_weight, reverse=True):
        lines.append(f"• {v.name}: target {v.target_weight:.1%}, actual {v.actual_weight:.1%}, gap {v.gap_eur:+.2f} EUR")
    return "\n".join(lines)


def order_message(name: str, view: HoldingView, plan: OrderPlan, regime: str, score: int, details: str, portfolio_value: float, reserve: float, deployable: float) -> str:
    tp_lines = ""
    if plan.tp1 is not None:
        tp_lines += f"• TP1: <b>{fmt(plan.tp1)}</b> — sell {plan.tp1_sell_pct}%\n"
    if plan.tp2 is not None:
        tp_lines += f"• TP2: <b>{fmt(plan.tp2)}</b> — sell {plan.tp2_sell_pct}%\n"
    if not tp_lines:
        tp_lines = "• TP: <b>none</b> — rebalance discipline only\n"
    rr = "n/a" if plan.reward_risk is None else f"{plan.reward_risk:.2f}"
    return (
        f"📌 <b>ETF BOT V4 — ACTION REQUIRED</b>\n"
        f"Instrument: <b>{name}</b> — {view.meta['label']}\n"
        f"XTB: <b>{view.meta['xtb_symbol']}</b> | Yahoo: <b>{view.meta['yf_symbol']}</b>\n"
        f"Sleeve: <b>{view.meta.get('sleeve')}</b> | Target: <b>{view.target_weight:.1%}</b> | Actual: <b>{view.actual_weight:.1%}</b>\n"
        f"Gap: <b>{view.gap_eur:.2f} EUR</b> | Portfolio est.: <b>{portfolio_value:.2f} EUR</b>\n"
        f"Free cash reserve: <b>{reserve:.2f} EUR</b> | Deployable cash: <b>{deployable:.2f} EUR</b>\n\n"
        f"Regime: <b>{regime}</b> / score {score}/100\n{details}\n\n"
        f"Order to place manually in XTB:\n"
        f"• Type: <b>{plan.order_type}</b>\n"
        f"• Entry price: <b>{fmt(plan.entry)}</b>\n"
        f"• Amount: <b>{plan.amount_eur:.2f} EUR</b>\n"
        f"• Quantity estimate: <b>{plan.qty:.4f}</b>\n\n"
        f"Protection immediately after fill:\n"
        f"• Stop Loss: <b>{fmt(plan.sl)}</b>\n"
        f"{tp_lines}"
        f"• Trailing rule: {plan.trailing}\n"
        f"• Reward/risk to TP1: <b>{rr}</b>\n\n"
        f"Rule: if filled, protection must be placed before any new buy. No polite exceptions."
    )
