import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


# =========================
# CONFIG
# =========================
TOKEN = "8581114074:AAF_nQRirdtd0wE7LsIA_ddZjtHdCz_QXEo"
CHAT_ID = "8631997789"

SYMBOLS = [
    "AXTI",
    "AAOI",
    "GLW",
    "JNJ",
]

INTERVAL = "60m"          # H1
PERIOD = "3mo"            # enough bars for context
SLEEP_SECONDS = 300       # check every 5 minutes

NY_TZ = ZoneInfo("America/New_York")

# Risk / position sizing
ACCOUNT_SIZE = 200.0
RISK_PER_TRADE = 0.01     # 1% risk/trade
MAX_ALLOC_PCT = 0.35      # max 35% of account in one trade

# Trend filters
EMA_FAST = 20
EMA_SLOW = 50

# Breakout logic
BREAKOUT_LOOKBACK = 20            # breakout over prior 20 candles high
BREAKOUT_BUFFER_PCT = 0.0015      # 0.15% above level to confirm
CLOSE_NEAR_HIGH_PCT = 0.35        # candle should close in top 35% of its range

# Volume / volatility logic
VOL_SMA_PERIOD = 20
VOLUME_MULTIPLIER = 1.8           # current volume >= 1.8x avg volume
ATR_PERIOD = 14
ATR_PCT_MIN = 0.007               # 0.7% minimum ATR/price
ATR_PCT_STRONG = 0.010            # 1.0% = strong environment
ATR_RISING_LOOKBACK = 3           # ATR rising vs recent bars

# Pullback-follow-through logic (optional extra entry)
ENABLE_PULLBACK_ENTRY = True
PULLBACK_LOOKBACK = 10
PULLBACK_TO_EMA_FAST_MAX_PCT = 0.01   # price may retest EMA20 within 1%
PULLBACK_VOLUME_MULT = 1.3

# Reward / stop
SL_ATR_MULT = 1.2
TP_ATR_MULT = 2.4                 # ~2R if SL_ATR_MULT=1.2
MIN_RR = 2.0

# Telegram spam control
COOLDOWN_BARS = 4                 # do not alert same symbol too often
SLEEPING_MODE_COOLDOWN_BARS = 8

# Trading hours filter (US market regular + a bit after open focus)
USE_TRADING_WINDOW = True
TRADING_WINDOWS = {
    "MORNING": ((9, 30), (12, 0)),
    "AFTERNOON": ((13, 0), (16, 0)),
}

# Optional stricter behavior by symbol
SYMBOL_SETTINGS = {
    "AXTI": {"atr_pct_min": 0.007, "volume_multiplier": 1.8},
    "AAOI": {"atr_pct_min": 0.010, "volume_multiplier": 1.8},
    "GLW":  {"atr_pct_min": 0.004, "volume_multiplier": 1.5},
    "JNJ":  {"atr_pct_min": 0.0018, "volume_multiplier": 1.4},
}


# =========================
# STATE
# =========================
last_signal_bar_time = {}
last_sleeping_bar_time = {}


# =========================
# TELEGRAM
# =========================
def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")


# =========================
# HELPERS
# =========================
def in_trading_window(now_ny: datetime):
    if not USE_TRADING_WINDOW:
        return True, "ALL_DAY"

    h, m = now_ny.hour, now_ny.minute
    current_minutes = h * 60 + m

    for label, ((sh, sm), (eh, em)) in TRADING_WINDOWS.items():
        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em
        if start_minutes <= current_minutes <= end_minutes:
            return True, label

    return False, "OUTSIDE"


