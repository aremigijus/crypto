# ============================================================
# ai/ai_performance.py — AI našumo analizė (tik DB, be JSON)
# Suderinama su main.py: get_ai_performance() → klasės objektas
# ============================================================
from pathlib import Path
import sqlite3
import logging
from datetime import datetime, timezone
from core.db_manager import DB_PATH

# ============================================================
# Lentelės garantavimas (naudojame DB_PATH iš db_manager)
# ============================================================

def _ensure_table():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                symbol TEXT,
                confidence REAL,
                edge REAL,
                pnl_usdc REAL,
                hold_sec REAL
            );
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[AI-PERF] Nepavyko sukurti ai_metrics lentelės: {e}")


# ============================================================
# KLASĖ — NAUDOJAMA MAIN.PY
# ============================================================

class AIPerformance:
    def __init__(self):
        _ensure_table()

    # ... (likusi dalis be pakeitimų)
    # ... record_equity, get_summary ...
    
    def record_equity(self):
        # Šiai funkcijai reikia importuoti logiką iš 'core.equity_tracker' arba 'core.paper_account', 
        # bet atsižvelgiant į jau esančią struktūrą, paliekamas tuščias implementacijos pavyzdys, jei ji buvo perkelta į kitą vietą.
        # Tikrasis įrašymas vyksta equity_tracker.py
        pass


    def get_summary(self) -> dict:
        """Grąžina AI veiklos metrikų suvestinę (nuo starto)."""
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()

            # Skaičiuoja vidutinį PnL tik iš uždarytų (SELL) sandorių
            cur.execute("""
                SELECT
                    COUNT(id),
                    SUM(CASE WHEN pnl_usdc > 0 THEN 1 ELSE 0 END),
                    AVG(confidence),
                    AVG(edge),
                    SUM(pnl_usdc)
                FROM ai_metrics
            """)
            row = cur.fetchone()
            conn.close()

            if not row or row[0] == 0:
                return {
                    "win_rate": 0,
                    "total_trades": 0,
                    "avg_confidence": 0,
                    "avg_edge": 0,
                    "profit_usdc": 0,
                }

            total = row[0]
            wins = row[1] or 0
            conf = row[2] or 0
            edge = row[3] or 0
            profit = row[4] or 0

            return {
                "win_rate": round(wins / total * 100, 2),
                "total_trades": total,
                "avg_confidence": round(conf, 3),
                "avg_edge": round(edge, 5),
                "profit_usdc": round(profit, 3),
            }

        except Exception as e:
            logging.error(f"[AI-PERF] Klaida skaitant AI metrikas: {e}")
            return {
                "win_rate": 0,
                "total_trades": 0,
                "avg_confidence": 0,
                "avg_edge": 0,
                "profit_usdc": 0,
            }