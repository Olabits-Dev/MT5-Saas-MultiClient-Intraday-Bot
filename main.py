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

# ✅ Default base symbols (FX/Crypto)
DEFAULT_BASE_SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPJPY"]

# ✅ Deriv Synthetic indices base aliases (NEW)
DERIV_BASE_SYMBOLS = ["STEP", "V10", "V75"]

# ✅ Signal timeframe
SIGNAL_TF = mt5.TIMEFRAME_H1

# ✅ Dual Bias Settings
PRIMARY_BIAS_TF = mt5.TIMEFRAME_H4
CONFIRM_BIAS_TF = mt5.TIMEFRAME_H1
PRIMARY_STABLE_BARS = 2
CONFIRM_STABLE_BARS = 2

# ✅ Session rule (FX only)
BLOCK_XAU_LONDON = True

# ✅ Default DD if client doesn't override
DEFAULT_DD_LIMIT_PCT = 5.0

send_telegram("🚀 Trading bot started (Snapshot ON | Dual Bias H4/H1 | Signal H1 | Deriv STEP/V10/V75 | Per-client DD)")


# ------------------- Helpers -------------------
def is_expired(expiry_str: str) -> bool:
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        return datetime.utcnow().date() > exp
    except Exception:
        return True


def _normalize_pairs(pairs):
    if not pairs:
        return []
    out = []
    for p in pairs:
        s = str(p).upper().strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))  # dedupe preserve order


def get_client_pairs(client: dict):
    """
    If client has allowed_pairs => use it.
    Otherwise use DEFAULT_BASE_SYMBOLS (FX/Crypto default).
    """
    allowed_pairs = _normalize_pairs(client.get("allowed_pairs"))
    return allowed_pairs if allowed_pairs else DEFAULT_BASE_SYMBOLS


def get_client_dd_limit_pct(client: dict) -> float:
    """
    Per-client daily DD % (override), fallback to DEFAULT.
    Example: client["dd_limit_pct"] = 0.5
    """
    try:
        v = client.get("dd_limit_pct", DEFAULT_DD_LIMIT_PCT)
        v = float(v)
        if v <= 0:
            return float(DEFAULT_DD_LIMIT_PCT)
        if v < 0.1:
            return 0.1
        return v
    except Exception:
        return float(DEFAULT_DD_LIMIT_PCT)


def connect_client(client: dict) -> bool:
    login = int(client.get("login", 0))
    password = client.get("password")
    server = client.get("server")

    if not login or not password or not server:
        print(f"❌ Client record incomplete (missing login/password/server): {client}")
        return False

    ok = mt5.initialize(path=MT5_PATH, login=login, password=password, server=server)

    if not ok:
        print(f"❌ Failed to connect client {login} | MT5 ERROR: {mt5.last_error()}")
        return False

    acc = mt5.account_info()
    if acc is None:
        print(f"❌ Connected but account_info() is None for {login} | MT5 ERROR: {mt5.last_error()}")
        return False

    print(f"✅ Connected client {acc.login} | Server: {acc.server} | Balance: {acc.balance}")
    return True


def shutdown_client():
    try:
        mt5.shutdown()
    except Exception:
        pass


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


def symbol_ready(symbol: str) -> bool:
    """
    ✅ Hard readiness checks:
    - symbol exists & selectable
    - trading enabled
    - has valid tick (bid/ask > 0)
    """
    symbol = str(symbol).strip()

    if not ensure_symbol(symbol):
        print(f"⛔ symbol_select failed for {symbol} | MT5 ERROR: {mt5.last_error()}")
        return False

    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"⛔ symbol_info None for {symbol}")
        return False

    if int(getattr(info, "trade_mode", mt5.SYMBOL_TRADE_MODE_DISABLED)) == mt5.SYMBOL_TRADE_MODE_DISABLED:
        print(f"⛔ trading DISABLED on {symbol} for this account")
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"⛔ no tick for {symbol} | MT5 ERROR: {mt5.last_error()}")
        return False

    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid <= 0 or ask <= 0:
        print(f"⛔ invalid tick for {symbol} (bid/ask=0) — market closed or feed issue")
        return False

    return True


def _is_deriv_base(base_symbol: str) -> bool:
    return str(base_symbol).upper().strip() in set(DERIV_BASE_SYMBOLS)


# ------------------- Panic stop across all clients -------------------
def handle_global_panic_stop(clients: list):
    """
    If STOP.txt exists:
    - connect each active, non-expired client
    - close bot positions (magic), fallback close all
    - shutdown and exit
    """
    if not stop_requested():
        return

    print("🛑 STOP.txt detected — flattening ALL clients then stopping...")
    send_telegram("🛑 STOP.txt detected — flattening ALL clients then stopping...")

    for client in clients:
        try:
            if not client.get("active", True):
                continue
            expiry = client.get("expiry", "2099-12-31")
            if is_expired(expiry):
                continue

            if not connect_client(client):
                continue

            try:
                closed_magic = close_positions_by_magic(magic=DEFAULT_MAGIC)
                if closed_magic == 0:
                    close_all_positions()
                print(f"✅ STOP: client {client.get('login')} flattened")
            finally:
                shutdown_client()

        except Exception as e:
            print("⚠️ STOP error on a client:", e)
            shutdown_client()

    clear_stop_file()
    raise SystemExit("Bot stopped by STOP.txt")


