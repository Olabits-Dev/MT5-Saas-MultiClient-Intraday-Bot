import os
import time
from datetime import datetime

import MetaTrader5 as mt5
from dotenv import load_dotenv

from strategy import get_signal, get_dual_bias
from trade_manager import execute_trade, DEFAULT_MAGIC
from session_filter import get_current_session
from decrypt_clients import load_clients
from drawdown_protection import allowed
from position_manager import manage_open_positions
from symbol_utils import get_symbol_map
from telegram import send_telegram

from panic_stop import (
    stop_requested,
    clear_stop_file,
    close_positions_by_magic,
    close_all_positions,
)

# ------------------- LOAD ENV -------------------
load_dotenv()

HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
MT5_PATH = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")

CLIENTS_FILE = "clients.enc"

# ✅ Base symbols
BASE_SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPJPY"]

# =====================================================
# ✅ SIGNAL TIMEFRAME CHANGE (ONLY CHANGE MADE)
# =====================================================
ASIA_TF = mt5.TIMEFRAME_H1
LONDON_TF = mt5.TIMEFRAME_H1
NY_TF = mt5.TIMEFRAME_H1

# =====================================================
# ✅ Dual Bias Settings (UNCHANGED)
# =====================================================
PRIMARY_BIAS_TF = mt5.TIMEFRAME_H4
CONFIRM_BIAS_TF = mt5.TIMEFRAME_H1
PRIMARY_STABLE_BARS = 2
CONFIRM_STABLE_BARS = 2

# ✅ Session rule
BLOCK_XAU_LONDON = True

send_telegram("🚀 Trading bot started (Dual Bias H4/H1 + Signal H1)")


def is_expired(expiry_str: str) -> bool:
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        return datetime.utcnow().date() > exp
    except Exception:
        return True


def connect_client(client: dict) -> bool:
    login = int(client.get("login", 0))
    password = client.get("password")
    server = client.get("server")

    if not login or not password or not server:
        print(f"❌ Client record incomplete: {client}")
        return False

    ok = mt5.initialize(path=MT5_PATH, login=login, password=password, server=server)
    if not ok:
        print(f"❌ Failed to connect client {login}")
        print("MT5 ERROR:", mt5.last_error())
        return False

    acc = mt5.account_info()
    if acc is None:
        print("❌ account_info() failed")
        return False

    print(f"✅ Connected client {acc.login} | Balance: {acc.balance}")
    return True


def _tf_for_session(session: str):
    if session == "ASIAN":
        return ASIA_TF
    if session == "LONDON":
        return LONDON_TF
    if session == "NEWYORK":
        return NY_TF
    return mt5.TIMEFRAME_H1


def _tf_name(tf):
    if tf == mt5.TIMEFRAME_H1:
        return "H1"
    if tf == mt5.TIMEFRAME_H4:
        return "H4"
    return str(tf)


def _handle_panic_stop():
    if not stop_requested():
        return

    print("🛑 STOP.txt detected — closing positions...")
    send_telegram("🛑 STOP.txt detected — closing positions")

    closed_magic = close_positions_by_magic(DEFAULT_MAGIC)
    if closed_magic == 0:
        close_all_positions()

    clear_stop_file()
    mt5.shutdown()
    raise SystemExit("Bot stopped by STOP.txt")


def run_for_client(client: dict):
    session = get_current_session()
    print(f"🕒 Session: {session}")

    if session is None:
        return

    _handle_panic_stop()

    acc = mt5.account_info()
    if acc is None:
        return

    symbol_map = get_symbol_map(BASE_SYMBOLS, acc.login, acc.server)

    if not allowed():
        print("⛔ DD protection active")
        return

    manage_open_positions()

    tf = _tf_for_session(session)
    tf_name = _tf_name(tf)

    for base_symbol in BASE_SYMBOLS:
        _handle_panic_stop()

        if BLOCK_XAU_LONDON and session == "LONDON" and base_symbol == "XAUUSD":
            print("⛔ XAUUSD blocked in London")
            continue

        broker_symbol = symbol_map.get(base_symbol, base_symbol)

        final_bias, h4_bias, h1_bias = get_dual_bias(
            broker_symbol,
            primary_tf=PRIMARY_BIAS_TF,
            confirm_tf=CONFIRM_BIAS_TF,
            primary_stable=PRIMARY_STABLE_BARS,
            confirm_stable=CONFIRM_STABLE_BARS,
        )

        sig = get_signal(broker_symbol, timeframe=tf)
        s = str(sig).upper().strip() if sig else "NONE"

        print(
            f"{base_symbol}({broker_symbol}) "
            f"Bias(H4/H1): {h4_bias}/{h1_bias} → {final_bias} | "
            f"Signal({tf_name}): {s}"
        )

        if final_bias is None:
            continue

        if s in ("BUY", "SELL"):
            execute_trade(
                base_symbol=base_symbol,
                symbol=broker_symbol,
                signal=s,
                client_login=acc.login,
                server=acc.server,
                session=session,
            )


def main():
    print("🚀 MT5 Bot running (Signal H1 | Dual Bias H4/H1)")

    while True:
        try:
            _handle_panic_stop()

            clients = load_clients(CLIENTS_FILE)
            for client in clients:
                if not client.get("active", True):
                    continue
                if is_expired(client.get("expiry", "2099-12-31")):
                    continue

                if connect_client(client):
                    try:
                        run_for_client(client)
                    finally:
                        mt5.shutdown()

            print("BOT HEARTBEAT RUNNING...")
            time.sleep(HEARTBEAT_INTERVAL)

        except SystemExit:
            return
        except Exception as e:
            print("⚠️ MAIN LOOP ERROR:", e)
            time.sleep(10)


if __name__ == "__main__":
    main()