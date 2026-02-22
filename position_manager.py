# position_manager.py
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

import MetaTrader5 as mt5
from telegram import send_telegram

DEFAULT_MAGIC = 777777
DEFAULT_DEVIATION = 20

# ===== Profit Lock Rules =====
TRIGGER_RR = 3.0   # when price reaches 1:3RR
LOCK_RR = 2.0      # lock profit at 1:2RR

# Broker stop/freeze safety buffer
STOP_BUFFER_POINTS = 10

# Small anti-spam cooldown for SL modifications (NOT a 1H lock)
MIN_MODIFY_COOLDOWN_SECONDS = 3
_last_modify_ts_by_ticket: Dict[int, float] = {}

# ===== Close notification cursor (persist between restarts) =====
CURSOR_FILE = "deal_cursor.json"

# Optional: send open positions snapshot (can spam)
SEND_POSITION_SNAPSHOT = False
SNAPSHOT_COOLDOWN_SECONDS = 300  # 5 min
_last_snapshot_ts = 0.0


# ---------------------------
# Utility helpers
# ---------------------------
def ensure_symbol(symbol: str, tries: int = 6, delay: float = 0.25) -> bool:
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


def _min_stop_distance_price(info) -> float:
    stops_points = int(getattr(info, "trade_stops_level", 0) or 0)
    freeze_points = int(getattr(info, "trade_freeze_level", 0) or 0)
    min_points = max(stops_points, freeze_points, STOP_BUFFER_POINTS)
    return float(min_points) * float(info.point)


def _cooldown_ok(ticket: int) -> bool:
    if MIN_MODIFY_COOLDOWN_SECONDS <= 0:
        return True
    now = time.time()
    last = _last_modify_ts_by_ticket.get(int(ticket), 0.0)
    return (now - last) >= MIN_MODIFY_COOLDOWN_SECONDS


def _mark_modified(ticket: int):
    _last_modify_ts_by_ticket[int(ticket)] = time.time()


def _current_price(symbol: str, pos_type: int) -> Optional[float]:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid <= 0 or ask <= 0:
        return None
    return bid if pos_type == mt5.POSITION_TYPE_BUY else ask


