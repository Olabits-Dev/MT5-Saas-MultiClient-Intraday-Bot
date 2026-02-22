import os
import csv
from datetime import datetime, timezone


LOG_DIR = "logs"
TRADE_LOG_FILE = os.path.join(LOG_DIR, "trades.csv")


def ensure_log_file():
    os.makedirs(LOG_DIR, exist_ok=True)

    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_utc",
                "client_login",
                "server",
                "symbol",
                "signal",
                "lot",
                "price",
                "sl",
                "tp",
                "ticket",
                "retcode",
                "message"
            ])


def log_trade(
    client_login,
    server,
    symbol,
    signal,
    lot,
    price,
    sl,
    tp,
    ticket,
    retcode,
    message=""
):
    ensure_log_file()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with open(TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            ts,
            client_login,
            server,
            symbol,
            signal,
            lot,
            price,
            sl,
            tp,
            ticket,
            retcode,
            message
        ])
