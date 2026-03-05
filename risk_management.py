import MetaTrader5 as mt5
import math


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    steps = round(value / step)
    return steps * step


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def _decimals_from_step(step: float) -> int:
    if step <= 0:
        return 2
    s = f"{step:.10f}".rstrip("0")
    if "." not in s:
        return 2
    return max(2, len(s.split(".")[1]))


def _ensure_symbol_ready(symbol: str):
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) failed: {mt5.last_error()}")
    return info


def _broker_min_lot(info) -> float:
    vol_min = float(getattr(info, "volume_min", 0.01) or 0.01)
    vol_step = float(getattr(info, "volume_step", vol_min) or vol_min)
    decimals = _decimals_from_step(vol_step)

    lot = _round_to_step(vol_min, vol_step)
    lot = round(lot, decimals)

    # final safety
    if lot < vol_min:
        lot = vol_min
    return float(lot)


def _enforce_broker_volume_rules(lot: float, info, max_lot_cap: float | None = None) -> float:
    """
    Enforce broker constraints:
      - >= volume_min
      - <= volume_max (and <= max_lot_cap if provided)
      - aligned to volume_step (floor-to-step is safest)
    """
    vol_min = float(getattr(info, "volume_min", 0.01) or 0.01)
    vol_max = float(getattr(info, "volume_max", 100.0) or 100.0)
    vol_step = float(getattr(info, "volume_step", vol_min) or vol_min)

    if max_lot_cap is not None:
        vol_max = min(vol_max, float(max_lot_cap))

    lot = float(lot)
    lot = _clamp(lot, vol_min, vol_max)

    # floor-to-step prevents "Invalid volume" on some brokers
    lot = _floor_to_step(lot, vol_step)

    decimals = _decimals_from_step(vol_step)
    lot = round(lot, decimals)

    if lot < vol_min:
        lot = vol_min
    return float(lot)


# ============================================================
# A) RISK-% LOT SIZING (unchanged behavior, stronger enforcement)
# ============================================================
def calculate_lot(symbol: str, risk_percent: float, sl_pips: float) -> float:
    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError(f"account_info() failed: {mt5.last_error()}")

    info = _ensure_symbol_ready(symbol)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"symbol_info_tick({symbol}) failed: {mt5.last_error()}")

    balance = float(acc.balance)
    risk_amount = balance * float(risk_percent) / 100.0

    point = float(info.point)
    sl_distance_price = float(sl_pips) * point
    if sl_distance_price <= 0:
        raise ValueError("sl_pips must be > 0")

    entry = float(tick.ask)
    sl = entry - sl_distance_price

    profit_if_sl = mt5.order_calc_profit(
        mt5.ORDER_TYPE_BUY,
        symbol,
        1.0,
        entry,
        sl
    )
    if profit_if_sl is None:
        raise RuntimeError(f"order_calc_profit failed: {mt5.last_error()}")

    risk_per_1lot = abs(float(profit_if_sl))

    if risk_per_1lot <= 0:
        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        if tick_value > 0 and tick_size > 0:
            risk_per_1lot = (sl_distance_price / tick_size) * tick_value
        else:
            risk_per_1lot = sl_distance_price * 1.0

    raw_lot = risk_amount / risk_per_1lot

    # ✅ enforce broker min/max/step
    lot = _enforce_broker_volume_rules(raw_lot, info, max_lot_cap=None)
    return float(lot)


# ============================================================
# B) BALANCE-TIER LOT SIZING ✅ with account currency detection
#    ✅ NEW:
#    - XAUUSD on USD accounts => ALWAYS broker minimum lot
#    - Always enforce broker min/step/max
# ============================================================
def calculate_lot_by_balance(
    symbol: str,
    balance: float | None = None,
    max_lot_cap: float | None = None,
    min_balance: float = 10.0,
    step_per_100: float = 0.01,
    base_currency_required: str = "USD",
    xau_force_min_lot_on_usd: bool = True,   # ✅ NEW
) -> float:

    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError(f"account_info() failed: {mt5.last_error()}")

    info = _ensure_symbol_ready(symbol)

    acc_currency = str(getattr(acc, "currency", "") or "").upper().strip()
    base_req = str(base_currency_required).upper().strip()

    # ✅ If non-USD account => always broker minimum lot (your original behavior)
    if acc_currency and acc_currency != base_req:
        return _broker_min_lot(info)

    # ✅ USD account special rule: XAUUSD must always use broker minimum lot
    sym_up = str(symbol).upper()
    if xau_force_min_lot_on_usd and ("XAUUSD" in sym_up):
        return _broker_min_lot(info)

    # USD accounts: apply tier sizing (your logic)
    if balance is None:
        balance = float(acc.balance)

    if float(balance) < float(min_balance):
        raw_lot = float(step_per_100)
    else:
        tier = int((float(balance) - 1) // 100)  # 10-100 -> 0, 101-200 -> 1
        raw_lot = float(tier + 1) * float(step_per_100)

    # ✅ enforce broker min/max/step + your cap
    lot = _enforce_broker_volume_rules(raw_lot, info, max_lot_cap=max_lot_cap)
    return float(lot)