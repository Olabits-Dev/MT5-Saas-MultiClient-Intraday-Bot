import MetaTrader5 as mt5
from datetime import datetime

# ---------------- SETTINGS ----------------
MAX_DD = 5.0  # % daily max drawdown per client
# -----------------------------------------

# Store baselines per account login:
# { login: {"start_equity": float, "day": int} }
_STATE = {}


def _server_day():
    """
    Use broker/server time by reading tick time from any common symbol.
    Falls back to UTC day if tick is not available.
    """
    tick = mt5.symbol_info_tick("EURUSD")
    if tick is None:
        return datetime.utcnow().day
    return datetime.fromtimestamp(tick.time).day


def reset_day_for_current_account():
    """
    Reset daily baseline equity for the currently connected MT5 account.
    """
    acc = mt5.account_info()
    if acc is None:
        return False

    login = int(acc.login)
    _STATE[login] = {
        "start_equity": float(acc.equity),
        "day": _server_day(),
    }

    print(
        f"🔄 DD reset | Client {login} | Start equity: {_STATE[login]['start_equity']:.2f} | MaxDD: {MAX_DD:.2f}%"
    )
    return True


def allowed():
    """
    Per-client drawdown check for the CURRENT connected MT5 account.
    Returns True if trading is allowed for that client today.
    """
    acc = mt5.account_info()
    if acc is None:
        return False

    login = int(acc.login)
    today = _server_day()

    # Initialize/reset baseline if missing or new day
    if login not in _STATE or _STATE[login].get("day") != today:
        ok = reset_day_for_current_account()
        if not ok:
            return False

    start_equity = float(_STATE[login]["start_equity"])
    equity = float(acc.equity)

    # Extra safety guard
    if start_equity <= 0:
        reset_day_for_current_account()
        start_equity = float(_STATE[login]["start_equity"])

    dd = (start_equity - equity) / start_equity * 100.0

    if dd >= MAX_DD:
        print(
            f"⛔ DAILY DD LIMIT HIT | Client {login} | DD: {dd:.2f}% (Max: {MAX_DD:.2f}%) — trading blocked today"
        )
        return False

    return True
