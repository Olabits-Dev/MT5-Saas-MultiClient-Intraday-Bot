import time
import MetaTrader5 as mt5
import pandas as pd

from telegram import send_telegram
from trade_executor import open_trade, close_opposite_positions
from risk_management import calculate_lot_by_balance
from news_filter import is_news_blocked  # ✅ Finnhub news avoidance

DEFAULT_MAGIC = 777777
DEFAULT_DEVIATION = 20

# ✅ Normal stacking for LONDON/NY
MAX_POSITIONS_PER_DIRECTION = 2

# ✅ ASIA: NO stacking (max 1 per direction)
MAX_POSITIONS_PER_DIRECTION_ASIA = 1

# ✅ XAU + BTC special rule: only 1 total position (BUY or SELL)
MAX_TOTAL_POSITIONS_PER_SYMBOL = {
    "XAUUSD": 1,
    "BTCUSD": 1,
}

RR = 5

ALLOWED_BASE_SYMBOLS = {"BTCUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPJPY"}

MAX_LOT_CAP = 0.05

ATR_BASE_SYMBOLS = {"BTCUSD", "XAUUSD"}
ATR_CONFIG = {
    "BTCUSD": {"tf": mt5.TIMEFRAME_H1, "period": 14, "mult": 1.8},
    "XAUUSD": {"tf": mt5.TIMEFRAME_H1, "period": 14, "mult": 1.5},
}

PIPS_CONFIG = {
    "EURUSD": {"sl_pips": 300},
    "USDJPY": {"sl_pips": 350},
    "GBPJPY": {"sl_pips": 450},
}


def ensure_symbol(symbol: str, tries: int = 5, delay: float = 0.4) -> bool:
    """
    ✅ Reliable symbol enable/select (fixes 'Terminal: Call failed')
    """
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


def _positions(symbol: str):
    pos = mt5.positions_get(symbol=symbol)
    if pos is None:
        print(f"⚠️ positions_get None for {symbol}. MT5 ERROR: {mt5.last_error()}")
        return []
    return list(pos)


def count_positions(symbol: str, magic: int, direction: str) -> int:
    direction = direction.upper().strip()
    positions = _positions(symbol)

    c = 0
    for p in positions:
        if int(p.magic) != int(magic):
            continue
        if direction == "BUY" and p.type == mt5.POSITION_TYPE_BUY:
            c += 1
        elif direction == "SELL" and p.type == mt5.POSITION_TYPE_SELL:
            c += 1
    return c


def count_total_positions(symbol: str, magic: int) -> int:
    positions = _positions(symbol)
    return sum(1 for p in positions if int(p.magic) == int(magic))


def open_pnl(symbol: str, magic: int):
    positions = _positions(symbol)
    return sum(float(p.profit) for p in positions if int(p.magic) == int(magic))


