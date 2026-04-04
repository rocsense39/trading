import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

TOKEN = "8581114074:AAFS55UBbtGPQR0NAzBYc3QOpDYFOzqY1A"
CHAT_ID = "8631997789"


SYMBOLS = ["GLW", "AXTI", "JNJ"]
INTERVAL = "5m"

RISK_PCT_SL = 0.01
RR = 2
SLEEP_SECONDS = 300  # 5 minute

EMA_FAST = 20
EMA_SLOW = 50
ATR_PERIOD = 14
ATR_MIN_PCT = 0.0035          # ATR minim = 0.35% din preț
CANDLE_BODY_RATIO_MIN = 0.50
EARLY_WARNING_PCT = 0.0035    # 0.35%
VOLUME_MULTIPLIER = 1.10      # mai permisiv
MAX_BARS_IN_TRADE_IDEA = 12   # 12 x 5m = 60 min

ACCOUNT_SIZE = 860.0          # total cont XTB
RISK_PER_TRADE = 0.007        # 0.7% risc/trade

NY_TZ = ZoneInfo("America/New_York")

# Stare separată pentru fiecare simbol
state = {
    symbol: {
        "last_alert_candle": None,
        "last_signal_date": None,
        "last_early_warning_candle": None,
        "active_setup": None,
    }
    for symbol in SYMBOLS
}


def send_telegram(message: str, retries: int = 3, delay: int = 3) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, data=payload, timeout=20)
            response.raise_for_status()
            print("Telegram message sent successfully.")
            return
        except requests.RequestException as e:
            print(f"Telegram send error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)

    print("Telegram message failed after all retries.")


def now_ny() -> datetime:
    return datetime.now(NY_TZ)


def is_us_session_now() -> bool:
    current = now_ny().time()
    return (
        (current.hour > 9 or (current.hour == 9 and current.minute >= 30))
        and current.hour < 16
    )


def is_optimal_window_now() -> bool:
    current = now_ny().time()
    after_open = (current.hour > 9 or (current.hour == 9 and current.minute >= 30))
    before_cutoff = (current.hour < 11 or (current.hour == 11 and current.minute <= 30))
    return after_open and before_cutoff


def get_data(symbol: str) -> pd.DataFrame:
    df = yf.download(
        tickers=symbol,
        period="3d",
        interval=INTERVAL,
        auto_adjust=False,
        progress=False,
        prepost=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    needed = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"[{symbol}] Missing columns: {missing}")
        return pd.DataFrame()

    df = df[needed].copy().dropna()

    for col in needed:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()
    if df.empty:
        return pd.DataFrame()

    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    cumulative_tpv = (typical_price * df["Volume"]).cumsum()
    cumulative_volume = df["Volume"].cumsum()
    df["VWAP"] = cumulative_tpv / cumulative_volume

    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(ATR_PERIOD).mean()
    df["ATR_PCT"] = df["ATR"] / df["Close"]

    return df


def opening_range(df: pd.DataFrame, bars: int = 6):
    if len(df) < bars:
        return None, None
    opening = df.iloc[:bars]
    return float(opening["High"].max()), float(opening["Low"].min())


def candle_confirmation(last_row: pd.Series, signal: str):
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


def position_size(account_size: float, risk_per_trade: float, entry: float, sl: float):
    risk_amount = account_size * risk_per_trade
    risk_per_share = abs(entry - sl)

    if risk_per_share <= 0:
        return 0, 0.0, risk_amount

    shares = int(risk_amount // risk_per_share)
    capital_needed = shares * entry
    return shares, capital_needed, risk_amount


def build_trade(signal: str, entry: float):
    risk = entry * RISK_PCT_SL

    if signal == "BUY":
        sl = entry - risk
        tp = entry + risk * RR
    else:
        sl = entry + risk
        tp = entry - risk * RR

    return round(entry, 2), round(sl, 2), round(tp, 2)


def update_active_setup(symbol: str, df: pd.DataFrame) -> None:
    active_setup = state[symbol]["active_setup"]

    if active_setup is None or df.empty:
        return

    if len(df) < 2:
        return

    last_ts = df.index[-1]
    if active_setup["last_checked_candle"] == last_ts:
        return

    active_setup["last_checked_candle"] = last_ts
    active_setup["bars_elapsed"] += 1

    last_close = float(df["Close"].iloc[-1])
    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])
    vwap = float(df["VWAP"].iloc[-1])

    signal = active_setup["signal"]

    if signal == "BUY":
        still_valid = last_close > ema20 and ema20 > ema50 and last_close > vwap
    else:
        still_valid = last_close < ema20 and ema20 < ema50 and last_close < vwap

    if not still_valid:
        send_telegram(
            f"⚠️ {symbol} SETUP INVALIDAT\n\n"
            f"Setup: {signal}\n"
            f"Motiv: trend/VWAP nu mai confirmă\n"
            f"Close: {last_close:.2f}\n"
            f"EMA20: {ema20:.2f}\n"
            f"EMA50: {ema50:.2f}\n"
            f"VWAP: {vwap:.2f}\n\n"
            f"Acțiune: NU executa acest setup."
        )
        state[symbol]["active_setup"] = None
        return

    if active_setup["bars_elapsed"] >= MAX_BARS_IN_TRADE_IDEA:
        send_telegram(
            f"⌛ {symbol} SETUP EXPIRAT\n\n"
            f"Setup: {signal}\n"
            f"Au trecut {MAX_BARS_IN_TRADE_IDEA} lumânări fără follow-through suficient.\n"
            f"Close: {last_close:.2f}\n"
            f"EMA20: {ema20:.2f}\n"
            f"EMA50: {ema50:.2f}\n"
            f"VWAP: {vwap:.2f}\n\n"
            f"Acțiune: ignoră setup-ul vechi și așteaptă unul nou."
        )
        state[symbol]["active_setup"] = None


