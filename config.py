import MetaTrader5 as mt5

# ============================================================
# CORE SYMBOLS (BASE symbols - your symbol_utils maps to EURUSDm etc)
# ============================================================
BASE_SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPJPY"]

# If any old module still imports SYMBOLS, keep alias:
SYMBOLS = BASE_SYMBOLS


# ============================================================
# TIMEFRAMES (NEW BOT RULE)
# - M15 = trigger signals
# - H1  = directional bias across sessions (replaces H4 bias)
# ============================================================
TRIGGER_TIMEFRAME = mt5.TIMEFRAME_M15
BIAS_TIMEFRAME = mt5.TIMEFRAME_H1


# ============================================================
# BOT IDENTIFIER (must match trade_manager DEFAULT_MAGIC)
# ============================================================
MAGIC_NUMBER = 777777


# ============================================================
# RISK / LOT SIZING
# You are using balance-tier lot sizing (Option B),
# so risk% is not used right now; keep for future modules.
# ============================================================
RISK_PERCENT = 1.0


# ============================================================
# STRATEGY BEHAVIOR
# ============================================================
RR = 5
NO_HEDGE = True

# Default stacking rules (London/NY can stack, Asia won't)
MAX_POSITIONS_PER_DIRECTION = 2

# Session-specific behavior
ASIA_USE_BIAS_FILTER = True      # B: Asia trades only with bias
ASIA_ALLOW_STACKING = False      # C: No stacking in Asia
ASIA_MAX_POSITIONS_PER_SYMBOL = 1  # extra safety: only 1 position per symbol in Asia


# ============================================================
# SYMBOL-SPECIFIC POSITION CAPS
# (Requested: XAUUSD should not exceed 1 open position)
# NOTE: This is per-symbol TOTAL cap (BUY+SELL combined, because we no-hedge)
# ============================================================
MAX_TOTAL_POSITIONS_PER_SYMBOL = {
    "XAUUSD": 1,     # ✅ special rule
    "BTCUSD": 2,
    "EURUSD": 2,
    "USDJPY": 2,
    "GBPJPY": 2,
}


# ============================================================
# STOP DISTANCE CONFIG
# (Used only if your trade_manager is in PIPS mode for FX)
# Your current trade_manager uses:
# - BTCUSD/XAUUSD -> ATR-based SL/TP
# - FX -> pips-mode SL/TP (sl_pips * point)
# So we keep only FX pips config here.
# ============================================================
FX_PIPS_CONFIG = {
    "EURUSD": {"sl_pips": 300},
    "USDJPY": {"sl_pips": 350},
    "GBPJPY": {"sl_pips": 450},
}

# Optional: if you later want fallback pips for BTC/XAU, you can set here:
CRYPTO_METAL_FALLBACK_PIPS = {
    "BTCUSD": {"sl_pips": 5000},
    "XAUUSD": {"sl_pips": 1500},
}


# ============================================================
# SESSION WINDOWS (UTC) - only if any module uses it
# Your bot mainly relies on session_filter.py; keep optional.
# ============================================================
SESSION_STARTS = [
    (0, 6),    # ASIAN
    (7, 11),   # LONDON
    (13, 17),  # NEWYORK
]


# ============================================================
# BREAK EVEN / PROFIT LOCK (only if position_manager uses these)
# You requested:
# - BE can trigger before H1 candle closes at ~1:2 RR
# - when 1:3 RR achieved -> lock 1:2 RR profit
#
# These values are expressed in RR multiples (not pips).
# Your position_manager should compute current RR and act.
# ============================================================
ENABLE_RR_BASED_BE = True
BE_AT_RR = 2.0           # move SL to entry when >= 1:2 RR
LOCK_PROFIT_AT_RR = 3.0  # when >= 1:3 RR...
LOCK_TO_RR = 2.0         # ...lock at least 1:2 RR profit


# ============================================================
# LIMIT/POI ORDERS
# You said remove POI limit setup (it was spamming).
# Keep this OFF so main/trade_manager doesn’t scan POIs.
# ============================================================
ENABLE_POI_LIMITS = False
