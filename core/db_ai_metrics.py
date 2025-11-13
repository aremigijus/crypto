# ============================================================
# core/db_ai_metrics.py — AI kokybės (metrics) agregatorius
# ------------------------------------------------------------
# Kas 5 arba 15 min (pagal režimą):
#   - Skaito SELL sandorius iš trades lentelės
#   - Skaičiuoja avg_confidence, avg_pnl, win_rate, avg_hold_sec
#   - Įrašo į ai_metrics lentelę
# ============================================================

import os
import time
import threading
import sqlite3
from datetime import datetime, timezone
from core.db_manager import DB_PATH, init_db
from core.config import CONFIG

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_ai_metrics_table():
    """Sukuria lentelę ai_metrics, jei dar nėra."""
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS ai_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day_key TEXT DEFAULT '',
            trades_count INTEGER DEFAULT 0,
            avg_confidence REAL DEFAULT 0,
            avg_pnl REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            avg_hold_sec REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_ai_metrics_ts ON ai_metrics (ts);
        """)
        c.commit()

def compute_ai_metrics():
    """Apskaičiuoja AI kokybės suvestinę."""
    init_db()
    init_ai_metrics_table()

    with get_conn() as c:
        rows = c.execute("""
            SELECT confidence, pnl_pct, hold_sec
            FROM trades
            WHERE UPPER(event)='SELL'
            ORDER BY ts DESC
            LIMIT 1000
        """).fetchall()

        if not rows:
            print("[AI-METRICS] ⚠️ Nėra SELL sandorių — nieko neskaičiuojama.")
            return None

        confs = [r["confidence"] for r in rows if r["confidence"] is not None]
        pnls = [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
        holds = [r["hold_sec"] for r in rows if r["hold_sec"] is not None]

        trades_count = len(rows)
        avg_conf = sum(confs)/len(confs) if confs else 0
        avg_pnl = sum(pnls)/len(pnls) if pnls else 0
        win_rate = (sum(1 for p in pnls if p > 0) / len(pnls) * 100) if pnls else 0
        avg_hold = sum(holds)/len(holds) if holds else 0
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "day_key": day_key,
            "trades_count": trades_count,
            "avg_confidence": round(avg_conf, 4),
            "avg_pnl": round(avg_pnl, 4),
            "win_rate": round(win_rate, 2),
            "avg_hold_sec": round(avg_hold, 2)
        }

        c.execute("""
            INSERT INTO ai_metrics
              (ts, day_key, trades_count, avg_confidence, avg_pnl, win_rate, avg_hold_sec)
            VALUES (:ts, :day_key, :trades_count, :avg_confidence, :avg_pnl, :win_rate, :avg_hold_sec)
        """, result)
        c.commit()

        print(f"[AI-METRICS] ✅ Atnaujinta ({result['ts']}) — {trades_count} sandoriai")
        return result

def _loop():
    """Kas 5–15 min atnaujina duomenis priklausomai nuo režimo."""
    interval = 300 if CONFIG.get("MODE") == "TEST" else 900
    while True:
        try:
            compute_ai_metrics()
        except Exception as e:
            print(f"[AI-METRICS] Klaida: {e}")
        time.sleep(interval)

def start_ai_metrics_loop():
    """Paleidžia fono procesą (vieną kartą)."""
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