def check_signal(symbol: str, df: pd.DataFrame):
    if df.empty:
        return None, "no data", None

    if len(df) < max(EMA_SLOW + 2, ATR_PERIOD + 2, 20):
        return None, "not enough candles", None

    if not is_us_session_now():
        return None, "outside US session", None

    if not is_optimal_window_now():
        return None, "outside optimal trading window", None

    today_ny = now_ny().date()

    if state[symbol]["last_signal_date"] == today_ny:
        return None, "already sent signal today", None

    or_high, or_low = opening_range(df, bars=6)
    if or_high is None or or_low is None:
        return None, "opening range unavailable", None

    candle_time = df.index[-1]
    if (
        state[symbol]["last_alert_candle"] is not None
        and candle_time == state[symbol]["last_alert_candle"]
    ):
        return None, "same candle already checked", None

    last_close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    last_volume = float(df["Volume"].iloc[-1])
    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])
    vwap = float(df["VWAP"].iloc[-1])
    atr = float(df["ATR"].iloc[-1])
    atr_pct = float(df["ATR_PCT"].iloc[-1])

    if pd.isna(atr) or pd.isna(atr_pct):
        return None, "ATR unavailable", None

    volume_window = df["Volume"].iloc[-10:-1]
    if len(volume_window) < 5:
        return None, "not enough volume history", None

    avg_volume = float(volume_window.mean())

    trend_up = last_close > ema20 and ema20 > ema50 and last_close > vwap
    trend_down = last_close < ema20 and ema20 < ema50 and last_close < vwap

    buy_breakout = prev_close <= or_high and last_close > or_high
    sell_breakout = prev_close >= or_low and last_close < or_low
    volume_ok = last_volume > avg_volume * VOLUME_MULTIPLIER
    atr_ok = atr_pct >= ATR_MIN_PCT

    buy_candle_ok, candle_open, candle_close, buy_body_ratio = candle_confirmation(df.iloc[-1], "BUY")
    sell_candle_ok, _, _, sell_body_ratio = candle_confirmation(df.iloc[-1], "SELL")

    buy_valid = buy_breakout and volume_ok and trend_up and buy_candle_ok and atr_ok
    sell_valid = sell_breakout and volume_ok and trend_down and sell_candle_ok and atr_ok

    diagnostics = {
        "or_high": or_high,
        "or_low": or_low,
        "buy_valid": buy_valid,
        "sell_valid": sell_valid,
        "distance_to_buy_breakout": max(or_high - last_close, 0.0),
        "distance_to_sell_breakout": max(last_close - or_low, 0.0),
        "vwap": vwap,
        "trend_up": trend_up,
        "trend_down": trend_down,
        "volume_ok": volume_ok,
        "buy_breakout": buy_breakout,
        "sell_breakout": sell_breakout,
        "buy_candle_ok": buy_candle_ok,
        "sell_candle_ok": sell_candle_ok,
        "atr": atr,
        "atr_pct": atr_pct,
        "atr_ok": atr_ok,
    }

    if buy_valid:
        state[symbol]["last_alert_candle"] = candle_time
        state[symbol]["last_signal_date"] = today_ny
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
                vwap,
                candle_open,
                candle_close,
                buy_body_ratio,
                atr,
                atr_pct,
            ),
            None,
            diagnostics,
        )

    if sell_valid:
        state[symbol]["last_alert_candle"] = candle_time
        state[symbol]["last_signal_date"] = today_ny
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
                vwap,
                candle_open,
                candle_close,
                sell_body_ratio,
                atr,
                atr_pct,
            ),
            None,
            diagnostics,
        )

    reasons = []
    if not buy_breakout and not sell_breakout:
        reasons.append("no breakout")
    if not volume_ok:
        reasons.append("volume too low")
    if not atr_ok:
        reasons.append(f"ATR too low ({atr_pct:.4f} < {ATR_MIN_PCT:.4f})")
    if not trend_up and not trend_down:
        reasons.append("trend/VWAP filter failed")
    if buy_breakout and not trend_up:
        reasons.append("BUY blocked by trend/VWAP filter")
    if sell_breakout and not trend_down:
        reasons.append("SELL blocked by trend/VWAP filter")
    if buy_breakout and trend_up and not buy_candle_ok:
        reasons.append("candle confirmation failed for BUY")
    if sell_breakout and trend_down and not sell_candle_ok:
        reasons.append("candle confirmation failed for SELL")

    return None, " | ".join(reasons) if reasons else "conditions not met", diagnostics


