# ============================================================
# ai/indicator_engine.py — Indikatorių pagrindu veikiantis AI signalų generatorius
# Atnaujinta: 2025-11-10 (Safe AI v6.5)
# ============================================================

import math
import logging
from typing import Dict, List
from core.config import CONFIG
from core.ws_bridge import get_price_history
from ai.ai_boost_layer import boost_signals

def _ema(values: List[float], period: int) -> float:
    if not values or len(values) < period: return values[-1] if values else 0.0
    k = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val

def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def _macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(closes) < slow + signal: return 0, 0, 0
    ema_fast = _ema(closes[-slow:], fast)
    ema_slow = _ema(closes[-slow:], slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema([macd_line for _ in range(signal)], signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def generate_signals() -> List[Dict]:
    """Sugeneruoja signalus ir taiko volatility boost."""
    signals = []
    universe = CONFIG.get("UNIVERSE", ["BTCUSDC", "ETHUSDC", "SOLUSDC"])
    base_quote = CONFIG.get("BASE_QUOTE", "USDC").upper()

    for sym in universe:
        if not sym.endswith(base_quote): continue
        try:
            ohlcv = get_price_history(sym, interval="1h", limit=100)
            if not ohlcv: continue
            closes = [float(x.get("close", 0)) for x in ohlcv]
            if len(closes) < 30: continue

            last_close, prev_close = closes[-1], closes[-2]
            change_pct = (last_close / prev_close - 1) * 100
            rsi_val = _rsi(closes, 14)
            macd_line, signal_line, hist = _macd(closes)
            ema_fast = _ema(closes[-20:], 9)
            ema_slow = _ema(closes[-50:], 50)
            ema_diff = (ema_fast / ema_slow - 1) * 100 if ema_slow else 0.0

            conf_rsi = 1.0 - abs(rsi_val - 50) / 50
            conf_trend = max(0.0, min(1.0, (ema_diff + 0.5) / 1.0))
            conf_macd = max(0.0, min(1.0, (hist + 1) / 2))
            confidence = 0.5 * conf_trend + 0.3 * conf_macd + 0.2 * conf_rsi
            edge = (ema_diff / 1000.0) + (hist / 100.0)

            if rsi_val < 35 and hist > 0 and ema_diff > 0:
                action = "BUY"
            elif rsi_val > 65 and hist < 0 and ema_diff < 0:
                action = "SELL"
            else:
                continue

            signals.append({
                "symbol": sym,
                "direction": action,
                "confidence": round(confidence, 3),
                "edge": round(edge, 4),
                "timestamp": ohlcv[-1].get("ts", "")
            })
        except Exception as e:
            logging.warning(f"[AI-ENGINE] Klaida {sym}: {e}")

    if not signals:
        logging.info("[AI-ENGINE] Nepavyko sugeneruoti signalų — per mažai duomenų?")
        return []

    return boost_signals(signals)
