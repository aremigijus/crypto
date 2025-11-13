# ============================================================
# ai/ai_tuner.py — Dieninis AI parametrų "tuningas" (DB-only)
# ------------------------------------------------------------
# Skaito rezultatus iš DB (trades) ir pateikia rekomendacijas
# (loguose). Nerašo į failus, nekeičia config tiesiogiai.
#
# Integracija su main:
#   from ai.ai_tuner import run_ai_tuner_daily
#   ... kas 24h -> run_ai_tuner_daily()
# ============================================================

from __future__ import annotations
import sqlite3
from datetime import datetime, timezone, timedelta
import logging
from statistics import mean

try:
    from core.db_manager import DB_PATH
except Exception:
    DB_PATH = "data/bot_data.db"


def _read_trades(days: int = 2):
    """Paima paskutinių N dienų uždarytus sandorius iš DB."""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        rows = cur.execute(
            """
            SELECT ts, pnl_pct, confidence
            FROM trades
            WHERE ts >= ? AND event='SELL'
            ORDER BY ts DESC
            """,
            (since,)
        ).fetchall()
        con.close()
        return rows
    except Exception as e:
        logging.error(f"[AI-TUNER] Klaida skaitant trades: {e}")
        return []


def run_ai_tuner_daily(days: int = 2) -> None:
    """
    Paprastas „tuneris“:
     - skaičiuoja win rate, avg pnl ir avg confidence per paskutines N dienų
     - išveda rekomendacijas loguose (pvz. koreguoti AI_CONFIDENCE_THRESHOLD)
    """
    rows = _read_trades(days=days)
    if not rows:
        logging.info("[AI-TUNER] Nėra pakankamai sandorių rekomendacijoms.")
        return

    pnl_list = [float(r[1] or 0.0) for r in rows]
    conf_list = [float(r[2] or 0.0) for r in rows]
    total = len(rows)
    wins = sum(1 for p in pnl_list if p > 0)
    win_rate = (wins * 100.0) / total if total > 0 else 0.0
    avg_pnl = mean(pnl_list) if pnl_list else 0.0
    avg_conf = mean(conf_list) if conf_list else 0.0

    # Rekomendacijos — konservatyvios, tik kaip gairės:
    # jei vidutinis confidence stipriai > 0.7, didinam slenkstį; jei < 0.5 — mažinam
    suggested_conf_thr = 0.7
    if avg_conf >= 0.8:
        suggested_conf_thr = 0.75
    elif avg_conf <= 0.5:
        suggested_conf_thr = 0.6

    # jei avg_pnl < 0, priveržti edge minimalų; jei > 0.2, galima atlaisvinti
    suggested_edge_min = 0.0015
    if avg_pnl < 0.0:
        suggested_edge_min = 0.0020
    elif avg_pnl > 0.2:
        suggested_edge_min = 0.0010

    logging.info(
        "[AI-TUNER] Per paskutines %dd: trades=%d | win_rate=%.2f%% | avg_pnl=%.4f%% | avg_conf=%.3f",
        days, total, win_rate, avg_pnl, avg_conf
    )
    logging.info(
        "[AI-TUNER] Rekomendacijos: AI_CONFIDENCE_THRESHOLD≈%.2f | EDGE_MIN_PCT≈%.4f",
        suggested_conf_thr, suggested_edge_min
    )

    # Jei ateityje norėsi, galime čia iš karto atnaujinti CONFIG per DB/ENV,
    # bet dabar tik pateikiame gaires loguose (saugiau TEST režime).
