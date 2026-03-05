import json
from cryptography.fernet import Fernet

# ==================================================
# IMPORTANT:
# This MUST be the same key used in decrypt_clients.py
# and stored in your .env
# ==================================================
FERNET_KEY = b"fCnx9bRy3Yq3NM98sG5FM7WqFRjoRySmlU8kPmfcs8I="

fernet = Fernet(FERNET_KEY)

CLIENTS_JSON = "clients.json"
CLIENTS_ENC = "clients.enc"

# Allowed base symbols (safety check)
KNOWN_SYMBOLS = {"BTCUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPJPY"}


def validate_clients(data):
    if not isinstance(data, list):
        raise ValueError("clients.json must contain a LIST of client objects")

    for i, client in enumerate(data, start=1):
        if not isinstance(client, dict):
            raise ValueError(f"Client #{i} is not an object")

        # Required fields
        for field in ("login", "password", "server"):
            if field not in client:
                raise ValueError(f"Client #{i} missing required field: {field}")

        # Optional: allowed_pairs
        if "allowed_pairs" in client:
            pairs = client["allowed_pairs"]
            if not isinstance(pairs, list):
                raise ValueError(f"Client #{i} allowed_pairs must be a list")

            cleaned = []
            for p in pairs:
                s = str(p).upper().strip()
                if s not in KNOWN_SYMBOLS:
                    raise ValueError(
                        f"Client #{i} has unknown symbol in allowed_pairs: {s}"
                    )
                cleaned.append(s)

            # Normalize + dedupe
            client["allowed_pairs"] = list(dict.fromkeys(cleaned))

    return data


def main():
    # ---------------- Read & validate JSON ----------------
    try:
        with open(CLIENTS_JSON, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        raise SystemExit(f"❌ Failed to read {CLIENTS_JSON}: {e}")

    try:
        validated = validate_clients(raw)
    except Exception as e:
        raise SystemExit(f"❌ Validation error: {e}")

    # Re-serialize (ensures normalized formatting)
    json_bytes = json.dumps(validated, indent=2).encode("utf-8")

    # ---------------- Encrypt ----------------
    encrypted = fernet.encrypt(json_bytes)

    with open(CLIENTS_ENC, "wb") as f:
        f.write(encrypted)

    print("✅ clients.enc created successfully!")
    print(f"🔒 Encrypted {len(validated)} client(s)")
    print("📌 allowed_pairs validated and normalized")


if __name__ == "__main__":
    main()