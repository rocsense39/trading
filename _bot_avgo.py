import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

TOKEN = "8581114074:AAFS55UBbtGPQR0NAzBYc3QOpDYFQzqY1A"
CHAT_ID = "8631997789"

SYMBOL = "AVGO"
INTERVAL = "5m"
RISK_PCT = 0.01
RR = 2
SLEEP_SECONDS = 300  # 5 minute

EMA_FAST = 20
EMA_SLOW = 50
CANDLE_BODY_RATIO_MIN = 0.40  # minim 40% din range-ul lumânării

NY_TZ = ZoneInfo("America/New_York")

last_alert_candle = None
last_signal_date = None


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        response = requests.post(url, data=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Telegram send error: {e}")


def get_data() -> pd.DataFrame:
    df = yf.download(
        tickers=SYMBOL,
        period="1d",
        interval=INTERVAL,
        auto_adjust=False,
        progress=False,
        prepost=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    needed = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"Missing columns: {missing}")
        return pd.DataFrame()

    df = df[needed].copy()
    df = df.dropna()

    for col in needed:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()

    if df.empty:
        return pd.DataFrame()

    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    return df


def is_us_session_now() -> bool:
    now_ny = datetime.now(NY_TZ)
    current_time = now_ny.time()

    return (
        (current_time.hour > 9 or (current_time.hour == 9 and current_time.minute >= 30))
        and current_time.hour < 16
    )


def opening_range(df: pd.DataFrame, bars: int = 6) -> tuple[float, float] | tuple[None, None]:
    if len(df) < bars:
        return None, None

    opening = df.iloc[:bars]
    or_high = float(opening["High"].max())
    or_low = float(opening["Low"].min())
    return or_high, or_low


def candle_confirmation(last_row: pd.Series, signal: str) -> tuple[bool, float, float, float]:
    candle_open = float(last_row["Open"])
    candle_high = float(last_row["High"])
    candle_low = float(last_row["Low"])
    candle_close = float(last_row["Close"])

    candle_range = candle_high - candle_low
    candle_body = abs(candle_close - candle_open)

    if candle_range <= 0:
        return False, candle_open, candle_close, 0.0

    body_ratio = candle_body / candle_range

    bullish_confirm = (
        signal == "BUY"
        and candle_close > candle_open
        and body_ratio >= CANDLE_BODY_RATIO_MIN
    )

    bearish_confirm = (
        signal == "SELL"
        and candle_close < candle_open
        and body_ratio >= CANDLE_BODY_RATIO_MIN
    )

    return bullish_confirm or bearish_confirm, candle_open, candle_close, body_ratio


def check_signal(df: pd.DataFrame):
    global last_alert_candle, last_signal_date

    if df.empty:
        return None, "no data", None

    if len(df) < max(20, EMA_SLOW + 2):
        return None, "not enough candles", None

    if not is_us_session_now():
        return None, "outside US session", None

    now_ny = datetime.now(NY_TZ).date()

    if last_signal_date == now_ny:
        return None, "already sent signal today", None

    or_high, or_low = opening_range(df, bars=6)
    if or_high is None or or_low is None:
        return None, "opening range unavailable", None

    candle_time = df.index[-1]

    if last_alert_candle is not None and candle_time == last_alert_candle:
        return None, "same candle already checked", None

    last_close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    last_volume = float(df["Volume"].iloc[-1])

    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])

    volume_window = df["Volume"].iloc[-10:-1]
    if len(volume_window) < 5:
        return None, "not enough volume history", None

    avg_volume = float(volume_window.mean())

    trend_up = last_close > ema20 and ema20 > ema50
    trend_down = last_close < ema20 and ema20 < ema50

    buy_breakout = prev_close <= or_high and last_close > or_high
    sell_breakout = prev_close >= or_low and last_close < or_low

    volume_ok = last_volume > avg_volume

    buy_candle_ok, candle_open, candle_close, buy_body_ratio = candle_confirmation(df.iloc[-1], "BUY")
    sell_candle_ok, _, _, sell_body_ratio = candle_confirmation(df.iloc[-1], "SELL")

    buy_valid = buy_breakout and volume_ok and trend_up and buy_candle_ok
    sell_valid = sell_breakout and volume_ok and trend_down and sell_candle_ok

    diagnostics = {
        "or_high": or_high,
        "or_low": or_low,
        "buy_valid": buy_valid,
        "sell_valid": sell_valid,
        "distance_to_buy_breakout": max(or_high - last_close, 0.0),
        "distance_to_sell_breakout": max(last_close - or_low, 0.0),
    }

    if buy_valid:
        last_alert_candle = candle_time
        last_signal_date = now_ny
        return (
            (
                "BUY",
                last_close,
                candle_time,
                or_high,
                or_low,
                last_volume,
                avg_volume,
                ema20,
                ema50,
                candle_open,
                candle_close,
                buy_body_ratio,
            ),
            None,
            diagnostics,
        )

    if sell_valid:
        last_alert_candle = candle_time
        last_signal_date = now_ny
        return (
            (
                "SELL",
                last_close,
                candle_time,
                or_high,
                or_low,
                last_volume,
                avg_volume,
                ema20,
                ema50,
                candle_open,
                candle_close,
                sell_body_ratio,
            ),
            None,
            diagnostics,
        )

    reasons = []

    if not buy_breakout and not sell_breakout:
        reasons.append("no breakout")
    if not volume_ok:
        reasons.append("volume too low")
    if not trend_up and not trend_down:
        reasons.append("trend filter failed")
    if buy_breakout and trend_up and not buy_candle_ok:
        reasons.append("candle confirmation failed for BUY")
    if sell_breakout and trend_down and not sell_candle_ok:
        reasons.append("candle confirmation failed for SELL")
    if buy_breakout and not trend_up:
        reasons.append("BUY blocked by trend filter")
    if sell_breakout and not trend_down:
        reasons.append("SELL blocked by trend filter")

    return None, " | ".join(reasons) if reasons else "conditions not met", diagnostics


