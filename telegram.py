# telegram.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_API_KEY", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def send_telegram(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram not configured. Missing TELEGRAM_API_KEY or TELEGRAM_CHAT_ID in .env")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print("❌ Telegram send failed:", r.status_code, r.text)
            return False

        print("✅ Telegram message sent successfully")
        return True

    except Exception as e:
        print("❌ Telegram error:", e)
        return False