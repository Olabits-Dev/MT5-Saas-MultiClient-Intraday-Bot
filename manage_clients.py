from decrypt_clients import load_clients, save_clients
from datetime import datetime

FILE = "clients.enc"

# ✅ Keep this list aligned with your bot
KNOWN_SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPJPY", "STEP", "V10", "V75"]

# ✅ Default DD limit if client doesn't set custom
DEFAULT_DD_LIMIT_PCT = 5.0


# ---------- Helpers ----------
def _input_date(prompt: str, default: str = "2099-12-31") -> str:
    s = input(prompt).strip()
    if not s:
        return default
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        print("⚠️ Invalid date format. Using default:", default)
        return default


def _input_float(prompt: str, default: float) -> float:
    s = input(prompt).strip()
    if not s:
        return float(default)
    try:
        return float(s)
    except Exception:
        print("⚠️ Invalid number. Using default:", default)
        return float(default)


def _normalize_pairs(pairs):
    if not pairs:
        return []
    out = []
    for p in pairs:
        s = str(p).upper().strip()
        if s:
            out.append(s)
    # dedupe while preserving order
    return list(dict.fromkeys(out))


def _choose_allowed_pairs():
    """
    Per-client pair whitelist.
    - Empty = trade ALL (default behavior)
    - Otherwise select from KNOWN_SYMBOLS
    """
    print("\n--- Allowed Pairs Setup ---")
    print("Leave empty to allow ALL pairs (default).")
    print("Or select pairs by number separated by comma.")
    for i, s in enumerate(KNOWN_SYMBOLS, start=1):
        print(f"{i}. {s}")

    raw = input("Select (e.g. 1,3) or press Enter for ALL: ").strip()
    if not raw:
        return []  # empty means ALL

    picks = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            continue
        idx = int(part)
        if 1 <= idx <= len(KNOWN_SYMBOLS):
            picks.append(KNOWN_SYMBOLS[idx - 1])

    return _normalize_pairs(picks)


def _choose_dd_limit_pct(current: float | None = None) -> float | None:
    """
    Set per-client daily DD %.
    - Empty => use default (remove override)
    - Otherwise e.g. 0.5, 1, 2, 5
    """
    print("\n--- Daily DD Limit (%) ---")
    print(f"Default (bot fallback): {DEFAULT_DD_LIMIT_PCT}%")
    if current is not None:
        print(f"Current override: {current}%")

    raw = input("Enter DD limit % (e.g. 0.5) or press Enter to use DEFAULT: ").strip()
    if not raw:
        return None  # no override stored

    try:
        v = float(raw)
        if v <= 0:
            print("⚠️ DD must be > 0. Using DEFAULT (no override).")
            return None
        if v < 0.1:
            print("⚠️ Very low DD. Minimum allowed is 0.1%. Setting to 0.1%.")
            v = 0.1
        return float(v)
    except Exception:
        print("⚠️ Invalid DD value. Using DEFAULT (no override).")
        return None


# ---------- AUTO REPAIR / MIGRATION ----------
def normalize_client(c):
    print(f"\nChecking client {c.get('login')}...")

    if "name" not in c or not str(c.get("name", "")).strip():
        c["name"] = input(f"Enter name for account {c.get('login')}: ").strip() or f"Client-{c.get('login')}"

    if "login" not in c or not str(c.get("login", "")).strip():
        c["login"] = int(input("Enter MT5 Login: ").strip())

    if "password" not in c or not str(c.get("password", "")).strip():
        c["password"] = input(f"Enter MT5 password for {c['login']}: ").strip()

    if "server" not in c or not str(c.get("server", "")).strip():
        c["server"] = input(f"Enter MT5 server for {c['login']}: ").strip()

    if "expiry" not in c or not str(c.get("expiry", "")).strip():
        c["expiry"] = _input_date(f"Enter expiry date for {c['login']} (YYYY-MM-DD) or leave blank: ")

    if "active" not in c:
        c["active"] = True

    # ✅ allowed_pairs migration
    if "allowed_pairs" in c:
        c["allowed_pairs"] = _normalize_pairs(c.get("allowed_pairs"))
        c["allowed_pairs"] = [p for p in c["allowed_pairs"] if p in KNOWN_SYMBOLS]
        if len(c["allowed_pairs"]) == 0:
            # remove empty list => means ALL
            del c["allowed_pairs"]

    # ✅ dd_limit_pct migration (optional override)
    if "dd_limit_pct" in c:
        try:
            v = float(c["dd_limit_pct"])
            if v <= 0:
                del c["dd_limit_pct"]
            else:
                if v < 0.1:
                    v = 0.1
                c["dd_limit_pct"] = float(v)
        except Exception:
            del c["dd_limit_pct"]

    return c


def normalize_all(clients):
    return [normalize_client(c) for c in clients]


# ---------- DISPLAY ----------
def show_clients(clients):
    print("\n========== LICENSED CLIENTS ==========")
    for i, c in enumerate(clients):
        status = "ACTIVE" if c.get("active", True) else "DISABLED"
        expiry = c.get("expiry", "2099-12-31")
        name = c.get("name", "Unknown")
        login = c.get("login", "N/A")

        allowed_pairs = c.get("allowed_pairs", None)
        pairs_txt = ",".join(allowed_pairs) if allowed_pairs else "ALL"

        dd_override = c.get("dd_limit_pct", None)
        dd_txt = f"{dd_override}%" if dd_override is not None else f"DEFAULT({DEFAULT_DD_LIMIT_PCT}%)"

        print(f"{i+1}. {name} | Login: {login} | Expiry: {expiry} | {status} | Pairs: {pairs_txt} | DD: {dd_txt}")
    print("======================================\n")


