# -*- coding: utf-8 -*-
# ============================================================
# manage.py — Safe AI Bot valdymas (CLI režimas)
# ============================================================

import os
import sys
import time
import sqlite3
import logging
import subprocess
import psutil
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "core.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

START_CAPITAL = 10_000.0


# ============================================================
# 🧾 Pagalbinės funkcijos
# ============================================================

def init_db_structure():
    """Užtikrina, kad lentelės egzistuoja."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        qty REAL DEFAULT 0,
        entry_price REAL DEFAULT 0,
        opened_at TEXT,
        confidence REAL DEFAULT 0,
        state TEXT DEFAULT 'OPEN'
    );

    CREATE TABLE IF NOT EXISTS equity_history (
        ts TEXT,
        equity REAL DEFAULT 0,
        day_pnl_pct REAL DEFAULT 0,
        equity_pct_from_start REAL DEFAULT 0,
        free_usdc REAL DEFAULT 0,
        used_usdc REAL DEFAULT 0,
        positions INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS ai_metrics (
        ts TEXT,
        avg_confidence REAL,
        avg_pnl REAL,
        win_rate REAL,
        trades_count INTEGER,
        avg_hold_sec REAL
    );

    CREATE TABLE IF NOT EXISTS risk_state (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        event TEXT,
        symbol TEXT,
        price REAL,
        qty REAL,
        usd_value REAL,
        confidence REAL,
        pnl_pct REAL,
        reason TEXT,
        hold_sec REAL,
        hold_time_str TEXT
    );
    """)
    con.commit()
    con.close()


def reset_database():
    """Išvalo DB ir įrašo bazinius duomenis testavimui."""
    logging.info("🧹 Išvaloma DB...")
    init_db_structure()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    for t in ["positions", "trades", "ai_metrics", "risk_state", "equity_history"]:
        try:
            cur.execute(f"DELETE FROM {t};")
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()

    cur.execute("""
        INSERT INTO equity_history
        (ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions)
        VALUES (?, ?, 0, 0, ?, 0, 0);
    """, (now, START_CAPITAL, START_CAPITAL))

    cur.execute("""
        INSERT INTO positions (symbol, qty, entry_price, opened_at, confidence, state)
        VALUES ('BTCUSDC', 0.001, 68000.0, ?, 0.8, 'OPEN');
    """, (now,))

    cur.execute("""
        INSERT INTO risk_state (key, value)
        VALUES
            ('dd_day_pct', '-0.3'),
            ('dd_week_pct', '-1.1'),
            ('dd_month_pct', '-2.0'),
            ('max_positions', '8'),
            ('max_exposure_pct', '85');
    """)

    con.commit()
    con.close()
    logging.info("✅ DB išvalyta ir baziniai duomenys įrašyti.")


def start_bot():
    """Paleidžia botą ir dashboard. TEST režime patikrina kapitalą."""
    python_exe = sys.executable
    logging.info("🟢 Paleidžiamas botas ir dashboard...")

    # TEST režimo kapitalo inicializacija
    from core.config import CONFIG
    if CONFIG.get("MODE", "").upper() == "TEST":
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM equity_history;")
            count = cur.fetchone()[0]
            if count == 0:
                now = datetime.now(timezone.utc).isoformat()
                cur.execute("""
                    INSERT INTO equity_history
                    (ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions)
                    VALUES (?, 10000, 0, 0, 10000, 0, 0);
                """, (now,))
                con.commit()
                logging.info("💰 TEST režimas — automatiškai nustatytas pradinis kapitalas (10 000 USDC).")
            con.close()
        except Exception as e:
            logging.warning(f"⚠️ Nepavyko inicializuoti TEST kapitalo: {e}")

    # Paleidžiamas bot ir dashboard
    subprocess.Popen([python_exe, "-m", "core.main"], stdout=None, stderr=None)
    subprocess.Popen([python_exe, "-m", "dashboard.app"], stdout=None, stderr=None)
    logging.info("✅ Abu procesai paleisti.")



def stop_bot():
    """Sustabdo visus boto ir dashboard procesus."""
    logging.info("🔴 Stabdomi procesai...")
    for p in psutil.process_iter(attrs=["pid", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            if any(x in cl for x in ["core.main", "dashboard.app"]):
                p.terminate()
                logging.info(f"🛑 Sustabdytas procesas PID={p.info['pid']}")
        except Exception:
            continue
    time.sleep(2)
    logging.info("✅ Visi procesai sustabdyti.")


def restart_bot():
    """Išvalo procesus ir paleidžia botą iš naujo."""
    stop_bot()
    start_bot()


def check_db():
    """Tikrina DB struktūrą ir lentelių kiekį."""
    init_db_structure()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cur.fetchall()]
    con.close()
    logging.info(f"📊 Rasta {len(tables)} lentelių: {', '.join(tables)}")


def full_test_reset():
    """Atlieka pilną testinį režimo reset + startą."""
    reset_database()
    restart_bot()
    logging.info("🧪 Testavimo režimas paleistas sėkmingai (kapitalas 10 000 USDC).")


# ============================================================
# CLI komandos (naudojamos ir .bat meniu)
# ============================================================
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "start":
        start_bot()
    elif cmd == "stop":
        stop_bot()
    elif cmd == "reset":
        reset_database()
    elif cmd == "restart":
        restart_bot()
    elif cmd == "checkdb":
        check_db()
    elif cmd == "test":
        full_test_reset()
    else:
        print("""
Naudojimas:
    python manage.py start     — paleidžia botą ir dashboard
    python manage.py stop      — sustabdo botą ir dashboard
    python manage.py reset     — išvalo DB ir įrašo bazinius duomenis
    python manage.py restart   — perkrauna botą
    python manage.py checkdb   — tikrina DB struktūrą
    python manage.py test      — pilnas testavimo paleidimas (reset + start)
        """)
