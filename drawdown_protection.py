# drawdown_protection.py
import json
import os
from datetime import datetime, timezone
import MetaTrader5 as mt5

DEFAULT_DD_LIMIT_PCT = 5.0  # fallback if client doesn't specify dd_limit_pct
STATE_DIR = "dd_state"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _state_path(login: int) -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"dd_{int(login)}.json")


def _load_state(login: int) -> dict:
    path = _state_path(login)
    if not os.path.exists(path):
        return {"date": _today_utc(), "start_equity": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"date": _today_utc(), "start_equity": None}


def _save_state(login: int, state: dict):
    path = _state_path(login)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def allowed(dd_limit_pct: float | None = None, login: int | None = None) -> bool:
    """
    Returns True if client is allowed to trade today based on daily DD%.

    dd_limit_pct:
      - if None => DEFAULT_DD_LIMIT_PCT
      - else uses given value (e.g., 0.5)

    login:
      - if None => tries account_info().login
    """
    acc = mt5.account_info()
    if acc is None:
        # If MT5 is not connected, safest is to block trading
        print("⚠️ DD: account_info() is None. Blocking trading for safety.")
        return False

    login = int(login or acc.login)
    dd_limit_pct = float(dd_limit_pct if dd_limit_pct is not None else DEFAULT_DD_LIMIT_PCT)

    # sanity
    if dd_limit_pct <= 0:
        dd_limit_pct = 0.1  # never allow zero/negative

    state = _load_state(login)
    today = _today_utc()

    equity_now = float(getattr(acc, "equity", 0.0) or 0.0)
    if equity_now <= 0:
        print("⚠️ DD: equity invalid. Blocking trading for safety.")
        return False

    # Reset daily state if new day OR missing
    if state.get("date") != today or not state.get("start_equity"):
        state = {"date": today, "start_equity": equity_now}
        _save_state(login, state)
        print(f"🆕 DD: Reset daily start_equity={equity_now:.2f} for login={login}")

    start_equity = float(state["start_equity"])
    dd_pct = ((start_equity - equity_now) / start_equity) * 100.0

    if dd_pct >= dd_limit_pct:
        print(f"⛔ DD protection: login={login} DD={dd_pct:.2f}% >= limit={dd_limit_pct:.2f}%")
        return False

    return True