def check_early_warning(symbol: str, df: pd.DataFrame):
    if df.empty or len(df) < max(EMA_SLOW + 2, ATR_PERIOD + 2, 20):
        return None

    if not is_us_session_now():
        return None

    if not is_optimal_window_now():
        return None

    or_high, or_low = opening_range(df, bars=6)
    if or_high is None or or_low is None:
        return None

    candle_time = df.index[-1]
    if (
        state[symbol]["last_early_warning_candle"] is not None
        and candle_time == state[symbol]["last_early_warning_candle"]
    ):
        return None

    last_close = float(df["Close"].iloc[-1])
    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])
    vwap = float(df["VWAP"].iloc[-1])
    atr = float(df["ATR"].iloc[-1])
    atr_pct = float(df["ATR_PCT"].iloc[-1])

    if pd.isna(atr) or pd.isna(atr_pct):
        return None

    dist_buy = max(or_high - last_close, 0.0)
    dist_sell = max(last_close - or_low, 0.0)

    near_buy = last_close < or_high and (dist_buy / last_close) <= EARLY_WARNING_PCT
    near_sell = last_close > or_low and (dist_sell / last_close) <= EARLY_WARNING_PCT

    trend_up = last_close > ema20 and ema20 > ema50 and last_close > vwap
    trend_down = last_close < ema20 and ema20 < ema50 and last_close < vwap
    atr_ok = atr_pct >= ATR_MIN_PCT

    if near_buy and trend_up and atr_ok:
        state[symbol]["last_early_warning_candle"] = candle_time
        return (
            f"🟡 EARLY WARNING {symbol}\n\n"
            f"Posibil BUY în curând.\n"
            f"Close: {last_close:.2f}\n"
            f"OR High: {or_high:.2f}\n"
            f"Distanță până la breakout BUY: {dist_buy:.2f}\n"
            f"EMA20: {ema20:.2f}\n"
            f"EMA50: {ema50:.2f}\n"
            f"VWAP: {vwap:.2f}\n"
            f"ATR: {atr:.2f}\n"
            f"ATR%: {atr_pct:.4f}\n\n"
            f"Acțiune: pregătește XTB, dar NU intra încă."
        )

    if near_sell and trend_down and atr_ok:
        state[symbol]["last_early_warning_candle"] = candle_time
        return (
            f"🟡 EARLY WARNING {symbol}\n\n"
            f"Posibil SELL în curând.\n"
            f"Close: {last_close:.2f}\n"
            f"OR Low: {or_low:.2f}\n"
            f"Distanță până la breakout SELL: {dist_sell:.2f}\n"
            f"EMA20: {ema20:.2f}\n"
            f"EMA50: {ema50:.2f}\n"
            f"VWAP: {vwap:.2f}\n"
            f"ATR: {atr:.2f}\n"
            f"ATR%: {atr_pct:.4f}\n\n"
            f"Acțiune: pregătește XTB, dar NU intra încă."
        )

    return None


