import time
import MetaTrader5 as mt5
from telegram import send_telegram


# ----------------------------
# Robust symbol enable/select
# ----------------------------
def ensure_symbol(symbol: str, tries: int = 8, delay: float = 0.25) -> bool:
    symbol = str(symbol).strip()
    for _ in range(tries):
        info = mt5.symbol_info(symbol)
        if info is None:
            time.sleep(delay)
            continue
        if mt5.symbol_select(symbol, True):
            return True
        time.sleep(delay)
    return False


# ----------------------------
# Tick helpers (FIX: avoid 0.0 prices)
# ----------------------------
def _get_valid_tick(symbol: str, tries: int = 12, delay: float = 0.2):
    """
    Returns a tick where bid/ask are > 0.
    Prevents price=0.0 causing invalid SL/TP.
    """
    for _ in range(tries):
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            bid = float(getattr(tick, "bid", 0.0) or 0.0)
            ask = float(getattr(tick, "ask", 0.0) or 0.0)
            if bid > 0 and ask > 0:
                return tick
        time.sleep(delay)
    return None


# ----------------------------
# Stop distance helpers
# ----------------------------
def _min_stop_distance(info) -> float:
    stops_points = int(getattr(info, "trade_stops_level", 0) or 0)
    freeze_points = int(getattr(info, "trade_freeze_level", 0) or 0)
    min_points = max(stops_points, freeze_points)
    return float(min_points) * float(info.point)


def _ensure_min_stops(price, sl, tp, signal, info, buffer_points=10):
    signal = str(signal).upper().strip()
    point = float(info.point)
    digits = int(info.digits)

    min_dist = _min_stop_distance(info) + (buffer_points * point)
    if min_dist <= 0:
        min_dist = buffer_points * point

    if signal == "BUY":
        if (price - sl) < min_dist:
            sl = price - min_dist
        if (tp - price) < min_dist:
            tp = price + min_dist
    else:  # SELL
        if (sl - price) < min_dist:
            sl = price + min_dist
        if (price - tp) < min_dist:
            tp = price - min_dist

    sl = round(float(sl), digits)
    tp = round(float(tp), digits)
    return sl, tp, float(min_dist)


def _validate_sl_tp(price: float, sl: float, tp: float, signal: str, info):
    """
    Ensures SL/TP are on correct sides:
    BUY  -> SL < price < TP
    SELL -> TP < price < SL
    """
    digits = int(info.digits)
    signal = str(signal).upper().strip()

    price = round(float(price), digits)
    sl = round(float(sl), digits)
    tp = round(float(tp), digits)

    if signal == "BUY":
        if not (sl < price < tp):
            return False, price, sl, tp
    else:
        if not (tp < price < sl):
            return False, price, sl, tp

    return True, price, sl, tp


# ----------------------------
# Volume normalization (optional but robust)
# ----------------------------
def _normalize_volume(volume: float, info) -> float:
    """
    Clamps volume to broker min/max and aligns to volume_step.
    """
    v = float(volume)
    vmin = float(getattr(info, "volume_min", 0.01) or 0.01)
    vmax = float(getattr(info, "volume_max", v) or v)
    step = float(getattr(info, "volume_step", 0.01) or 0.01)

    # clamp
    v = max(vmin, min(v, vmax))

    # align to step
    if step > 0:
        steps = round(v / step)
        v = steps * step

    # round to 2dp is usually safe for lots
    return float(round(v, 2))


# ----------------------------
# Filling mode fallback
# ----------------------------
FILLING_CANDIDATES = [
    mt5.ORDER_FILLING_RETURN,
    mt5.ORDER_FILLING_IOC,
    mt5.ORDER_FILLING_FOK,
]


def _send_with_filling_fallback(request: dict, symbol: str):
    """
    Try multiple filling modes to avoid retcode=10030 (Unsupported filling mode).
    Returns (result, used_filling) where used_filling can be None if fail.
    """
    last_result = None

    for filling in FILLING_CANDIDATES:
        req = dict(request)
        req["type_filling"] = int(filling)

        result = mt5.order_send(req)
        last_result = result

        if result is None:
            time.sleep(0.15)
            continue

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result, filling

        if int(result.retcode) == 10030 or "Unsupported filling mode" in str(getattr(result, "comment", "")):
            continue

        return result, filling

    return last_result, None