def _calc_rr_reached(entry: float, sl: float, price: float, pos_type: int) -> Optional[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    move = (price - entry) if pos_type == mt5.POSITION_TYPE_BUY else (entry - price)
    return move / risk


def _locked_sl_price(entry: float, sl: float, pos_type: int, lock_rr: float) -> Optional[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    return entry + (lock_rr * risk) if pos_type == mt5.POSITION_TYPE_BUY else entry - (lock_rr * risk)


def _only_tighten(current_sl: float, new_sl: float, pos_type: int) -> bool:
    if pos_type == mt5.POSITION_TYPE_BUY:
        return new_sl > current_sl
    return new_sl < current_sl


def _respect_min_stop(symbol: str, pos_type: int, new_sl: float) -> Optional[float]:
    info = mt5.symbol_info(symbol)
    if info is None:
        return None

    price = _current_price(symbol, pos_type)
    if price is None:
        return None

    min_dist = _min_stop_distance_price(info)
    digits = int(info.digits)

    if pos_type == mt5.POSITION_TYPE_BUY:
        # SL must be <= price - min_dist
        max_sl = price - min_dist
        sl_adj = min(new_sl, max_sl)
    else:
        # SL must be >= price + min_dist
        min_sl = price + min_dist
        sl_adj = max(new_sl, min_sl)

    return round(float(sl_adj), digits)


def _modify_sl_only(position, new_sl: float, deviation: int = DEFAULT_DEVIATION) -> bool:
    symbol = str(position.symbol).strip()
    if not ensure_symbol(symbol):
        print(f"❌ [PM] symbol_select failed for {symbol}. MT5 ERROR: {mt5.last_error()}")
        return False

    # keep TP as-is
    tp_val = float(position.tp) if float(position.tp or 0) > 0 else 0.0

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": int(position.ticket),
        "sl": float(new_sl),
        "tp": tp_val,
        "magic": int(getattr(position, "magic", 0) or 0),
        "deviation": int(deviation),
        "comment": "profit_lock_1to2_at_1to3",
    }

    result = mt5.order_send(request)
    if result is None:
        print(f"❌ [PM] SLTP modify None for {symbol}. MT5 ERROR: {mt5.last_error()}")
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return True

    print(
        f"❌ [PM] Modify failed {symbol} ticket={position.ticket} "
        f"retcode={result.retcode} comment={getattr(result,'comment','')}"
    )
    return False


# ---------------------------
# Close notifications via Deal History
# ---------------------------
def _load_cursor() -> Dict[str, Any]:
    """
    Stores:
    - last_time (epoch seconds)
    - seen_deals (small set-like dict) for de-dup
    """
    if not os.path.exists(CURSOR_FILE):
        # default: look back 24 hours at first run
        now = int(time.time())
        return {"last_time": now - 24 * 3600, "seen_deals": {}}

    try:
        with open(CURSOR_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "last_time" not in data:
            data["last_time"] = int(time.time()) - 24 * 3600
        if "seen_deals" not in data:
            data["seen_deals"] = {}
        return data
    except Exception:
        now = int(time.time())
        return {"last_time": now - 24 * 3600, "seen_deals": {}}


def _save_cursor(data: Dict[str, Any]):
    try:
        with open(CURSOR_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _deal_time_to_str(ts: int) -> str:
    # show UTC for consistency
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def notify_closed_positions(magic: int = DEFAULT_MAGIC):
    """
    ✅ Sends Telegram when a position closes (TP/SL/manual/etc) with PnL.
    Uses history_deals_get and a cursor to avoid duplicates.
    """
    cursor = _load_cursor()
    last_time = int(cursor.get("last_time", int(time.time()) - 24 * 3600))
    seen = cursor.get("seen_deals", {}) or {}

    # query from last_time - small overlap (in case of clock drift)
    time_from = datetime.fromtimestamp(max(0, last_time - 60), tz=timezone.utc)
    time_to = datetime.now(timezone.utc) + timedelta(seconds=5)

    deals = mt5.history_deals_get(time_from, time_to)
    if deals is None:
        # if MT5 not connected, just skip gracefully
        return

    deals = list(deals)
    if not deals:
        return

    max_ts = last_time

    for d in deals:
        try:
            deal_id = int(getattr(d, "ticket", 0) or 0)
            if deal_id <= 0:
                continue

            # dedupe
            if str(deal_id) in seen:
                continue

            d_magic = int(getattr(d, "magic", 0) or 0)
            if int(d_magic) != int(magic):
                continue

            # only OUT deals (closed)
            entry = int(getattr(d, "entry", -1))
            if entry != mt5.DEAL_ENTRY_OUT:
                continue

            symbol = str(getattr(d, "symbol", "") or "").strip()
            profit = float(getattr(d, "profit", 0.0) or 0.0)
            volume = float(getattr(d, "volume", 0.0) or 0.0)
            reason = str(getattr(d, "comment", "") or "").strip()

            ts = int(getattr(d, "time", 0) or 0)
            if ts > max_ts:
                max_ts = ts

            # mark seen
            seen[str(deal_id)] = 1

            # Build message
            pnl_emoji = "✅" if profit >= 0 else "❌"
            msg = (
                f"{pnl_emoji} POSITION CLOSED\n"
                f"Symbol: {symbol}\n"
                f"Volume: {volume}\n"
                f"PnL: {profit:.2f}\n"
                f"Time: {_deal_time_to_str(ts)}\n"
            )
            if reason:
                msg += f"Comment: {reason}\n"

            send_telegram(msg)

        except Exception:
            continue

    # keep seen small
    if len(seen) > 2000:
        # drop old entries by resetting
        seen = {}

    cursor["last_time"] = max_ts if max_ts > 0 else int(time.time())
    cursor["seen_deals"] = seen
    _save_cursor(cursor)


# ---------------------------
# Optional snapshot
# ---------------------------
def notify_open_positions_snapshot(magic: int = DEFAULT_MAGIC):
    global _last_snapshot_ts
    if not SEND_POSITION_SNAPSHOT:
        return

    now = time.time()
    if (now - _last_snapshot_ts) < SNAPSHOT_COOLDOWN_SECONDS:
        return

    pos = mt5.positions_get()
    if pos is None:
        return

    bot_pos = [p for p in pos if int(getattr(p, "magic", 0) or 0) == int(magic)]
    if not bot_pos:
        _last_snapshot_ts = now
        return

    lines = []
    for p in bot_pos:
        symbol = str(p.symbol)
        typ = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        profit = float(p.profit or 0.0)
        lines.append(f"{symbol} {typ} | vol={p.volume} | pnl={profit:.2f} | ticket={p.ticket}")

    msg = "📌 OPEN POSITIONS SNAPSHOT\n" + "\n".join(lines[:15])
    send_telegram(msg)
    _last_snapshot_ts = now


# ---------------------------
# Main manager (call every heartbeat)
# ---------------------------
def manage_open_positions(magic: int = DEFAULT_MAGIC):
    """
    ✅ No 1H lock.
    - Sends close notifications (PnL) using history deals
    - Applies profit lock: at 1:3RR, SL -> lock 1:2RR
    - Sends Telegram when SL is adjusted
    """
    # 1) Notify closes first (so you get closure alerts ASAP)
    try:
        notify_closed_positions(magic=magic)
    except Exception:
        pass

    # 2) Optional snapshot
    try:
        notify_open_positions_snapshot(magic=magic)
    except Exception:
        pass

    # 3) Manage SL locks
    positions = mt5.positions_get()
    if positions is None:
        print(f"⚠️ [PM] positions_get None. MT5 ERROR: {mt5.last_error()}")
        return

    positions = list(positions)
    if not positions:
        return

    for p in positions:
        try:
            if int(getattr(p, "magic", 0) or 0) != int(magic):
                continue

            symbol = str(p.symbol).strip()
            entry = float(p.price_open)
            current_sl = float(p.sl or 0.0)

            # If SL missing, skip (can't compute RR safely)
            if current_sl <= 0:
                continue

            if not _cooldown_ok(p.ticket):
                continue

            price = _current_price(symbol, p.type)
            if price is None:
                continue

            rr = _calc_rr_reached(entry, current_sl, price, p.type)
            if rr is None or rr < TRIGGER_RR:
                continue

            desired_sl = _locked_sl_price(entry, current_sl, p.type, LOCK_RR)
            if desired_sl is None:
                continue

            # Only tighten, never loosen
            if not _only_tighten(current_sl, desired_sl, p.type):
                continue

            final_sl = _respect_min_stop(symbol, p.type, desired_sl)
            if final_sl is None:
                continue

            if not _only_tighten(current_sl, final_sl, p.type):
                continue

            ok = _modify_sl_only(p, final_sl)
            if ok:
                _mark_modified(p.ticket)

                msg = (
                    f"🔒 SL ADJUSTED (Profit Lock)\n"
                    f"Symbol: {symbol}\n"
                    f"Ticket: {p.ticket}\n"
                    f"RR reached: ≥ {TRIGGER_RR:.1f}\n"
                    f"New SL: {final_sl}\n"
                    f"Locked: ~{LOCK_RR:.1f}R\n"
                )
                print(f"✅ [PM] {msg.strip()}")
                send_telegram(msg)

        except Exception as e:
            print(f"⚠️ [PM] Error managing {getattr(p,'symbol','?')} ticket={getattr(p,'ticket','?')}: {e}")