def action_message(
    symbol: str,
    signal: str,
    entry: float,
    sl: float,
    tp: float,
    ema20: float,
    ema50: float,
    vwap: float,
    or_high: float,
    or_low: float,
    last_volume: float,
    avg_volume: float,
    candle_time,
    atr: float,
    atr_pct: float,
) -> str:
    shares, capital_needed, risk_amount = position_size(ACCOUNT_SIZE, RISK_PER_TRADE, entry, sl)

    if signal == "BUY":
        action = "✅ ACȚIUNE: CUMPĂRĂ ACUM"
        extra = "Plasează ordin BUY în XTB."
    else:
        action = "✅ ACȚIUNE: VINDE / SHORT ACUM"
        extra = "Plasează SELL doar dacă instrumentul și contul permit short."

    if shares <= 0:
        size_text = (
            "⚠️ CAPITAL INSUFICIENT PENTRU EXECUȚIE\n\n"
            f"Risc/trade: {risk_amount:.2f}\n"
            f"Preț acțiune: {entry}\n\n"
            "Sugestii:\n"
            "- redu RISK_PER_TRADE\n"
            "- sau așteaptă alt setup\n"
            "- sau crește capitalul\n\n"
            "❌ NU EXECUTA TRADE-UL"
        )
    else:
        size_text = (
            f"Poziție recomandată: {shares} acțiuni\n"
            f"Capital estimat necesar: {capital_needed:.2f}\n"
            f"Risc/trade: {risk_amount:.2f}"
        )

    return (
        f"🚨 {symbol} SEMNAL EXECUTABIL\n\n"
        f"{action}\n"
        f"{extra}\n\n"
        f"Instrument: {symbol}\n"
        f"Tip semnal: {signal}\n"
        f"Entry: {entry}\n"
        f"Stop Loss: {sl}\n"
        f"Take Profit: {tp}\n\n"
        f"{size_text}\n\n"
        f"EMA20: {ema20:.2f}\n"
        f"EMA50: {ema50:.2f}\n"
        f"VWAP: {vwap:.2f}\n"
        f"ATR: {atr:.2f}\n"
        f"ATR%: {atr_pct:.4f}\n"
        f"OR High: {or_high:.2f}\n"
        f"OR Low: {or_low:.2f}\n"
        f"Volum ultim: {last_volume:.2f}\n"
        f"Volum mediu: {avg_volume:.2f}\n"
        f"Timp semnal: {candle_time}\n\n"
        f"Instrucțiune: execută doar dacă poți plasa imediat ordinul."
    )


def run_bot():
    send_telegram(
        "🤖 Bot AGRESIV+DEFENSIV pornit | Simboluri: GLW, AXTI, JNJ | "
        "Fereastră 09:30-11:30 NY | EMA20/EMA50 + VWAP + ATR | "
        "volum adaptiv | candle confirmation strict | early warning activ"
    )

    while True:
        try:
            for symbol in SYMBOLS:
                try:
                    df = get_data(symbol)

                    if df.empty:
                        print(f"[{symbol}] No data received.")
                        continue

                    update_active_setup(symbol, df)

                    early_warning = check_early_warning(symbol, df)
                    if early_warning:
                        send_telegram(early_warning)
                        print(f"{datetime.now()} [{symbol}] EARLY WARNING SENT")

                    result, reason, diagnostics = check_signal(symbol, df)

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
                            vwap,
                            candle_open,
                            candle_close,
                            body_ratio,
                            atr,
                            atr_pct,
                        ) = result

                        entry, sl, tp = build_trade(signal, price)

                        msg = action_message(
                            symbol=symbol,
                            signal=signal,
                            entry=entry,
                            sl=sl,
                            tp=tp,
                            ema20=ema20,
                            ema50=ema50,
                            vwap=vwap,
                            or_high=or_high,
                            or_low=or_low,
                            last_volume=last_volume,
                            avg_volume=avg_volume,
                            candle_time=candle_time,
                            atr=atr,
                            atr_pct=atr_pct,
                        )
                        send_telegram(msg)
                        print(f"{datetime.now()} [{symbol}] SIGNAL SENT -> {signal} at {entry}")

                        state[symbol]["active_setup"] = {
                            "signal": signal,
                            "entry": entry,
                            "sl": sl,
                            "tp": tp,
                            "start_candle": candle_time,
                            "last_checked_candle": candle_time,
                            "bars_elapsed": 0,
                        }

                    else:
                        last_close = float(df["Close"].iloc[-1])
                        ema20 = float(df["EMA20"].iloc[-1])
                        ema50 = float(df["EMA50"].iloc[-1])
                        vwap = float(df["VWAP"].iloc[-1])
                        atr = float(df["ATR"].iloc[-1]) if not pd.isna(df["ATR"].iloc[-1]) else 0.0
                        atr_pct = float(df["ATR_PCT"].iloc[-1]) if not pd.isna(df["ATR_PCT"].iloc[-1]) else 0.0

                        print(
                            f"{datetime.now()} [{symbol}] | Close: {last_close:.2f} | "
                            f"EMA20: {ema20:.2f} | EMA50: {ema50:.2f} | VWAP: {vwap:.2f} | "
                            f"ATR: {atr:.2f} | ATR%: {atr_pct:.4f} | "
                            f"No signal -> {reason}"
                        )

                except Exception as symbol_error:
                    error_msg = f"⚠️ Eroare bot {symbol}: {type(symbol_error).__name__}: {symbol_error}"
                    print(error_msg)
                    send_telegram(error_msg)

        except Exception as e:
            error_msg = f"⚠️ Eroare bot multi-stock: {type(e).__name__}: {e}"
            print(error_msg)
            send_telegram(error_msg)

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    run_bot()