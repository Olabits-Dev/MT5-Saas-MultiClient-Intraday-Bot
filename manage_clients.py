from decrypt_clients import load_clients, save_clients

FILE = "clients.enc"


# ---------- AUTO REPAIR / MIGRATION ----------
def normalize_client(c):
    print(f"\nChecking client {c.get('login')}...")

    if "name" not in c:
        c["name"] = input(f"Enter name for account {c['login']}: ")

    if "password" not in c:
        c["password"] = input(f"Enter MT5 password for {c['login']}: ")

    if "server" not in c:
        c["server"] = input(f"Enter MT5 server for {c['login']}: ")

    if "expiry" not in c:
        expiry = input(f"Enter expiry date for {c['login']} (YYYY-MM-DD) or leave blank: ")
        c["expiry"] = expiry if expiry else "2099-12-31"

    if "active" not in c:
        c["active"] = True

    return c


def normalize_all(clients):
    fixed = []
    for c in clients:
        fixed.append(normalize_client(c))
    return fixed


# ---------- DISPLAY ----------
def show_clients(clients):
    print("\n========== LICENSED CLIENTS ==========")
    for i, c in enumerate(clients):
        status = "ACTIVE" if c.get("active", True) else "DISABLED"
        print(f"{i+1}. {c['name']} | Login: {c['login']} | Expiry: {c['expiry']} | {status}")
    print("======================================\n")


# ---------- ADD ----------
def add_client(clients):
    print("\n--- ADD NEW CLIENT ---")

    name = input("Client Name: ")
    login = int(input("MT5 Login: "))
    password = input("MT5 Password: ")
    server = input("MT5 Server: ")
    expiry = input("Expiry Date (YYYY-MM-DD): ")

    clients.append({
        "name": name,
        "login": login,
        "password": password,
        "server": server,
        "expiry": expiry if expiry else "2099-12-31",
        "active": True
    })

    print("✅ Client added successfully")
    return clients


# ---------- REMOVE ----------
def remove_client(clients):
    show_clients(clients)
    index = int(input("Enter client number to REMOVE: ")) - 1

    if 0 <= index < len(clients):
        removed = clients.pop(index)
        print(f"❌ Removed {removed['login']}")
    else:
        print("Invalid selection")

    return clients


# ---------- DISABLE ----------
def disable_client(clients):
    show_clients(clients)
    index = int(input("Enter client number to DISABLE: ")) - 1

    if 0 <= index < len(clients):
        clients[index]["active"] = False
        print("⛔ Client disabled")
    else:
        print("Invalid selection")

    return clients


# ---------- ACTIVATE ----------
def activate_client(clients):
    show_clients(clients)
    index = int(input("Enter client number to ACTIVATE: ")) - 1

    if 0 <= index < len(clients):
        clients[index]["active"] = True
        print("✅ Client activated")
    else:
        print("Invalid selection")

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
6. Save & Exit
""")

        choice = input("Select: ")

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
            save_clients(FILE, clients)
            print("💾 Saved successfully")
            break

        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()
