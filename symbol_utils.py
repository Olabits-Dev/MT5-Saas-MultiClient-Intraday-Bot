import MetaTrader5 as mt5

# Cache so we don’t scan symbols every loop
_SYMBOL_MAP_CACHE = {}  # {(login, server): {"EURUSD": "EURUSDm", ...}}

# ✅ Deriv Synthetic indices explicit mapping (exact MT5 names)
DERIV_MAP = {
    "STEP": "Step Index",
    "V10": "Volatility 10 Index",
    "V75": "Volatility 75 Index",
}


def _best_candidate(base: str, names: set[str]) -> str | None:
    """
    Picks the best broker symbol candidate for a given base symbol.
    """

    # 1) Exact match
    if base in names:
        return base

    # 2) Common suffix match: EURUSDm, EURUSD.i, EURUSD-ECN
    starts = [n for n in names if n.startswith(base)]
    if starts:
        starts.sort(key=len)
        return starts[0]

    # 3) Some brokers use separators: EURUSD.m, EURUSD_i, EURUSD# etc.
    sep_candidates = [
        n for n in names
        if n.replace(".", "").replace("_", "").replace("-", "").startswith(base)
    ]
    if sep_candidates:
        sep_candidates.sort(key=len)
        return sep_candidates[0]

    # 4) Very rare: base occurs in middle (prefix added)
    contains = [n for n in names if base in n]
    if contains:
        contains.sort(key=len)
        return contains[0]

    return None


def build_symbol_map(base_symbols, cache_key=None):
    """
    Finds the broker’s actual symbol names for each base symbol.

    ✅ NEW:
    - If base symbol is a Deriv synthetic alias (STEP/V10/V75),
      it maps directly to the exact MT5 name from DERIV_MAP.
      No suffix guessing is used for synthetics.
    """

    # Normalize base_symbols safely
    base_symbols = [str(s).upper().strip() for s in (base_symbols or []) if str(s).strip()]

    all_syms = mt5.symbols_get()
    if all_syms is None:
        # fallback: map to self or deriv map
        mapping = {}
        for base in base_symbols:
            if base in DERIV_MAP:
                mapping[base] = DERIV_MAP[base]
            else:
                mapping[base] = base
        if cache_key is not None:
            _SYMBOL_MAP_CACHE[cache_key] = mapping
        return mapping

    names = {s.name for s in all_syms}

    mapping = {}
    for base in base_symbols:
        # ✅ Deriv explicit mapping first
        if base in DERIV_MAP:
            target = DERIV_MAP[base]
            # If broker actually has it, use it. If not, fall back to candidate search.
            if target in names:
                mapping[base] = target
                continue
            # Sometimes broker may add suffix to synthetic name; try "starts with" match on full target text
            starts = [n for n in names if n.startswith(target)]
            if starts:
                starts.sort(key=len)
                mapping[base] = starts[0]
                continue
            # Last resort: attempt candidate search using base alias
            cand = _best_candidate(base, names)
            mapping[base] = cand if cand else target
            continue

        # Normal FX/Crypto resolution
        cand = _best_candidate(base, names)
        mapping[base] = cand if cand else base

    if cache_key is not None:
        _SYMBOL_MAP_CACHE[cache_key] = mapping

    return mapping


def get_symbol_map(base_symbols, login=None, server=None):
    """
    Returns cached map if available.
    """
    key = (login, server)
    if login and server and key in _SYMBOL_MAP_CACHE:
        return _SYMBOL_MAP_CACHE[key]
    return build_symbol_map(base_symbols, cache_key=key if login and server else None)