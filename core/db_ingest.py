# ============================================================
# core/db_ingest.py — Istorinių duomenų perkėlimo logika (DB-only)
# Atnaujinta: 2025-11-13 (Runtime JSON sekimas pašalintas)
# - Šis failas skirtas tik istoriniam backfill, jei reikia. Runtime veiksmas nereikalingas.
# ============================================================

import os
import json
import time
import threading
import logging
from pathlib import Path
# Importai, kurių reikia backfill funkcijai (jei ji bus kviečiama)
from core.db_manager import init_db, insert_trade, upsert_equity, backfill_from_files

DATA_DIR = Path("data")
TRADE_LOG = DATA_DIR / "trade_log.jsonl" # Paliekama dėl backfill
EQUITY_JSON = DATA_DIR / "equity_history.json" # Paliekama dėl backfill

_started = False
logging.basicConfig(level=logging.INFO)


def start_ingest():
    """Paleidžia istorinį duomenų perkėlimą iš JSON failų (backfill)."""
    global _started
    if _started:
        return

    _started = True
    try:
        backfill_from_files()
        logging.info("[DB_INGEST] Istorinių JSON failų perkėlimas į DB atliktas (backfill).")
    except Exception as e:
        # Ši dalis veiks TIK vieną kartą paleidžiant botą
        logging.warning(f"[DB_INGEST] Klaida atliekant backfill: {e}")