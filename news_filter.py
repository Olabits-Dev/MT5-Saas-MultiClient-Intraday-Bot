# news_filter.py (TradingEconomics - News Avoidance Only)
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

import requests

TE_CREDENTIALS = os.getenv("TE_CREDENTIALS", "").strip()  # format: key:secret

# Block window
BLOCK_BEFORE = 30 * 60  # 30 mins before
BLOCK_AFTER  = 30 * 60  # 30 mins after

# Impact threshold (TE: Importance 1/2/3 => 3 = high)
HIGH_IMPORTANCE = 3

# Cache
_CACHE: Dict[str, Any] = {"ts": 0, "events": []}
CACHE_TTL = 120  # seconds

# Currency -> base symbols (match your base_symbol in trade_manager)
CURRENCY_BLOCK_MAP = {
    "USD": {"EURUSD", "USDJPY", "XAUUSD", "BTCUSD"},
    "GBP": {"GBPJPY"},
    "JPY": {"USDJPY", "GBPJPY"},
    "EUR": {"EURUSD"},
}

# Country -> Currency fallback (when TE Currency field is blank)
# (Keep it focused on what you trade)
COUNTRY_TO_CCY = {
    "UNITED STATES": "USD",
    "US": "USD",
    "U.S.": "USD",

    "UNITED KINGDOM": "GBP",
    "UK": "GBP",
    "BRITAIN": "GBP",

    "JAPAN": "JPY",

    "EURO AREA": "EUR",
    "EUROZONE": "EUR",
    "GERMANY": "EUR",
    "FRANCE": "EUR",
    "ITALY": "EUR",
    "SPAIN": "EUR",
    "NETHERLANDS": "EUR",
    "ECB": "EUR",  # sometimes appears in country-like field
}


def _now_ts() -> int:
    return int(time.time())


def _ymd_utc(ts: Optional[int] = None) -> str:
    dt = datetime.fromtimestamp(ts or _now_ts(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _parse_te_date_to_ts(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    s = str(date_str).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _fetch_te_calendar(from_ymd: str, to_ymd: str) -> List[Dict[str, Any]]:
    if not TE_CREDENTIALS:
        return []

    url = "https://api.tradingeconomics.com/calendar"
    params = {"c": TE_CREDENTIALS, "d1": from_ymd, "d2": to_ymd, "format": "json"}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def get_events_cached(days_ahead: int = 7) -> List[Dict[str, Any]]:
    now = _now_ts()
    if (now - int(_CACHE["ts"])) < CACHE_TTL:
        return _CACHE["events"]

    d1 = _ymd_utc(now)
    d2 = _ymd_utc(now + days_ahead * 24 * 3600)

    # Don’t hide errors silently during real use; but keep bot running
    try:
        events = _fetch_te_calendar(d1, d2)
    except Exception as e:
        print(f"❌ TradingEconomics fetch failed: {e}")
        events = []

    _CACHE["ts"] = now
    _CACHE["events"] = events
    return events


def _get_event_ccy(ev: Dict[str, Any]) -> Optional[str]:
    ccy = ev.get("Currency")
    if ccy:
        c = str(ccy).strip().upper()
        if c:
            return c

    country = ev.get("Country") or ""
    c2 = COUNTRY_TO_CCY.get(str(country).strip().upper())
    return c2


def is_news_blocked(base_symbol: str) -> Tuple[bool, str]:
    base_symbol = str(base_symbol).upper().strip()
    now = _now_ts()

    events = get_events_cached(days_ahead=7)
    if not events:
        return False, ""

    for ev in events:
        # Importance
        try:
            imp = int(ev.get("Importance", 0) or 0)
        except Exception:
            continue
        if imp < HIGH_IMPORTANCE:
            continue

        # Currency (with fallback)
        ccy = _get_event_ccy(ev)
        if not ccy:
            continue

        blocked_symbols = CURRENCY_BLOCK_MAP.get(ccy, set())
        if base_symbol not in blocked_symbols:
            continue

        # Time
        t = _parse_te_date_to_ts(ev.get("Date") or "")
        if t is None:
            continue

        # Block window
        if (t - BLOCK_BEFORE) <= now <= (t + BLOCK_AFTER):
            title = str(ev.get("Event") or ev.get("Category") or "Economic event").strip()
            mins = int((t - now) / 60)
            when = f"in {mins} min" if mins >= 0 else f"{abs(mins)} min ago"
            return True, f"{ccy} HIGH impact: {title} ({when})"

    return False, ""


def debug_next_high_impact(limit: int = 10):
    """
    Helper to print the next high-impact events and what currency they map to.
    """
    now = _now_ts()
    events = get_events_cached(days_ahead=7)

    candidates = []
    for ev in events:
        try:
            imp = int(ev.get("Importance", 0) or 0)
        except Exception:
            continue
        if imp < HIGH_IMPORTANCE:
            continue

        t = _parse_te_date_to_ts(ev.get("Date") or "")
        if t is None or t < now:
            continue

        ccy = _get_event_ccy(ev) or ""
        title = str(ev.get("Event") or ev.get("Category") or "").strip()
        country = str(ev.get("Country") or "").strip()
        candidates.append((t, ccy, country, title, imp))

    candidates.sort(key=lambda x: x[0])
    for t, ccy, country, title, imp in candidates[:limit]:
        dt = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"- {dt} | imp={imp} | ccy={ccy or '??'} | country={country} | {title}")