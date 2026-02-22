import MetaTrader5 as mt5

# Cache so we don’t scan symbols every loop
_SYMBOL_MAP_CACHE = {}  # {(login, server): {"EURUSD": "EURUSDm", ...}}


def _best_candidate(base: str, names: set[str]) -> str | None:
    # 1) Exact match
    if base in names:
        return base

    # 2) Common suffix match: EURUSDm, EURUSD.i, EURUSD-ECN
    starts = [n for n in names if n.startswith(base)]
    if starts:
        starts.sort(key=len)
        return starts[0]

    # 3) Some brokers use separators: EURUSD.m, EURUSD_i, EURUSD# etc.
    sep_candidates = [n for n in names if n.replace(".", "").replace("_", "").replace("-", "").startswith(base)]
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
    Example: "EURUSD" -> "EURUSDm" if that exists, otherwise "EURUSD".
    """

    all_syms = mt5.symbols_get()
    if all_syms is None:
        mapping = {s: s for s in base_symbols}
        if cache_key is not None:
            _SYMBOL_MAP_CACHE[cache_key] = mapping
        return mapping

    names = {s.name for s in all_syms}

    mapping = {}
    for base in base_symbols:
        cand = _best_candidate(base, names)
        mapping[base] = cand if cand else base

    if cache_key is not None:
        _SYMBOL_MAP_CACHE[cache_key] = mapping

    return mapping


def get_symbol_map(base_symbols, login=None, server=None):
    key = (login, server)
    if login and server and key in _SYMBOL_MAP_CACHE:
        return _SYMBOL_MAP_CACHE[key]
    return build_symbol_map(base_symbols, cache_key=key if login and server else None)