def build_trade(signal: str, entry: float) -> tuple[float, float, float]:
    risk = entry * RISK_PCT

    if signal == "BUY":
        sl = entry - risk
        tp = entry + risk * RR
    else:
        sl = entry + risk
        tp = entry - risk * RR

    return round(entry, 2), round(sl, 2), round(tp, 2)


def action_message(signal: str, entry: float, sl: float, tp: float,
                   ema20: float, ema50: float, or_high: float, or_low: float,
                   last_volume: float, avg_volume: float, candle_time) -> str:
    if signal == "BUY":
        action = "✅ ACȚIUNE: CUMPĂRĂ ACUM"
        extra = "Setează ordin BUY în XTB."
    else:
        action = "✅ ACȚIUNE: VINDE / SHORT ACUM"
        extra = "Setează ordin SELL în XTB doar dacă folosești short selling."

    return (
        f"🚨 AVGO SEMNAL EXECUTABIL\n\n"
        f"{action}\n"
        f"{extra}\n\n"
        f"Instrument: {SYMBOL}\n"
        f"Tip semnal: {signal}\n"
        f"Entry: {entry}\n"
        f"Stop Loss: {sl}\n"
        f"Take Profit: {tp}\n\n"
        f"EMA20: {round(ema20, 2)}\n"
        f"EMA50: {round(ema50, 2)}\n"
        f"OR High: {round(or_high, 2)}\n"
        f"OR Low: {round(or_low, 2)}\n"
        f"Volum ultim: {round(last_volume, 2)}\n"
        f"Volum mediu: {round(avg_volume, 2)}\n"
        f"Timp semnal: {candle_time}\n\n"
        f"Instrucțiune: Execută doar dacă piața este deschisă și ordinul poate fi plasat imediat."
    )


def wait_message(reason: str, diagnostics: dict | None, df: pd.DataFrame) -> str:
    last_close = float(df["Close"].iloc[-1])
    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])

    or_high = diagnostics["or_high"] if diagnostics else None
    or_low = diagnostics["or_low"] if diagnostics else None
    buy_valid = diagnostics["buy_valid"] if diagnostics else False
    sell_valid = diagnostics["sell_valid"] if diagnostics else False
    distance_to_buy = diagnostics["distance_to_buy_breakout"] if diagnostics else None
    distance_to_sell = diagnostics["distance_to_sell_breakout"] if diagnostics else None

    return (
        f"⏳ ACȚIUNE: AȘTEAPTĂ\n\n"
        f"Instrument: {SYMBOL}\n"
        f"Close: {last_close:.2f}\n"
        f"EMA20: {ema20:.2f}\n"
        f"EMA50: {ema50:.2f}\n"
        f"OR High: {or_high:.2f}\n"
        f"OR Low: {or_low:.2f}\n"
        f"BUY valid: {buy_valid}\n"
        f"SELL valid: {sell_valid}\n"
        f"Distanță până la BUY breakout: {distance_to_buy:.2f}\n"
        f"Distanță până la SELL breakout: {distance_to_sell:.2f}\n\n"
        f"Motiv: {reason}\n\n"
        f"Instrucțiune: Nu deschide poziție acum."
    )


def run_bot() -> None:
    send_telegram(
        "🤖 Bot AVGO pornit | Sesiune SUA | Max 1 semnal/zi | EMA20/EMA50 | Candle confirmation activ"
    )

    while True:
        try:
            df = get_data()

            if df.empty:
                print("No data received.")
                time.sleep(SLEEP_SECONDS)
                continue

            result, reason, diagnostics = check_signal(df)

            if result:
                (
                    signal,
                    price,
                    candle_time,
                    or_high,
                    or_low,
                    last_volume,
                    avg_volume,
                    ema20,
                    ema50,
                    candle_open,
                    candle_close,
                    body_ratio,
                ) = result

                entry, sl, tp = build_trade(signal, price)

                msg = action_message(
                    signal=signal,
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    ema20=ema20,
                    ema50=ema50,
                    or_high=or_high,
                    or_low=or_low,
                    last_volume=last_volume,
                    avg_volume=avg_volume,
                    candle_time=candle_time,
                )
                send_telegram(msg)
                print(f"{datetime.now()}: SIGNAL SENT -> {signal} at {entry}")

            else:
                now_ny = datetime.now(NY_TZ)
                last_close = float(df["Close"].iloc[-1])
                ema20 = float(df["EMA20"].iloc[-1])
                ema50 = float(df["EMA50"].iloc[-1])

                print(
                    f"{datetime.now()} | NY: {now_ny.strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"Close: {last_close:.2f} | EMA20: {ema20:.2f} | EMA50: {ema50:.2f} | "
                    f"No signal -> {reason}"
                )

                # Activează linia de mai jos DOAR dacă vrei mesaj Telegram și când trebuie să aștepți.
                # Atenție: trimite mesaje dese.
                # send_telegram(wait_message(reason, diagnostics, df))

        except Exception as e:
            error_msg = f"⚠️ Eroare bot AVGO: {type(e).__name__}: {e}"
            print(error_msg)
            send_telegram(error_msg)

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    run_bot()