# ------------------- Signal Snapshot -------------------
def build_signal_snapshot(source_symbol_map: dict, base_symbols: list, tf_signal):
    """
    Compute bias+signal ONCE using a single connected account as the data source.
    Store result keyed by BASE symbol.

    ✅ NEW:
    - For DERIV bases (STEP/V10/V75): bypass dual-bias requirement (final_bias="DERIV")
      because synthetics strategy is self-contained (Trend+SMC) and 24/7.
    """
    snapshot = {}

    for base in base_symbols:
        data_symbol = source_symbol_map.get(base, base)

        try:
            if not symbol_ready(data_symbol):
                snapshot[base] = {"signal": "NONE", "final_bias": None, "h4": None, "h1": None}
                continue

            # ✅ Deriv: no session gating + no dual-bias gating (keeps FX logic untouched)
            if _is_deriv_base(base):
                sig = get_signal(data_symbol, timeframe=tf_signal)
                s = str(sig).upper().strip() if sig else "NONE"
                snapshot[base] = {
                    "signal": s,
                    "final_bias": "DERIV",
                    "h4": None,
                    "h1": None,
                }
                continue

            # ✅ FX/Crypto: dual bias gating
            final_bias, h4_bias, h1_bias = get_dual_bias(
                data_symbol,
                primary_tf=PRIMARY_BIAS_TF,
                confirm_tf=CONFIRM_BIAS_TF,
                primary_stable=PRIMARY_STABLE_BARS,
                confirm_stable=CONFIRM_STABLE_BARS,
            )

            sig = get_signal(data_symbol, timeframe=tf_signal)
            s = str(sig).upper().strip() if sig else "NONE"

            snapshot[base] = {
                "signal": s,
                "final_bias": final_bias,
                "h4": h4_bias,
                "h1": h1_bias,
            }

        except Exception as e:
            snapshot[base] = {"signal": "NONE", "final_bias": None, "h4": None, "h1": None, "err": str(e)}

    return snapshot


def union_all_pairs(clients: list) -> list:
    """
    Union of all pairs across all clients so snapshot covers everything any client may trade.

    ✅ NEW:
    - Ensures DERIV symbols appear in the snapshot if any client allows them.
    """
    s = set()
    for c in clients:
        if not c.get("active", True):
            continue
        expiry = c.get("expiry", "2099-12-31")
        if is_expired(expiry):
            continue
        for p in get_client_pairs(c):
            s.add(str(p).upper().strip())

    ordered = []

    # stable ordering: FX/Crypto first, then Deriv
    for p in DEFAULT_BASE_SYMBOLS:
        if p in s and p not in ordered:
            ordered.append(p)

    for p in DERIV_BASE_SYMBOLS:
        if p in s and p not in ordered:
            ordered.append(p)

    # include any extras (unknown) for safety
    for p in sorted(s):
        if p and p not in ordered:
            ordered.append(p)

    return ordered