# ----------------------------
# Position closing
# ----------------------------
def close_position_ticket(position, deviation=20) -> bool:
    symbol = str(position.symbol).strip()

    if not ensure_symbol(symbol):
        msg = f"❌ symbol_select failed while closing {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return False

    tick = _get_valid_tick(symbol)
    if tick is None:
        msg = f"❌ No valid tick (bid/ask=0) while closing {symbol}. Market may be closed. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return False

    if position.type == mt5.POSITION_TYPE_BUY:
        close_type = mt5.ORDER_TYPE_SELL
        price = float(tick.bid)
    else:
        close_type = mt5.ORDER_TYPE_BUY
        price = float(tick.ask)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "position": int(position.ticket),
        "volume": float(position.volume),
        "type": int(close_type),
        "price": float(price),
        "deviation": int(deviation),
        "magic": int(getattr(position, "magic", 0) or 0),
        "type_time": mt5.ORDER_TIME_GTC,
        "comment": "bot:close_opposite",
    }

    result, used_fill = _send_with_filling_fallback(request, symbol)

    if result is None:
        msg = f"❌ order_send None while closing {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = f"✅ Closed position {position.ticket} on {symbol} (vol={position.volume}) fill={used_fill}"
        print(msg)
        send_telegram(msg)
        return True

    msg = (
        f"❌ Failed to close position {position.ticket} on {symbol}\n"
        f"retcode: {result.retcode}\n"
        f"comment: {getattr(result, 'comment', '')}"
    )
    print(msg)
    send_telegram(msg)
    return False


def close_opposite_positions(symbol, incoming_signal, magic=None, deviation=20) -> int:
    symbol = str(symbol).strip()
    incoming_signal = str(incoming_signal).upper().strip()
    if incoming_signal not in ("BUY", "SELL"):
        return 0

    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        print(f"⚠️ positions_get returned None for {symbol}. MT5 ERROR: {mt5.last_error()}")
        return 0

    to_close = []
    for p in positions:
        if magic is not None and int(getattr(p, "magic", 0) or 0) != int(magic):
            continue
        if incoming_signal == "SELL" and p.type == mt5.POSITION_TYPE_BUY:
            to_close.append(p)
        elif incoming_signal == "BUY" and p.type == mt5.POSITION_TYPE_SELL:
            to_close.append(p)

    closed = 0
    for p in to_close:
        if close_position_ticket(p, deviation=deviation):
            closed += 1
    return closed


# ----------------------------
# Market order opening
# ----------------------------
def open_trade(
    symbol,
    signal,
    lot,
    magic,
    deviation=20,
    sl_pips=None,
    tp_pips=None,
    sl_price=None,
    tp_price=None,
):
    symbol = str(symbol).strip()
    signal = str(signal).upper().strip()

    if signal not in ("BUY", "SELL"):
        msg = f"❌ Invalid signal '{signal}' for {symbol}. Must be BUY or SELL."
        print(msg)
        send_telegram(msg)
        return None

    if not ensure_symbol(symbol):
        msg = f"❌ symbol_select failed for {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    info = mt5.symbol_info(symbol)
    if info is None:
        msg = f"❌ symbol_info() returned None for {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    # ✅ normalize lot to broker rules (min/max/step)
    lot = _normalize_volume(lot, info)

    # ✅ FIX: use valid tick (bid/ask must be > 0)
    tick = _get_valid_tick(symbol)
    if tick is None:
        msg = f"❌ No valid tick (bid/ask=0) for {symbol}. Market may be closed or no quotes. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    digits = int(info.digits)
    point = float(info.point)

    if signal == "BUY":
        price = float(tick.ask)
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = float(tick.bid)
        order_type = mt5.ORDER_TYPE_SELL

    if price <= 0:
        msg = f"❌ Invalid tick price for {symbol}: price={price}. Cannot place order."
        print(msg)
        send_telegram(msg)
        return None

    price = round(price, digits)

    # --- Determine SL/TP ---
    if sl_price is not None and tp_price is not None:
        sl = float(sl_price)
        tp = float(tp_price)
    else:
        if sl_pips is None or tp_pips is None:
            msg = f"❌ Missing SL/TP for {symbol}. Provide sl_price/tp_price or sl_pips/tp_pips."
            print(msg)
            send_telegram(msg)
            return None

        if signal == "BUY":
            sl = price - (float(sl_pips) * point)
            tp = price + (float(tp_pips) * point)
        else:
            sl = price + (float(sl_pips) * point)
            tp = price - (float(tp_pips) * point)

    sl = round(float(sl), digits)
    tp = round(float(tp), digits)

    # ✅ enforce min stops
    sl, tp, min_dist = _ensure_min_stops(price, sl, tp, signal, info, buffer_points=10)

    # ✅ final validation: correct sides
    ok, price, sl, tp = _validate_sl_tp(price, sl, tp, signal, info)
    if not ok:
        msg = (
            f"❌ Invalid SL/TP sides for {symbol}\n"
            f"signal={signal} price={price} sl={sl} tp={tp}\n"
            f"(BUY requires SL < price < TP | SELL requires TP < price < SL)"
        )
        print(msg)
        send_telegram(msg)
        return None

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": int(order_type),
        "price": float(price),
        "sl": float(sl),
        "tp": float(tp),
        "magic": int(magic),
        "deviation": int(deviation),
        "type_time": mt5.ORDER_TIME_GTC,
        "comment": f"bot:{signal}",
    }

    # Try sending with filling fallback
    result, used_fill = _send_with_filling_fallback(request, symbol)

    if result is None:
        msg = f"❌ order_send returned None for {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = (
            f"✅ {signal} {symbol}\n"
            f"Lot: {lot}\n"
            f"Entry: {price}\n"
            f"SL: {sl}\n"
            f"TP: {tp}\n"
            f"MinStopUsed: {min_dist}\n"
            f"Fill: {used_fill}\n"
            f"Ticket: {result.order}"
        )
        print(msg)
        send_telegram(msg)
        return result

    msg = (
        f"❌ Order failed: {signal} {symbol}\n"
        f"retcode: {result.retcode}\n"
        f"comment: {getattr(result, 'comment', '')}\n"
        f"price: {price} sl: {sl} tp: {tp}\n"
        f"min_stop_used: {min_dist}"
    )
    print(msg)
    send_telegram(msg)
    return result


