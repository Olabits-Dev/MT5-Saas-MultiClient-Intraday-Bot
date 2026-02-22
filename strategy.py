# =========================
# MULTI-SESSION STRATEGY (PRO)
# ASIA: Range Bounce
# LONDON: Trend Continuation (EMA state + pullback)
# NEWYORK: Reversal (strict PA) + SAFE LOOSENING (Option 1)
#
# ✅ UPDATED:
# - Signal timeframe can stay H1 (your main.py controls this)
# - Bias can be Dual Bias:
#    Primary: H4
#    Confirm: H1
#    Trade allowed only if H4 bias == H1 bias (both stable)
# =========================

import MetaTrader5 as mt5
import pandas as pd
from session_filter import get_current_session

DEBUG_ASIA = False

FAST_EMA = 12
SLOW_EMA = 40

VOL_LOOKBACK = 20
VOL_MULTIPLIER = 0.60

SR_THRESH = {
    "EURUSD": 0.0015,
    "USDJPY": 0.0015,
    "GBPJPY": 0.0018,
    "XAUUSD": 0.0025,
    "BTCUSD": 0.0060,
}

TF_NAMES = {
    mt5.TIMEFRAME_M5: "M5",
    mt5.TIMEFRAME_M15: "M15",
    mt5.TIMEFRAME_M30: "M30",
    mt5.TIMEFRAME_H1: "H1",
    mt5.TIMEFRAME_H4: "H4",
}


def get_data(symbol, timeframe, bars=300):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None:
        return None
    return pd.DataFrame(rates)


# ------------------- PRICE ACTION HELPERS -------------------
def is_bullish_pinbar(df):
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"]) or 1e-9
    lower_wick = min(last["open"], last["close"]) - last["low"]
    return lower_wick > 2 * body and last["close"] > last["open"]


def is_bearish_pinbar(df):
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"]) or 1e-9
    upper_wick = last["high"] - max(last["open"], last["close"])
    return upper_wick > 2 * body and last["close"] < last["open"]