# ---------- ADD ----------
def add_client(clients):
    print("\n--- ADD NEW CLIENT ---")

    name = input("Client Name: ").strip()
    login = int(input("MT5 Login: ").strip())
    password = input("MT5 Password: ").strip()
    server = input("MT5 Server: ").strip()
    expiry = _input_date("Expiry Date (YYYY-MM-DD) or leave blank: ")

    allowed_pairs = _choose_allowed_pairs()
    dd_override = _choose_dd_limit_pct(current=None)

    client = {
        "name": name if name else f"Client-{login}",
        "login": login,
        "password": password,
        "server": server,
        "expiry": expiry,
        "active": True,
    }

    # store only if restricted
    if allowed_pairs:
        client["allowed_pairs"] = allowed_pairs

    # store only if override
    if dd_override is not None:
        client["dd_limit_pct"] = dd_override

    clients.append(client)
    print("✅ Client added successfully")
    return clients


# ---------- REMOVE ----------
def remove_client(clients):
    show_clients(clients)
    raw = input("Enter client number to REMOVE: ").strip()
    if not raw.isdigit():
        print("Invalid selection")
        return clients

    index = int(raw) - 1
    if 0 <= index < len(clients):
        removed = clients.pop(index)
        print(f"❌ Removed {removed.get('login')}")
    else:
        print("Invalid selection")
    return clients


# ---------- DISABLE ----------
def disable_client(clients):
    show_clients(clients)
    raw = input("Enter client number to DISABLE: ").strip()
    if not raw.isdigit():
        print("Invalid selection")
        return clients

    index = int(raw) - 1
    if 0 <= index < len(clients):
        clients[index]["active"] = False
        print("⛔ Client disabled")
    else:
        print("Invalid selection")
    return clients


# ---------- ACTIVATE ----------
def activate_client(clients):
    show_clients(clients)
    raw = input("Enter client number to ACTIVATE: ").strip()
    if not raw.isdigit():
        print("Invalid selection")
        return clients

    index = int(raw) - 1
    if 0 <= index < len(clients):
        clients[index]["active"] = True
        print("✅ Client activated")
    else:
        print("Invalid selection")
    return clients


# ---------- EDIT ALLOWED PAIRS ----------
def edit_allowed_pairs(clients):
    show_clients(clients)
    raw = input("Enter client number to EDIT PAIRS: ").strip()
    if not raw.isdigit():
        print("Invalid selection")
        return clients

    index = int(raw) - 1
    if not (0 <= index < len(clients)):
        print("Invalid selection")
        return clients

    c = clients[index]
    print(f"\nEditing pairs for {c.get('name')} | login={c.get('login')}")
    new_pairs = _choose_allowed_pairs()

    if new_pairs:
        c["allowed_pairs"] = new_pairs
        print("✅ Updated allowed_pairs:", ",".join(new_pairs))
    else:
        if "allowed_pairs" in c:
            del c["allowed_pairs"]
        print("✅ Updated allowed_pairs: ALL")

    clients[index] = c
    return clients


# ---------- EDIT DD LIMIT ----------
def edit_dd_limit(clients):
    show_clients(clients)
    raw = input("Enter client number to EDIT DD LIMIT: ").strip()
    if not raw.isdigit():
        print("Invalid selection")
        return clients

    index = int(raw) - 1
    if not (0 <= index < len(clients)):
        print("Invalid selection")
        return clients

    c = clients[index]
    cur = c.get("dd_limit_pct", None)
    print(f"\nEditing DD limit for {c.get('name')} | login={c.get('login')}")

    new_dd = _choose_dd_limit_pct(current=cur)

    if new_dd is None:
        if "dd_limit_pct" in c:
            del c["dd_limit_pct"]
        print(f"✅ DD limit set to DEFAULT({DEFAULT_DD_LIMIT_PCT}%)")
    else:
        c["dd_limit_pct"] = float(new_dd)
        print(f"✅ DD limit override set to {new_dd}%")

    clients[index] = c
    return clients


# ---------- MAIN MENU ----------
def main():
    clients = load_clients(FILE)
    clients = normalize_all(clients)

    while True:
        print("""
1. Show Clients
2. Add Client
3. Remove Client
4. Disable Client
5. Activate Client
6. Edit Allowed Pairs (BTCUSD/EURUSD only etc.)
7. Edit Daily DD Limit (e.g. 0.5%)
8. Save & Exit
""")

        choice = input("Select: ").strip()

        if choice == "1":
            show_clients(clients)

        elif choice == "2":
            clients = add_client(clients)

        elif choice == "3":
            clients = remove_client(clients)

        elif choice == "4":
            clients = disable_client(clients)

        elif choice == "5":
            clients = activate_client(clients)

        elif choice == "6":
            clients = edit_allowed_pairs(clients)

        elif choice == "7":
            clients = edit_dd_limit(clients)

        elif choice == "8":
            save_clients(FILE, clients)
            print("💾 Saved successfully")
            break

        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()