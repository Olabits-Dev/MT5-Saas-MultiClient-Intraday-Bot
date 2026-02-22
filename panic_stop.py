import os
import time
import MetaTrader5 as mt5

STOP_FILE = "STOP.txt"

# ---------------------------
# Stop file helpers
# ---------------------------
def stop_requested() -> bool:
    return os.path.exists(STOP_FILE)


def clear_stop_file():
    try:
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
    except Exception:
        pass


# ---------------------------
# MT5 connection helpers (FIX for -10004 No IPC connection)
# ---------------------------
def ensure_mt5_connection(tries: int = 6, delay: float = 1.0) -> bool:
    """
    ✅ Ensures MT5 IPC connection is alive.
    Fixes: (-10004, 'No IPC connection') by re-initializing MT5 if needed.

    NOTE:
    - This will only work if the MT5 terminal is open and logged in.
    - If you use mt5.initialize(path=...) in your main bot, keep MT5 open.
    """
    last_err = None

    for attempt in range(1, tries + 1):
        try:
            term = mt5.terminal_info()
            acct = mt5.account_info()
            if term is not None and acct is not None:
                return True
        except Exception:
            pass

        last_err = mt5.last_error()

        # try re-init
        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(0.2)

        ok = mt5.initialize()
        if ok:
            time.sleep(0.4)
            term = mt5.terminal_info()
            acct = mt5.account_info()
            if term is not None and acct is not None:
                return True

        print(f"⚠️ [STOP] MT5 reconnect attempt {attempt}/{tries} failed. last_error={last_err}")
        time.sleep(delay)

    print(f"❌ [STOP] MT5 connection not available. last_error={last_err}. "
          f"Keep MT5 open + logged in, then try STOP again.")
    return False


# ---------------------------
# Robust helpers
# ---------------------------
def _safe_positions_get(tries: int = 8, delay: float = 0.35):
    """
    ✅ Robust positions_get with reconnection.
    If MT5 is disconnected, try to reconnect first.
    """
    if not ensure_mt5_connection():
        return []

    last_err = None
    for _ in range(tries):
        pos = mt5.positions_get()
        if pos is not None:
            return list(pos)
        last_err = mt5.last_error()

        # If IPC drops mid-call, attempt reconnect once
        if last_err and int(last_err[0]) == -10004:
            ensure_mt5_connection(tries=3, delay=0.8)

        time.sleep(delay)

    print(f"⚠️ [STOP] positions_get still None after retries. last_error={last_err}")
    return []


def _ensure_symbol(symbol: str, tries: int = 6, delay: float = 0.35) -> bool:
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


def _safe_tick(symbol: str, tries: int = 10, delay: float = 0.2):
    """
    ✅ Robust tick fetch:
    - retries
    - rejects bid/ask == 0 which causes invalid price closes
    """
    symbol = str(symbol).strip()
    for _ in range(tries):
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            bid = float(getattr(tick, "bid", 0.0) or 0.0)
            ask = float(getattr(tick, "ask", 0.0) or 0.0)
            if bid > 0 and ask > 0:
                return tick
        time.sleep(delay)
    return None


def _order_send_with_fill_fallback(request: dict):
    """
    Some brokers reject certain filling modes, so try a few.
    """
    filling_modes = [
        mt5.ORDER_FILLING_RETURN,
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_FOK,
    ]

    last = None
    for mode in filling_modes:
        req = dict(request)
        req["type_filling"] = int(mode)
        result = mt5.order_send(req)
        last = result

        if result is None:
            time.sleep(0.15)
            continue

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result

        # Unsupported filling mode -> try next
        if int(result.retcode) == 10030 or "Unsupported filling mode" in str(getattr(result, "comment", "")):
            continue

        # Other errors: still try next mode (panic close should be stubborn)
        time.sleep(0.15)

    return last


def _close_position(p, deviation: int = 20) -> bool:
    """
    ✅ Close a single position (panic stop).
    Handles reconnects and common MT5 transient errors.
    """
    if not ensure_mt5_connection():
        return False

    symbol = str(p.symbol).strip()

    if not _ensure_symbol(symbol):
        print(f"❌ [STOP] symbol_select failed for {symbol}. MT5 ERROR: {mt5.last_error()}")
        return False

    tick = _safe_tick(symbol)
    if tick is None:
        print(f"❌ [STOP] no valid tick (bid/ask=0) for {symbol}. MT5 ERROR: {mt5.last_error()}")
        return False

    if p.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = float(tick.bid)
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = float(tick.ask)

    if price <= 0:
        print(f"❌ [STOP] invalid close price for {symbol}: {price}")
        return False

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "position": int(p.ticket),
        "volume": float(p.volume),
        "type": int(order_type),
        "price": float(price),
        "deviation": int(deviation),
        "magic": int(getattr(p, "magic", 0) or 0),
        "type_time": mt5.ORDER_TIME_GTC,
        "comment": "BOT_STOP_CLOSE",
    }

    # Retry close a few times (and reconnect on IPC drop)
    for attempt in range(1, 6):
        result = _order_send_with_fill_fallback(request)

        if result is None:
            err = mt5.last_error()
            print(f"❌ [STOP] order_send None (attempt {attempt}) for {symbol}. MT5 ERROR: {err}")
            if err and int(err[0]) == -10004:
                ensure_mt5_connection(tries=3, delay=0.8)
            time.sleep(0.25)
            continue

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"✅ [STOP] closed {symbol} ticket={p.ticket} vol={p.volume} magic={getattr(p, 'magic', 0)}")
            return True

        # Common transient codes: requote, off quotes, trade context busy, etc.
        print(
            f"❌ [STOP] close failed (attempt {attempt}) {symbol} ticket={p.ticket} magic={getattr(p, 'magic', 0)} "
            f"retcode={result.retcode} comment={getattr(result, 'comment', '')}"
        )

        # If IPC dropped mid-close
        err = mt5.last_error()
        if err and int(err[0]) == -10004:
            ensure_mt5_connection(tries=3, delay=0.8)

        time.sleep(0.25)

    return False


# ---------------------------
# Public API
# ---------------------------
def close_positions_by_magic(magic: int, deviation: int = 20) -> int:
    """
    Close positions where position.magic == magic.
    """
    positions = _safe_positions_get()
    if not positions:
        print("🧾 [STOP] total positions=0 (nothing to close)")
        return 0

    matches = [p for p in positions if int(getattr(p, "magic", 0) or 0) == int(magic)]
    print(f"🧾 [STOP] total positions={len(positions)} | matching magic({magic})={len(matches)}")

    closed = 0
    for p in matches:
        if _close_position(p, deviation=deviation):
            closed += 1

    if closed == 0 and len(matches) > 0:
        print("⚠️ [STOP] Found matching positions but failed to close them. Check logs above (retcodes).")

    return closed


def close_all_positions(deviation: int = 20) -> int:
    """
    Close ALL positions on the account (panic flatten).
    """
    positions = _safe_positions_get()
    if not positions:
        print("🧾 [STOP] total positions=0 (nothing to close)")
        return 0

    print(f"🧾 [STOP] closing ALL positions on account: total={len(positions)}")

    closed = 0
    for p in positions:
        if _close_position(p, deviation=deviation):
            closed += 1

    if closed == 0 and len(positions) > 0:
        print("⚠️ [STOP] There were open positions but none closed. Check retcodes above.")

    return closed