def is_bullish_engulfing(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return (
        last["close"] > last["open"]
        and prev["close"] < prev["open"]
        and last["close"] > prev["open"]
        and last["open"] < prev["close"]
    )


def is_bearish_engulfing(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return (
        last["close"] < last["open"]
        and prev["close"] > prev["open"]
        and last["open"] > prev["close"]
        and last["close"] < prev["open"]
    )


def has_bullish_pa(df):
    return is_bullish_engulfing(df) or is_bullish_pinbar(df)


def has_bearish_pa(df):
    return is_bearish_engulfing(df) or is_bearish_pinbar(df)


def is_simple_rejection(df):
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"]) or 1e-9
    upper = last["high"] - max(last["open"], last["close"])
    lower = min(last["open"], last["close"]) - last["low"]
    return upper > body or lower > body


# ------------------- SUPPORT & RESISTANCE -------------------
def get_support_resistance(df, window=50):
    recent = df.tail(window)
    support = recent["low"].min()
    resistance = recent["high"].max()
    return support, resistance


def near_support(symbol, price, support):
    thr = SR_THRESH.get(symbol, 0.0015)
    return abs(price - support) / price < thr


def near_resistance(symbol, price, resistance):
    thr = SR_THRESH.get(symbol, 0.0015)
    return abs(price - resistance) / price < thr


# ------------------- VOLUME FILTER -------------------
def sufficient_volume(df, symbol=None, session=None):
    v = df["tick_volume"]
    if len(v) < VOL_LOOKBACK + 2:
        return True

    avg = v.tail(VOL_LOOKBACK).mean()
    cur = v.iloc[-1]
    mult = VOL_MULTIPLIER

    if symbol == "XAUUSD":
        mult = min(mult, 0.45)

    if session == "ASIAN":
        mult = min(mult, 0.30)
        if symbol == "XAUUSD":
            mult = min(mult, 0.25)

    return cur >= mult * avg


# =========================
# ASIA: RANGE BOUNCE
# =========================
def asian_range_bounce(symbol, df):
    vol_ok = sufficient_volume(df, symbol, session="ASIAN")
    if not vol_ok:
        if DEBUG_ASIA:
            cur_v = df["tick_volume"].iloc[-1]
            avg_v = df["tick_volume"].tail(VOL_LOOKBACK).mean()
            print(f"🧪 {symbol} ASIA blocked: low volume | cur={cur_v} avg={avg_v:.2f}")
        return None

    support, resistance = get_support_resistance(df, window=60)
    price = df["close"].iloc[-1]

    near_sup = near_support(symbol, price, support)
    near_res = near_resistance(symbol, price, resistance)

    bull_ok = has_bullish_pa(df) or is_simple_rejection(df)
    bear_ok = has_bearish_pa(df) or is_simple_rejection(df)

    if DEBUG_ASIA:
        print(
            f"🧪 {symbol} ASIA debug | price={price} support={support} resistance={resistance} | "
            f"nearS={near_sup} nearR={near_res} | bullOK={bull_ok} bearOK={bear_ok} | volOK={vol_ok}"
        )

    if near_sup and bull_ok:
        return "BUY"
    if near_res and bear_ok:
        return "SELL"
    return None


# =========================
# LONDON: TREND CONTINUATION
# =========================
def london_trend(symbol, df):
    if not sufficient_volume(df, symbol, session="LONDON"):
        return None

    df["ema_fast"] = df["close"].ewm(span=FAST_EMA).mean()
    df["ema_slow"] = df["close"].ewm(span=SLOW_EMA).mean()

    price = df["close"].iloc[-1]
    ema_fast = df["ema_fast"].iloc[-1]
    ema_slow = df["ema_slow"].iloc[-1]

    support, resistance = get_support_resistance(df, window=50)

    tol = SR_THRESH.get(symbol, 0.0015) * price
    near_ema_slow = abs(price - ema_slow) <= tol

    if ema_fast > ema_slow and near_ema_slow:
        if not near_resistance(symbol, price, resistance):
            return "BUY"

    if ema_fast < ema_slow and near_ema_slow:
        if not near_support(symbol, price, support):
            return "SELL"

    return None


# =========================
# NEW YORK: REVERSAL (Option 1 safe loosening)
# =========================
def newyork_reversal(symbol, df):
    if not sufficient_volume(df, symbol, session="NEWYORK"):
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last["close"]

    support, resistance = get_support_resistance(df, window=50)

    signal = None

    if prev["close"] < prev["open"] and last["close"] > last["open"]:
        if not near_resistance(symbol, price, resistance):
            signal = "BUY"
    elif prev["close"] > prev["open"] and last["close"] < last["open"]:
        if not near_support(symbol, price, support):
            signal = "SELL"

    if signal is None:
        return None

    if signal == "BUY" and not (has_bullish_pa(df) or is_simple_rejection(df)):
        return None
    if signal == "SELL" and not (has_bearish_pa(df) or is_simple_rejection(df)):
        return None

    return signal


# ------------------- MASTER SIGNAL -------------------
def get_signal(symbol, timeframe=mt5.TIMEFRAME_M30):
    session = get_current_session()
    if session is None:
        return None

    df = get_data(symbol, timeframe=timeframe, bars=300)
    if df is None or len(df) < 120:
        return None

    tf_name = TF_NAMES.get(timeframe, str(timeframe))

    if session == "ASIAN":
        print(f"{symbol} -> Asian range bounce (PA + S/R + vol) [{tf_name}]")
        return asian_range_bounce(symbol, df)

    if session == "LONDON":
        print(f"{symbol} -> London trend (EMA + S/R + vol) [{tf_name}]")
        return london_trend(symbol, df)

    if session == "NEWYORK":
        print(f"{symbol} -> NY reversal (strict PA + rejection + S/R + vol) [{tf_name}]")
        return newyork_reversal(symbol, df)

    return None


# ------------------- BIAS (single TF, stable bars) -------------------
def get_bias(symbol, timeframe=mt5.TIMEFRAME_H1, stable_bars: int = 2):
    """
    Returns: "BULL", "BEAR", or None

    ✅ Stability rule:
    - Bias must be the SAME for the last `stable_bars` CLOSED candles.
    """
    df = get_data(symbol, timeframe=timeframe, bars=300)
    if df is None or len(df) < 120:
        return None

    df["ema_fast"] = df["close"].ewm(span=FAST_EMA).mean()
    df["ema_slow"] = df["close"].ewm(span=SLOW_EMA).mean()

    needed = stable_bars
    if len(df) < (needed + 5):
        return None

    biases = []
    for i in range(2, 2 + needed):  # closed candles only
        fast = df["ema_fast"].iloc[-i]
        slow = df["ema_slow"].iloc[-i]
        if fast > slow:
            biases.append("BULL")
        elif fast < slow:
            biases.append("BEAR")
        else:
            biases.append(None)

    if any(b is None for b in biases):
        return None
    if len(set(biases)) != 1:
        return None

    return biases[0]


# ------------------- DUAL BIAS (H4 + H1 must agree) -------------------
def get_dual_bias(
    symbol,
    primary_tf=mt5.TIMEFRAME_H4,
    confirm_tf=mt5.TIMEFRAME_H1,
    primary_stable: int = 2,
    confirm_stable: int = 2,
):
    """
    Returns:
      (final_bias, primary_bias, confirm_bias)

    final_bias is:
      - "BULL" or "BEAR" if BOTH timeframes agree and both are stable
      - None otherwise

    Example:
      final, h4, h1 = get_dual_bias(symbol)
    """
    primary_bias = get_bias(symbol, timeframe=primary_tf, stable_bars=primary_stable)
    confirm_bias = get_bias(symbol, timeframe=confirm_tf, stable_bars=confirm_stable)

    if primary_bias is None or confirm_bias is None:
        return None, primary_bias, confirm_bias

    if primary_bias != confirm_bias:
        return None, primary_bias, confirm_bias

    return primary_bias, primary_bias, confirm_bias