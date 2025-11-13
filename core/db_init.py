# -*- coding: utf-8 -*-
# ============================================================
# init_db_full.py — pilnas DB sutvarkymas Safe AI Bot projektui
# Sukuria naują core.db struktūrą 100% suderintą su main.py
# ============================================================

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import logging

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "core.db"  # PAKEISTA: DB pavadinimas suderintas su db_manager.py (core.db)

START_CAPITAL = 10_000.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

def recreate_tables():
    """Pilnai sukuria DB struktūrą iš naujo."""
    logging.info("🔧 Perkuriama core.db struktūra...") # <--- PAKEISTA: Pranešimas apie core.db

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ištriname senas lenteles
    cur.executescript("""
        DROP TABLE IF EXISTS positions;
        DROP TABLE IF EXISTS equity_history;
        DROP TABLE IF EXISTS ai_metrics;
        DROP TABLE IF EXISTS risk_state;
        DROP TABLE IF EXISTS trades;
    """)

    # Sukuriame naujas lenteles
    cur.executescript("""
        -- Aktyvios pozicijos
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            entry_price REAL,
            qty REAL,
            opened_at TEXT,
            confidence REAL DEFAULT 0.0,
            edge REAL DEFAULT 0.0,
            state TEXT DEFAULT 'OPEN',
            closed_at TEXT,
            close_price REAL,
            pnl_pct REAL,
            pnl_usdc REAL,
            close_reason TEXT
        );

        -- Equity ir PnL istorija
        CREATE TABLE equity_history (
            ts TEXT PRIMARY KEY,
            equity REAL,
            day_pnl_pct REAL DEFAULT 0.0,
            equity_pct_from_start REAL DEFAULT 0.0,
            free_usdc REAL DEFAULT 0.0,
            used_usdc REAL DEFAULT 0.0,
            positions INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_equity_history_ts ON equity_history(ts);

        -- AI veiklos metrikos
        CREATE TABLE ai_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day_key TEXT DEFAULT '',
            trades_count INTEGER DEFAULT 0,
            avg_confidence REAL DEFAULT 0,
            avg_pnl REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            avg_hold_sec REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_ai_metrics_day ON ai_metrics(day_key);
        
        -- Rizikos valdymo būsena (key-value)
        CREATE TABLE risk_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- Visi sandoriai (atidarymas/uždarymas/SL/TP)
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            event TEXT, -- BUY, SELL, OPEN, CLOSE, SL, TP
            symbol TEXT,
            price REAL,
            qty REAL,
            usd_value REAL,
            pnl_pct REAL DEFAULT 0.0,
            reason TEXT,
            confidence REAL DEFAULT 0.0,
            hold_sec REAL DEFAULT 0.0
        );
        CREATE INDEX IF NOT EXISTS ix_trades_ts ON trades(ts);
        CREATE INDEX IF NOT EXISTS ix_trades_symbol ON trades(symbol);
    """)

    conn.commit()
    conn.close()
    logging.info("✅ DB struktūra sukurta.")


def insert_initial_rows():
    """Įrašo pradinę būseną."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    now = datetime.now(timezone.utc).isoformat()

    # Pradinis kapitalas
    logging.info("💰 Įrašomas pradinis kapitalas 10 000 USDC")

    cur.execute("""
        INSERT INTO equity_history
        (ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions)
        VALUES (?, ?, 0, 0, ?, 0, 0)
    """, (now, START_CAPITAL, START_CAPITAL))

    # Pradinis risk_state
    logging.info("🛡️ Įrašomi pradiniai risk_state parametrai")

    cur.executescript("""
        INSERT INTO risk_state (key, value) VALUES
            ('dd_day_pct', '-0.3'),
            ('dd_week_pct', '-1.1'),
            ('dd_month_pct', '-2.0'),
            ('max_positions', '8'),
            ('max_exposure_pct', '85'),
            ('status', 'OK');
    """)

    conn.commit()
    conn.close()
    logging.info("✅ Pradiniai duomenys įrašyti.")


# ============================================================
# Vykdymas
# ============================================================

def init_full_db(force_recreate: bool = False):
    """Paleidžia pilną DB inicijavimą."""
    if force_recreate or not DB_PATH.exists():
        recreate_tables()
        insert_initial_rows()
    else:
        logging.info("⚠️ core.db jau egzistuoja, inicijavimas praleistas (naudokite force_recreate=True, jei reikia).")

if __name__ == "__main__":
    init_full_db(force_recreate=True)