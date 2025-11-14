# core/ai_sizer_summary.py
# ============================================================
# core/ai_sizer_summary.py — AI dydžio ir portfelio santrauka
# ------------------------------------------------------------
# Naudojama /api/ai_sizer endpoint'e dashboard'e
# ============================================================

import statistics
import logging
from core.config import CONFIG
from core.paper_account import get_state
from ai.ai_signals import get_trade_signals


def get_ai_sizer_summary() -> dict:
    """
    Grąžina AI dydžio, volatility ir portfelio užimtumo santrauką.
    Naudojama dashboard'e kortelei "🧠 AI Dydis / Boost".
    """
    try:
        # ✅ PATAISYTA: Naudoti CONFIG tiesiogiai, ne .all()
        cfg = CONFIG  # buvo: cfg = CONFIG.all()
        state = get_state()

        # 1️⃣ Config parametrai
        ai_cfg = cfg.get("AI_SIZER", {})
        min_trade_usdc = float(ai_cfg.get("MIN_TRADE_USDC", 25))
        max_trade_usdc = float(ai_cfg.get("MAX_TRADE_USDC", 500))
        max_positions = int(cfg.get("PORTFOLIO", {}).get("MAX_OPEN_POSITIONS", cfg.get("MAX_OPEN_POSITIONS", 8)))

        # 2️⃣ Dabartinė sąskaitos būsena
        positions = state.get("positions", {})
        open_positions = len(positions)
        used_usdc = float(state.get("used_usdc", 0))
        equity = float(state.get("equity", 10000))
        portfolio_usage_pct = round((used_usdc / equity) * 100 if equity > 0 else 0, 2)

        # 3️⃣ Vidutiniai AI signalų rodikliai (boost ir volatility)
        try:
            signals = get_trade_signals()
            boosts = [s.get("confidence", 0) for s in signals if s.get("confidence") is not None]
            vols = [abs(s.get("edge", 0)) * 10000 for s in signals if s.get("edge") is not None]
            boost_avg = round(statistics.mean(boosts), 3) if boosts else 0.0
            vol_avg = round(statistics.mean(vols), 3) if vols else 0.0
        except Exception:
            boost_avg = 0.0
            vol_avg = 0.0

        # ✅ Galutinė struktūra dashboard'ui
        return {
            "boost_avg": boost_avg,
            "vol_avg": vol_avg,
            "min_trade_usdc": min_trade_usdc,
            "max_trade_usdc": max_trade_usdc,
            "max_positions": max_positions,
            "open_positions": open_positions,
            "portfolio_usage_pct": portfolio_usage_pct
        }

    except Exception as e:
        logging.warning(f"[AI-SIZER] Klaida renkant santrauką: {e}")
        return {
            "boost_avg": 0.0,
            "vol_avg": 0.0,
            "min_trade_usdc": 0.0,
            "max_trade_usdc": 0.0,
            "max_positions": 0,
            "open_positions": 0,
            "portfolio_usage_pct": 0.0
        }