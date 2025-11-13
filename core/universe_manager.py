import time
import math
import requests
from typing import List, Dict, Tuple
from core.config import CONFIG

BINANCE_REST_MAIN = "https://api.binance.com"
TIMEOUT = 5

def _fetch_24h() -> list:
    r = requests.get(f"{BINANCE_REST_MAIN}/api/v3/ticker/24hr", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _score_row(t: dict) -> float:
    try:
        vol_usdc = float(t.get("quoteVolume", 0) or 0.0)
        price_change = abs(float(t.get("priceChangePercent", 0) or 0.0))
        trades = float(t.get("count", 0) or 0.0)
        return (vol_usdc / 1_000_000.0) + (trades / 10_000.0) - (price_change / 100.0)
    except Exception:
        return 0.0

def select_universe() -> List[str]:
    base_quote = CONFIG.get("BASE_QUOTE", "USDC").upper()
    min_liq = float(CONFIG.get("MIN_LIQUIDITY_USDC", 0) or 0.0)
    max_spread_bps = float(CONFIG.get("MAX_SPREAD_BPS", 10) or 10)
    limit = int(CONFIG.get("TOP_USDC_LIMIT", 40) or 40)

    data = _fetch_24h()
    rows: List[Tuple[str, float]] = []
    for t in data:
        sym = str(t.get("symbol", "")).upper()
        if not sym.endswith(base_quote):
            continue
        try:
            vol_usdc = float(t.get("quoteVolume", 0) or 0.0)
            if vol_usdc < min_liq:
                continue
            score = _score_row(t)
            rows.append((sym, score))
        except Exception:
            pass
    rows.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in rows[:limit]]