def get_min_lot(symbol: str) -> float:
    """
    ✅ Returns broker minimum lot for the symbol (e.g., 0.01).
    Falls back to 0.01 if MT5 info is unavailable.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.01
    try:
        vmin = float(info.volume_min)
        if vmin > 0:
            return vmin
    except Exception:
        pass
    return 0.01


def _get_atr(symbol: str, timeframe=mt5.TIMEFRAME_H1, period: int = 14) -> float | None:
    bars = period + 5
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) < period + 2:
        return None

    df = pd.DataFrame(rates)
    high, low, close = df["high"], df["low"], df["close"]

    tr = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean().iloc[-1]
    if pd.isna(atr):
        return None
    return float(atr)


def _get_entry_price(symbol: str, signal: str) -> float | None:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    if ask <= 0 or bid <= 0:
        return None
    return ask if signal == "BUY" else bid


def execute_trade(base_symbol, symbol, signal, client_login=None, server=None, session: str | None = None):
    """
    base_symbol: "EURUSD"
    symbol     : "EURUSDm"  (must keep case EXACT)

    ✅ Enforcements:
    - Finnhub News avoidance: block entries around high-impact events
    - If session == ASIAN -> no stacking (max 1 per direction)
    - XAUUSD + BTCUSD -> max 1 total position
    - XAUUSD -> LOT must always be broker minimum lot (e.g., 0.01)
    """

    base_symbol = str(base_symbol).upper().strip()
    symbol = str(symbol).strip()  # ✅ do NOT upper() broker symbol!

    if base_symbol not in ALLOWED_BASE_SYMBOLS:
        return None

    if signal is None:
        return None

    sig = str(signal).upper().strip()
    if sig not in ("BUY", "SELL"):
        return None

    # ✅ NEWS FILTER (Finnhub) - block NEW entries around events
    blocked, reason = is_news_blocked(base_symbol)
    if blocked:
        print(f"🛑 NEWS BLOCK {base_symbol}: {reason}")
        return None

    # ✅ Robust symbol select
    if not ensure_symbol(symbol):
        msg = f"❌ symbol_select failed for {base_symbol}({symbol}). MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    # ✅ Lot sizing uses broker symbol (suffix-safe)
    try:
        lot = calculate_lot_by_balance(symbol, max_lot_cap=MAX_LOT_CAP)
    except Exception as e:
        msg = f"❌ Lot calc failed for {base_symbol}({symbol}): {e}"
        print(msg)
        send_telegram(msg)
        return None

    # ✅ XAUUSD only: force broker minimum lot (e.g. 0.01)
    if base_symbol == "XAUUSD":
        min_lot = get_min_lot(symbol)
        if float(lot) != float(min_lot):
            print(f"🪙 XAUUSD lot override -> using broker min lot {min_lot} (was {lot})")
        lot = min_lot

    if client_login and server:
        print(f"📌 Client {client_login} @ {server} -> {sig} {base_symbol}({symbol})")

    pnl = open_pnl(symbol, DEFAULT_MAGIC)
    if pnl != 0:
        print(f"📊 Current open PnL ({base_symbol}) = {pnl:.2f}")

    # 1) ✅ NO-HEDGE: close opposite first
    closed = close_opposite_positions(
        symbol=symbol,
        incoming_signal=sig,
        magic=DEFAULT_MAGIC,
        deviation=DEFAULT_DEVIATION
    )
    if closed > 0:
        print(f"🔁 Closed {closed} opposite position(s) on {base_symbol} before opening {sig}")

    # ✅ XAU + BTC special rule: max total positions = 1 always
    max_total = MAX_TOTAL_POSITIONS_PER_SYMBOL.get(base_symbol)
    if max_total is not None:
        total_now = count_total_positions(symbol, DEFAULT_MAGIC)
        if total_now >= int(max_total):
            print(f"⏭️ {base_symbol} max total positions reached ({total_now}/{max_total}). Skipping.")
            return None

    # 2) ✅ STACKING CONTROL (session-aware)
    max_per_dir = MAX_POSITIONS_PER_DIRECTION
    if str(session).upper().strip() == "ASIAN":
        max_per_dir = MAX_POSITIONS_PER_DIRECTION_ASIA  # ✅ no stacking in Asia

    same_count = count_positions(symbol, DEFAULT_MAGIC, sig)
    if same_count >= max_per_dir:
        print(
            f"⏭️ {base_symbol} already has {same_count} {sig} position(s). "
            f"Max={max_per_dir} for session={session}. Skipping."
        )
        return None

    # 3) ✅ SL/TP Hybrid
    entry = _get_entry_price(symbol, sig)
    if entry is None:
        msg = f"❌ No valid tick price for {base_symbol}({symbol}). Market closed/no quotes. MT5 ERROR: {mt5.last_error()}"
        print(msg)
        send_telegram(msg)
        return None

    # ATR-based (BTC/XAU)
    if base_symbol in ATR_BASE_SYMBOLS:
        cfg = ATR_CONFIG.get(base_symbol, {"tf": mt5.TIMEFRAME_H1, "period": 14, "mult": 1.5})
        atr = _get_atr(symbol, timeframe=cfg["tf"], period=int(cfg["period"]))
        if atr is None:
            msg = f"❌ ATR unavailable for {base_symbol}({symbol})."
            print(msg)
            send_telegram(msg)
            return None

        sl_dist = float(atr) * float(cfg["mult"])
        tp_dist = sl_dist * float(RR)

        if sig == "BUY":
            sl_price = entry - sl_dist
            tp_price = entry + tp_dist
        else:
            sl_price = entry + sl_dist
            tp_price = entry - tp_dist

        print(
            f"🧮 {base_symbol}({symbol}) ATR -> lot={lot} entry={entry:.5f} "
            f"ATR={atr:.5f} mult={cfg['mult']} SLdist={sl_dist:.5f} TPdist={tp_dist:.5f} (RR=1:{RR})"
        )

        return open_trade(
            symbol=symbol,
            signal=sig,
            lot=lot,
            magic=DEFAULT_MAGIC,
            deviation=DEFAULT_DEVIATION,
            sl_price=sl_price,
            tp_price=tp_price
        )

    # Pips-mode (FX)
    cfg = PIPS_CONFIG.get(base_symbol)
    if not cfg:
        msg = f"❌ No pips config for {base_symbol}"
        print(msg)
        send_telegram(msg)
        return None

    sl_pips = float(cfg["sl_pips"])
    tp_pips = float(sl_pips * RR)

    print(f"🧮 {base_symbol}({symbol}) PIPS -> lot={lot} SL_pips={sl_pips} TP_pips={tp_pips} (RR=1:{RR})")

    return open_trade(
        symbol=symbol,
        signal=sig,
        lot=lot,
        magic=DEFAULT_MAGIC,
        deviation=DEFAULT_DEVIATION,
        sl_pips=sl_pips,
        tp_pips=tp_pips
    )