# ----------------------------
# Optional: Limit order helper
# ----------------------------
def place_limit_order(
    symbol,
    signal,
    lot,
    magic,
    deviation=20,
    entry_price=None,
    sl_price=None,
    tp_price=None,
):
    symbol = str(symbol).strip()
    signal = str(signal).upper().strip()

    if signal not in ("BUY", "SELL"):
        msg = f"❌ Invalid limit signal '{signal}' for {symbol}"
        print(msg)
        send_telegram(msg)
        return None

    if entry_price is None or sl_price is None or tp_price is None:
        msg = f"❌ Missing entry/sl/tp for limit on {symbol}"
        print(msg)
        send_telegram(msg)
        return None

    if not ensure_symbol(symbol):
        msg = f"❌ symbol_select failed for {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    info = mt5.symbol_info(symbol)
    if info is None:
        msg = f"❌ symbol_info None for {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    lot = _normalize_volume(lot, info)

    digits = int(info.digits)
    entry = round(float(entry_price), digits)
    sl = round(float(sl_price), digits)
    tp = round(float(tp_price), digits)

    # basic sanity
    ok, entry, sl, tp = _validate_sl_tp(entry, sl, tp, signal, info)
    if not ok:
        msg = f"❌ Invalid limit SL/TP sides for {symbol} | entry={entry} sl={sl} tp={tp}"
        print(msg)
        send_telegram(msg)
        return None

    order_type = mt5.ORDER_TYPE_BUY_LIMIT if signal == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": float(lot),
        "type": int(order_type),
        "price": float(entry),
        "sl": float(sl),
        "tp": float(tp),
        "magic": int(magic),
        "deviation": int(deviation),
        "type_time": mt5.ORDER_TIME_GTC,
        "comment": f"bot:LIMIT:{signal}",
    }

    result, used_fill = _send_with_filling_fallback(request, symbol)

    if result is None:
        msg = f"❌ limit order_send None for {symbol}. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = f"✅ LIMIT placed {signal} {symbol} | lot={lot} entry={entry} sl={sl} tp={tp} fill={used_fill} ticket={result.order}"
        print(msg)
        send_telegram(msg)
        return result

    msg = (
        f"❌ LIMIT failed {signal} {symbol}\n"
        f"retcode: {result.retcode}\n"
        f"comment: {getattr(result, 'comment', '')}\n"
        f"entry: {entry} sl: {sl} tp: {tp}"
    )
    print(msg)
    send_telegram(msg)
    return result