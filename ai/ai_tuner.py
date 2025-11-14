# ai/ai_tuner.py
# ============================================================
# ai/ai_tuner.py — Dieninis AI parametrų "tuningas" (DB-only)
# ============================================================

import sqlite3
from datetime import datetime, timezone, timedelta
import logging
from statistics import mean

from core.db_manager import DB_PATH

def _read_trades(days: int = 2):
    """Paima paskutinių N dienų uždarytus sandorius iš DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        rows = cur.execute(
            """
            SELECT ts, pnl_pct, confidence
            FROM trades
            WHERE ts >= ? AND event='CLOSE'
            ORDER BY ts DESC
            """,
            (since,)
        ).fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"[AI-TUNER] Klaida skaitant trades iš DB: {e}")
        return []

def run_ai_tuner_daily(days: int = 7):
    """Apskaičiuoja metrikas ir logina patarimus."""
    logging.info(f"--- [AI-TUNER] Kasdienė metrikų analizė (per {days}d.) ---")
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

    # Rekomendacijos
    suggested_conf_thr = 0.7
    if avg_conf >= 0.8:
        suggested_conf_thr = 0.75
    elif avg_conf <= 0.5:
        suggested_conf_thr = 0.6

    suggested_edge_min = 0.0015
    if avg_pnl < 0:
        suggested_edge_min = 0.0025
    elif avg_pnl > 0.2:
        suggested_edge_min = 0.0010

    logging.info(f"📊 Rezultatai: {total} sandoriai | WinRate: {win_rate:.2f}% | Avg. PnL: {avg_pnl:+.4f}% | Avg. Conf: {avg_conf:.3f}")
    logging.info(f"💡 Rekomendacija (CONFIDENCE_THRESHOLD): ~{suggested_conf_thr:.2f}")
    logging.info(f"💡 Rekomendacija (EDGE_MIN_PCT): ~{suggested_edge_min:.4f}")
    logging.info("--- [AI-TUNER] Analizė baigta ---")