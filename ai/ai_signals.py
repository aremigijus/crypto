# ============================================================
# ai/ai_signals.py — Realūs AI signalai iš Binance (be generacijos)
# Test režimu sąlygos švelnesnės, kad botas aktyviai reaguotų
# ============================================================

import logging
from datetime import datetime, timezone
from core.config import CONFIG
from core.exchange_adapter import get_adapter


def get_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = prices[-i] - prices[-i - 1]
        (gains if delta >= 0 else losses).append(abs(delta))
    avg_gain = sum(gains) / period if gains else 0.01
    avg_loss = sum(losses) / period if losses else 0.01
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_ma(prices, n=20):
    if len(prices) < n:
        return sum(prices) / len(prices)
    return sum(prices[-n:]) / n


def get_trade_signals(symbol):
    """
    Naudoja realius Binance duomenis — tiek TEST, tiek LIVE režimu.
    TEST režime sąlygos laisvesnės, kad matytume pirkimų logiką.
    """
    try:
        adapter = get_adapter()
        klines = adapter.get_klines(symbol, interval="5m", limit=80)
        if not klines:
            logging.warning(f"[AI-SIGNALS] ⚠️ Negauta klinių {symbol}")
            return []

        closes = [float(k["close"]) for k in klines]
        price = closes[-1]
        ma = get_ma(closes, 20)
        rsi = get_rsi(closes, 14)

        signal = None
        conf = 0.0
        edge = 0.0

        mode = CONFIG.get("MODE", "").upper()
        # testavimui – šiek tiek jautresni filtrai
        rsi_buy_thr = 72 if mode == "LIVE" else 80
        rsi_sell_thr = 28 if mode == "LIVE" else 20

        # Paprasta logika
        if price > ma * 1.001 and rsi < rsi_buy_thr:
            signal = "BUY"
            conf = min(0.95, (70 - rsi) / 100 + 0.6)
            edge = (price - ma) / ma
        elif price < ma * 0.999 and rsi > rsi_sell_thr:
            signal = "SELL"
            conf = min(0.95, (rsi - 30) / 100 + 0.6)
            edge = (ma - price) / ma

        if signal:
            logging.info(
                f"[AI-REAL] 📊 {symbol}: {signal} | RSI={rsi:.1f} | MA={ma:.2f} | "
                f"price={price:.2f} | conf={conf:.2f} | edge={edge:.4f}"
            )
            return [{
                "symbol": symbol,
                "direction": signal,
                "confidence": round(conf, 3),
                "edge": round(edge, 5),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        else:
            logging.debug(f"[AI-REAL] {symbol}: nėra signalo (RSI={rsi:.1f}, MA={ma:.2f}, price={price:.2f})")
            return []

    except Exception as e:
        logging.error(f"[AI-SIGNALS] Klaida apdorojant {symbol}: {e}")
        return []
