# =========================
# SESSION FILTER (UTC) - PRIORITY HANDLING
# =========================

from datetime import datetime, time, timezone

# UTC session times
ASIAN_START = time(0, 0)
ASIAN_END   = time(9, 0)

LONDON_START = time(7, 0)
LONDON_END   = time(16, 0)

NY_START = time(12, 0)
NY_END   = time(21, 0)


def get_current_session():
    """
    Returns one of: "ASIAN", "LONDON", "NEWYORK", or None.
    Handles overlaps by priority:
    NEWYORK > LONDON > ASIAN
    """
    now = datetime.now(timezone.utc).time()

    # ✅ Priority order for overlaps
    if NY_START <= now <= NY_END:
        return "NEWYORK"

    if LONDON_START <= now <= LONDON_END:
        return "LONDON"

    if ASIAN_START <= now <= ASIAN_END:
        return "ASIAN"

    return None