# ------------------- Main -------------------
def main():
    print("🚀 MT5 SaaS Multi-Client Bot Starting (Signal Snapshot mode)...")

    while True:
        try:
            clients = load_clients(CLIENTS_FILE)

            # STOP should be able to flatten everyone
            handle_global_panic_stop(clients)

            session = get_current_session()
            print(f"🕒 Current Session: {session}")

            snapshot_pairs = union_all_pairs(clients)
            if not snapshot_pairs:
                print("⚠️ No active, non-expired clients found.")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            # ✅ If outside FX sessions, we still run if there are DERIV pairs in snapshot
            has_deriv = any(_is_deriv_base(p) for p in snapshot_pairs)
            if session is None and not has_deriv:
                print("⛔ Outside trading sessions (no DERIV pairs enabled) — heartbeat only")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            if session is None and has_deriv:
                print("🧪 Outside FX sessions but DERIV pairs enabled — running DERIV only this heartbeat")

            # -----------------------------
            # 1) CONNECT ONE SOURCE CLIENT
            # -----------------------------
            source_client = None
            for c in clients:
                if not c.get("active", True):
                    continue
                expiry = c.get("expiry", "2099-12-31")
                if is_expired(expiry):
                    continue
                source_client = c
                break

            if source_client is None:
                print("⚠️ No active, non-expired clients available.")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            if not connect_client(source_client):
                print("⚠️ Could not connect source client for snapshot. Retrying next heartbeat...")
                shutdown_client()
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            try:
                acc = mt5.account_info()
                if acc is None:
                    print("⚠️ Source account_info() failed.")
                    time.sleep(HEARTBEAT_INTERVAL)
                    continue

                source_symbol_map = get_symbol_map(snapshot_pairs, login=acc.login, server=acc.server)

                # -----------------------------
                # 2) BUILD SNAPSHOT ONCE
                # -----------------------------
                snapshot = build_signal_snapshot(source_symbol_map, snapshot_pairs, tf_signal=SIGNAL_TF)

                for base in snapshot_pairs:
                    row = snapshot.get(base, {})
                    if _is_deriv_base(base):
                        print(f"[SNAPSHOT] {base} | DERIV | Signal(H1)={row.get('signal')}")
                    else:
                        print(
                            f"[SNAPSHOT] {base} | Bias(H4/H1)={row.get('h4')}/{row.get('h1')} -> {row.get('final_bias')} "
                            f"| Signal(H1)={row.get('signal')}"
                        )

            finally:
                shutdown_client()

            # -----------------------------
            # 3) EXECUTE SNAPSHOT FOR ALL CLIENTS
            # -----------------------------
            for client in clients:
                try:
                    handle_global_panic_stop(clients)

                    if not client.get("active", True):
                        continue

                    expiry = client.get("expiry", "2099-12-31")
                    if is_expired(expiry):
                        print(f"⛔ Client {client.get('login')} expired ({expiry}) — skipping")
                        continue

                    if not connect_client(client):
                        continue

                    try:
                        acc = mt5.account_info()
                        if acc is None:
                            print("❌ Can't read account info")
                            continue

                        client_pairs = get_client_pairs(client)
                        dd_limit_pct = get_client_dd_limit_pct(client)
                        print(f"📌 Client {acc.login} allowed pairs: {client_pairs} | DD limit: {dd_limit_pct}%")

                        # ✅ DD protection per client
                        if not allowed(dd_limit_pct=dd_limit_pct, login=acc.login):
                            print(f"⛔ DD protection active for client {acc.login} (limit={dd_limit_pct}%) — skipping")
                            continue

                        # manage open positions (profit lock + close notifications)
                        manage_open_positions()

                        # map symbols for this client
                        symbol_map = get_symbol_map(client_pairs, login=acc.login, server=acc.server)

                        for base_symbol in client_pairs:
                            handle_global_panic_stop(clients)

                            base_symbol_u = str(base_symbol).upper().strip()

                            # ✅ If outside FX sessions, skip FX/Crypto, allow DERIV only
                            if session is None and not _is_deriv_base(base_symbol_u):
                                continue

                            # ✅ FX-only session block
                            if (
                                    session is not None
                                    and BLOCK_XAU_LONDON
                                    and session == "LONDON"
                                    and base_symbol_u == "XAUUSD"
                            ):
                                print("⛔ XAUUSD blocked during LONDON — skipping")
                                continue

                            decision = snapshot.get(base_symbol_u, None)
                            if not decision:
                                continue

                            final_bias = decision.get("final_bias")
                            sig = decision.get("signal", "NONE")

                            # ✅ Gating:
                            # - DERIV: final_bias == "DERIV"
                            # - FX/Crypto: final_bias must be BULL/BEAR
                            if _is_deriv_base(base_symbol_u):
                                if final_bias != "DERIV":
                                    continue
                            else:
                                if final_bias is None:
                                    continue

                            if sig not in ("BUY", "SELL"):
                                continue

                            broker_symbol = symbol_map.get(base_symbol_u, base_symbol_u)

                            if not symbol_ready(broker_symbol):
                                print(f"⛔ {acc.login} not ready for {base_symbol_u}({broker_symbol}) — skipped")
                                continue

                            # ✅ Re-check DD mid-run with this client's limit
                            if not allowed(dd_limit_pct=dd_limit_pct, login=acc.login):
                                print(
                                    f"⛔ DD protection hit mid-run for client {acc.login} "
                                    f"(limit={dd_limit_pct}%) — blocking further trades"
                                )
                                break

                            execute_trade(
                                base_symbol=base_symbol_u,
                                symbol=broker_symbol,
                                signal=sig,
                                client_login=acc.login,
                                server=acc.server,
                                session=session,  # can be None for DERIV; trade_manager handles safely
                            )

                    finally:
                        shutdown_client()

                except Exception as e:
                    print("⚠️ Client loop error:", e)
                    shutdown_client()

            print("BOT HEARTBEAT RUNNING...")
            time.sleep(HEARTBEAT_INTERVAL)

        except SystemExit as e:
            print(str(e))
            return

        except Exception as e:
            print("⚠️ MAIN LOOP ERROR:", e)
            time.sleep(10)


if __name__ == "__main__":
    main()