def download_data(symbol: str) -> pd.DataFrame:
    df = yf.download(
        tickers=symbol,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=True,
        progress=False,
        prepost=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    # Flatten columns if needed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.title)

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["EMA20"] = out["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    out["EMA50"] = out["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    typical_price = (out["High"] + out["Low"] + out["Close"]) / 3
    cumulative_tpv = (typical_price * out["Volume"]).cumsum()
    cumulative_vol = out["Volume"].replace(0, pd.NA).cumsum()
    out["VWAP"] = cumulative_tpv / cumulative_vol

    prev_close = out["Close"].shift(1)
    tr1 = out["High"] - out["Low"]
    tr2 = (out["High"] - prev_close).abs()
    tr3 = (out["Low"] - prev_close).abs()
    out["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["ATR"] = out["TR"].rolling(ATR_PERIOD).mean()
    out["ATR_PCT"] = out["ATR"] / out["Close"]

    out["VOL_SMA20"] = out["Volume"].rolling(VOL_SMA_PERIOD).mean()

    out["RECENT_HIGH"] = out["High"].shift(1).rolling(BREAKOUT_LOOKBACK).max()
    out["RECENT_LOW"] = out["Low"].shift(1).rolling(BREAKOUT_LOOKBACK).min()

    out["CANDLE_RANGE"] = out["High"] - out["Low"]
    out["BODY"] = (out["Close"] - out["Open"]).abs()

    # Close position within candle range: 1.0 = closes at high
    out["CLOSE_LOCATION"] = (
        (out["Close"] - out["Low"]) / out["CANDLE_RANGE"].replace(0, pd.NA)
    )

    return out


def atr_is_rising(df: pd.DataFrame) -> bool:
    if len(df) < ATR_RISING_LOOKBACK + 2:
        return False

    recent = df["ATR_PCT"].iloc[-(ATR_RISING_LOOKBACK + 1):-1]
    if recent.isna().any():
        return False

    return recent.iloc[-1] > recent.mean()


def is_sleeping_market(row: pd.Series, symbol: str) -> tuple[bool, str]:
    settings = SYMBOL_SETTINGS.get(symbol, {})
    atr_pct_min = settings.get("atr_pct_min", ATR_PCT_MIN)
    volume_multiplier = settings.get("volume_multiplier", VOLUME_MULTIPLIER)

    reasons = []

    if pd.isna(row["VOL_SMA20"]) or row["Volume"] < row["VOL_SMA20"] * (volume_multiplier * 0.8):
        reasons.append("volume too low")

    if pd.isna(row["ATR_PCT"]) or row["ATR_PCT"] < atr_pct_min:
        reasons.append("ATR too low")

    if row["Close"] < row["EMA20"] and row["Close"] < row["VWAP"]:
        reasons.append("below EMA20 and VWAP")

    return (len(reasons) >= 2), " | ".join(reasons)


def breakout_signal(df: pd.DataFrame, symbol: str) -> tuple[bool, str, dict]:
    row = df.iloc[-1]
    prev = df.iloc[-2]
    settings = SYMBOL_SETTINGS.get(symbol, {})
    atr_pct_min = settings.get("atr_pct_min", ATR_PCT_MIN)
    volume_multiplier = settings.get("volume_multiplier", VOLUME_MULTIPLIER)

    reasons = []

    if pd.isna(row["RECENT_HIGH"]):
        return False, "not enough bars", {}

    breakout_level = row["RECENT_HIGH"]
    breakout_ok = row["Close"] > breakout_level * (1 + BREAKOUT_BUFFER_PCT)

    if not breakout_ok:
        reasons.append("no breakout")

    if pd.isna(row["VOL_SMA20"]) or row["Volume"] < row["VOL_SMA20"] * volume_multiplier:
        reasons.append(f"volume too low ({int(row['Volume'])} < {int(row['VOL_SMA20'] * volume_multiplier) if pd.notna(row['VOL_SMA20']) else 'n/a'})")

    if pd.isna(row["ATR_PCT"]) or row["ATR_PCT"] < atr_pct_min:
        reasons.append(f"ATR too low ({row['ATR_PCT']:.4f} < {atr_pct_min:.4f})")

    if not atr_is_rising(df):
        reasons.append("ATR not rising")

    if not (row["EMA20"] > row["EMA50"] and row["Close"] > row["EMA20"] and row["Close"] > row["VWAP"]):
        reasons.append("trend/VWAP filter failed")

    if pd.isna(row["CLOSE_LOCATION"]) or row["CLOSE_LOCATION"] < (1 - CLOSE_NEAR_HIGH_PCT):
        reasons.append("weak candle close")

    if row["Close"] <= prev["Close"]:
        reasons.append("no follow-through vs previous close")

    info = {
        "entry": float(row["Close"]),
        "breakout_level": float(breakout_level),
        "atr": float(row["ATR"]),
        "atr_pct": float(row["ATR_PCT"]),
        "ema20": float(row["EMA20"]),
        "ema50": float(row["EMA50"]),
        "vwap": float(row["VWAP"]),
        "volume": int(row["Volume"]),
        "vol_sma20": float(row["VOL_SMA20"]) if pd.notna(row["VOL_SMA20"]) else None,
        "signal_type": "BREAKOUT",
    }

    return len(reasons) == 0, " | ".join(reasons) if reasons else "valid breakout", info


def pullback_continuation_signal(df: pd.DataFrame, symbol: str) -> tuple[bool, str, dict]:
    if not ENABLE_PULLBACK_ENTRY or len(df) < max(PULLBACK_LOOKBACK, EMA_SLOW) + 5:
        return False, "pullback disabled or not enough bars", {}

    row = df.iloc[-1]
    recent = df.iloc[-PULLBACK_LOOKBACK:]

    settings = SYMBOL_SETTINGS.get(symbol, {})
    atr_pct_min = settings.get("atr_pct_min", ATR_PCT_MIN)

    reasons = []

    trend_ok = row["EMA20"] > row["EMA50"] and row["Close"] > row["VWAP"]
    if not trend_ok:
        reasons.append("trend/VWAP filter failed")

    recent_high = recent["High"].max()
    distance_from_recent_high = (recent_high - row["Close"]) / recent_high if recent_high > 0 else 1
    if distance_from_recent_high > 0.03:
        reasons.append("too far from recent highs")

    distance_to_ema20 = abs(row["Close"] - row["EMA20"]) / row["EMA20"] if row["EMA20"] > 0 else 1
    if distance_to_ema20 > PULLBACK_TO_EMA_FAST_MAX_PCT:
        reasons.append("not near EMA20 retest zone")

    if pd.isna(row["VOL_SMA20"]) or row["Volume"] < row["VOL_SMA20"] * PULLBACK_VOLUME_MULT:
        reasons.append("volume too low")

    if pd.isna(row["ATR_PCT"]) or row["ATR_PCT"] < atr_pct_min:
        reasons.append("ATR too low")

    if not atr_is_rising(df):
        reasons.append("ATR not rising")

    bullish_reclaim = row["Close"] > row["Open"] and row["Close"] > df.iloc[-2]["High"]
    if not bullish_reclaim:
        reasons.append("no bullish reclaim candle")

    info = {
        "entry": float(row["Close"]),
        "breakout_level": float(recent_high),
        "atr": float(row["ATR"]),
        "atr_pct": float(row["ATR_PCT"]),
        "ema20": float(row["EMA20"]),
        "ema50": float(row["EMA50"]),
        "vwap": float(row["VWAP"]),
        "volume": int(row["Volume"]),
        "vol_sma20": float(row["VOL_SMA20"]) if pd.notna(row["VOL_SMA20"]) else None,
        "signal_type": "PULLBACK_CONTINUATION",
    }

    return len(reasons) == 0, " | ".join(reasons) if reasons else "valid pullback continuation", info


def make_trade_plan(entry: float, atr: float) -> dict:
    stop_loss = entry - atr * SL_ATR_MULT
    take_profit = entry + atr * TP_ATR_MULT

    risk_per_share = max(entry - stop_loss, 0.01)
    reward_per_share = max(take_profit - entry, 0.01)
    rr = reward_per_share / risk_per_share

    euro_risk = ACCOUNT_SIZE * RISK_PER_TRADE
    shares_by_risk = euro_risk / risk_per_share
    max_capital = ACCOUNT_SIZE * MAX_ALLOC_PCT
    shares_by_capital = max_capital / entry
    shares = int(max(0, min(shares_by_risk, shares_by_capital)))

    capital_used = shares * entry

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_per_share": round(risk_per_share, 2),
        "reward_per_share": round(reward_per_share, 2),
        "rr": round(rr, 2),
        "shares": shares,
        "capital_used": round(capital_used, 2),
        "valid": rr >= MIN_RR and shares >= 1,
    }


def should_send_signal(symbol: str, bar_time) -> bool:
    last_time = last_signal_bar_time.get(symbol)
    if last_time is None:
        return True
    return last_time != bar_time


def should_send_sleeping(symbol: str, bar_time) -> bool:
    last_time = last_sleeping_bar_time.get(symbol)
    if last_time is None:
        return True
    return last_time != bar_time


def format_log(symbol: str, session_label: str, row: pd.Series, verdict: str) -> str:
    return (
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"[{symbol}] [{session_label}] | "
        f"Close: {row['Close']:.2f} | EMA20: {row['EMA20']:.2f} | EMA50: {row['EMA50']:.2f} | "
        f"VWAP: {row['VWAP']:.2f} | ATR: {row['ATR']:.2f} | ATR%: {row['ATR_PCT']:.4f} | "
        f"Volume: {int(row['Volume'])} | VolSMA20: {int(row['VOL_SMA20']) if pd.notna(row['VOL_SMA20']) else 0} | "
        f"{verdict}"
    )


def analyze_symbol(symbol: str) -> None:
    now_ny = datetime.now(NY_TZ)
    inside_window, session_label = in_trading_window(now_ny)

    df = download_data(symbol)
    if df.empty or len(df) < 60:
        print(f"{datetime.now()} [{symbol}] No data / not enough bars")
        return

    df = compute_indicators(df)
    row = df.iloc[-1]

    if row[["EMA20", "EMA50", "VWAP", "ATR", "ATR_PCT", "VOL_SMA20"]].isna().any():
        print(f"{datetime.now()} [{symbol}] Indicators not ready yet")
        return

    bar_time = df.index[-1]

    if USE_TRADING_WINDOW and not inside_window:
        print(format_log(symbol, session_label, row, "No signal -> outside optimal trading window"))
        return

    sleeping, sleeping_reason = is_sleeping_market(row, symbol)
    if sleeping and should_send_sleeping(symbol, bar_time):
        message = (
            f"😴 <b>MARKET SLEEPING MODE</b>\n"
            f"<b>{symbol}</b> ({INTERVAL})\n"
            f"Price: <b>{row['Close']:.2f}</b>\n"
            f"ATR%: <b>{row['ATR_PCT']:.2%}</b>\n"
            f"Volume: <b>{int(row['Volume'])}</b> vs avg <b>{int(row['VOL_SMA20'])}</b>\n"
            f"Reason: {sleeping_reason}\n\n"
            f"No trade. Cash-ul nu fuge nicăieri."
        )
        send_telegram(message)
        last_sleeping_bar_time[symbol] = bar_time

    breakout_ok, breakout_reason, breakout_info = breakout_signal(df, symbol)
    pullback_ok, pullback_reason, pullback_info = pullback_continuation_signal(df, symbol)

    if breakout_ok:
        plan = make_trade_plan(breakout_info["entry"], breakout_info["atr"])
        verdict = "VALID BREAKOUT SIGNAL"

        print(format_log(symbol, session_label, row, verdict))

        if should_send_signal(symbol, bar_time):
            if plan["valid"]:
                msg = (
                    f"🚀 <b>BUY SIGNAL - {breakout_info['signal_type']}</b>\n"
                    f"<b>{symbol}</b> ({INTERVAL})\n\n"
                    f"Entry: <b>{plan['entry']}</b>\n"
                    f"Breakout over: <b>{breakout_info['breakout_level']:.2f}</b>\n"
                    f"Stop Loss: <b>{plan['stop_loss']}</b>\n"
                    f"Take Profit: <b>{plan['take_profit']}</b>\n"
                    f"R:R: <b>{plan['rr']}</b>\n"
                    f"Suggested shares: <b>{plan['shares']}</b>\n"
                    f"Capital used: <b>{plan['capital_used']}</b>\n\n"
                    f"EMA20: {breakout_info['ema20']:.2f} | EMA50: {breakout_info['ema50']:.2f}\n"
                    f"VWAP: {breakout_info['vwap']:.2f}\n"
                    f"ATR%: {breakout_info['atr_pct']:.2%}\n"
                    f"Volume: {breakout_info['volume']} vs avg {int(breakout_info['vol_sma20']) if breakout_info['vol_sma20'] else 'n/a'}\n\n"
                    f"Condițiile sunt aliniate: breakout + volum + volatilitate."
                )
            else:
                msg = (
                    f"🚨 <b>WATCHLIST SIGNAL - {breakout_info['signal_type']}</b>\n"
                    f"<b>{symbol}</b> ({INTERVAL})\n"
                    f"Breakout valid, dar poziția calculată e prea mică pentru regulile actuale.\n"
                    f"Entry: {plan['entry']} | SL: {plan['stop_loss']} | TP: {plan['take_profit']} | R:R: {plan['rr']}"
                )

            send_telegram(msg)
            last_signal_bar_time[symbol] = bar_time
        return

    if pullback_ok:
        plan = make_trade_plan(pullback_info["entry"], pullback_info["atr"])
        verdict = "VALID PULLBACK CONTINUATION SIGNAL"

        print(format_log(symbol, session_label, row, verdict))

        if should_send_signal(symbol, bar_time):
            if plan["valid"]:
                msg = (
                    f"📈 <b>BUY SIGNAL - {pullback_info['signal_type']}</b>\n"
                    f"<b>{symbol}</b> ({INTERVAL})\n\n"
                    f"Entry: <b>{plan['entry']}</b>\n"
                    f"Recent high: <b>{pullback_info['breakout_level']:.2f}</b>\n"
                    f"Stop Loss: <b>{plan['stop_loss']}</b>\n"
                    f"Take Profit: <b>{plan['take_profit']}</b>\n"
                    f"R:R: <b>{plan['rr']}</b>\n"
                    f"Suggested shares: <b>{plan['shares']}</b>\n"
                    f"Capital used: <b>{plan['capital_used']}</b>\n\n"
                    f"EMA20 retest + reclaim + volum crescut."
                )
            else:
                msg = (
                    f"📌 <b>WATCHLIST SIGNAL - {pullback_info['signal_type']}</b>\n"
                    f"<b>{symbol}</b> ({INTERVAL})\n"
                    f"Set-up bun, dar prea mic pentru sizing-ul actual.\n"
                    f"Entry: {plan['entry']} | SL: {plan['stop_loss']} | TP: {plan['take_profit']} | R:R: {plan['rr']}"
                )

            send_telegram(msg)
            last_signal_bar_time[symbol] = bar_time
        return

    print(format_log(symbol, session_label, row, f"No signal -> {breakout_reason} || {pullback_reason}"))


def main():
    send_telegram("🤖 Bot pornit. Monitorizez breakout + volum + volatilitate pentru AXTI, AAOI, GLW, JNJ.")

    while True:
        try:
            for symbol in SYMBOLS:
                analyze_symbol(symbol)
                time.sleep(2)

        except Exception as e:
            error_msg = f"❌ Bot error: {e}"
            print(error_msg)
            send_telegram(error_msg)

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()