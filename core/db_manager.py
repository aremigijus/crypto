# ============================================================
# ai/ai_tuner.py — Dieninis AI parametrų "tuningas" (DB-only)
# ------------------------------------------------------------
# Skaito rezultatus iš DB (trades) ir pateikia rekomendacijas
# (loguose). Nerašo į failus, nekeičia config tiesiogiai.
# ============================================================

from __future__ import annotations
import sqlite3
from datetime import datetime, timezone, timedelta
import logging
from statistics import mean

from core.db_manager import DB_PATH  # <--- PAKEISTA: Importuojame tik is core.db_manager


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
            WHERE ts >= ? AND event='CLOSE'
            ORDER BY ts DESC
            """,
            (since,)
        ).fetchall()
        con.close()
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

    # Rekomendacijos — konservatyvios, tik kaip gairės:
    # jei vidutinis confidence stipriai > 0.7, didinam slenkstį; jei < 0.5 — mažinam
    suggested_conf_thr = 0.7
    if avg_conf >= 0.8:
        suggested_conf_thr = 0.75
    elif avg_conf <= 0.5:
        suggested_conf_thr = 0.6

    # jei avg_pnl < 0, priveržti edge minimalų; jei > 0.2, galima atlaisvinti
    suggested_edge_min = 0.0015
    if avg_pnl < 0:
        suggested_edge_min = 0.0025
    elif avg_pnl > 0.2:
        suggested_edge_min = 0.0010

    logging.info(f"📊 Rezultatai: {total} sandoriai | WinRate: {win_rate:.2f}% | Avg. PnL: {avg_pnl:+.4f}% | Avg. Conf: {avg_conf:.3f}")
    logging.info(f"💡 Rekomendacija (CONFIDENCE_THRESHOLD): ~{suggested_conf_thr:.2f} (dabar: ?) ")
    logging.info(f"💡 Rekomendacija (EDGE_MIN_PCT): ~{suggested_edge_min:.4f} (dabar: ?) ")
    logging.info("--- [AI-TUNER] Analizė baigta ---")

    def backfill_from_files():
    """Vienkartinis backfill iš JSON failų į DB (idempotentiška). Dabar tik trades."""
    # Čia turite užtikrinti, kad aukščiau apibrėžtos funkcijos (_iter_jsonl, _load_json, init_db, insert_trade) yra prieinamos
    # Pilnas backfill turėtų būti atliekamas per init_db_full.py. 
    # Ši funkcija skirta tik likusiems trades logams.

    init_db()

    # trades
    for t in _iter_jsonl(TRADE_LOG):
        insert_trade({
            "ts": t.get("ts") or t.get("timestamp"),
            "event": t.get("event"),
            "symbol": t.get("symbol"),
            "price": t.get("price"),
            "qty": t.get("qty"),
            "usd_value": t.get("usd_value"),
            "pnl_pct": t.get("pnl_pct"),
            "reason": t.get("reason"),
            "hold_sec": t.get("hold_sec"),
            "confidence": t.get("confidence"),
        })

    # equity - PAŠALINTA. Equity rašomas tiesiogiai per equity_tracker.py, o pradinis įrašas
    # turi būti atliktas per db_init.py.
    pass # <--- PAKEISTA: Pašalintas equity backfill iš JSON