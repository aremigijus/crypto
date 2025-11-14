# core/db_manager.py
# ============================================================
# core/db_manager.py — Centrinis DB valdymas
# Atnaujinta: 2025-11-13 (pašalintas ai_tuner kodas)
# ============================================================

import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "core.db"

def init_db():
    """Užtikrina, kad DB ir lentelės egzistuoja."""
    from core.db_init import init_full_db
    init_full_db()

def get_conn():
    """Grąžina DB connection."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def insert_trade(trade_data: dict):
    """Įrašo sandorį į trades lentelę."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trades 
            (ts, event, symbol, price, qty, usd_value, pnl_pct, reason, hold_sec, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_data.get("ts"),
            trade_data.get("event"),
            trade_data.get("symbol"),
            trade_data.get("price"),
            trade_data.get("qty"),
            trade_data.get("usd_value"),
            trade_data.get("pnl_pct"),
            trade_data.get("reason"),
            trade_data.get("hold_sec"),
            trade_data.get("confidence")
        ))
        conn.commit()

def upsert_equity(equity_data: dict):
    """Įrašo equity įrašą (UPSERT)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO equity_history 
            (ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            equity_data.get("timestamp"),
            equity_data.get("equity"),
            equity_data.get("day_pnl_pct"),
            equity_data.get("equity_pct_from_start"),
            equity_data.get("free_usdc"),
            equity_data.get("used_usdc"),
            equity_data.get("positions")
        ))
        conn.commit()

def fetch_risk_state() -> dict:
    """Grąžina risk_state lentelės reikšmes."""
    with get_conn() as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT key, value FROM risk_state").fetchall()
        return {row['key']: row['value'] for row in rows}

def update_risk_state(key: str, value: str):
    """Atnaujina risk_state reikšmę."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO risk_state (key, value)
            VALUES (?, ?)
        """, (key, value))
        conn.commit()

# ✅ PRIDĖTOS TRŪKSTAMOS FUNKCIJOS dashboard/app.py

def fetch_recent_trades(limit: int = 100):
    """Grąžina paskutinius sandorius iš trades lentelės."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT ts, event, symbol, price, qty, usd_value, pnl_pct, reason, confidence
                FROM trades 
                ORDER BY ts DESC 
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"[DB_MANAGER] Klaida gaunant sandorius: {e}")
        return []

def fetch_equity_from_db():
    """Grąžina paskutinį equity įrašą."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("""
                SELECT ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions
                FROM equity_history 
                ORDER BY ts DESC 
                LIMIT 1
            """).fetchone()
            if row:
                return dict(row)
            else:
                return {
                    "equity": 10000.0,
                    "day_pnl_pct": 0.0,
                    "equity_pct_from_start": 0.0,
                    "free_usdc": 10000.0,
                    "used_usdc": 0.0,
                    "positions": 0
                }
    except Exception as e:
        logging.error(f"[DB_MANAGER] Klaida gaunant equity: {e}")
        return {"equity": 10000.0, "day_pnl_pct": 0.0}

def fetch_open_positions_db():
    """Grąžina atidarytas pozicijas iš positions lentelės."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT symbol, entry_price, qty, opened_at, confidence
                FROM positions 
                WHERE state='OPEN' AND qty > 0
            """).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"[DB_MANAGER] Klaida gaunant pozicijas: {e}")
        return []

def ensure_tables_exist():
    """Užtikrina, kad visos reikalingos lentelės egzistuoja."""
    init_db()  # Jau turime šią funkciją

def reset_test_mode_state():
    """Išvalo testinius duomenis (paprasta versija)."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            # Išvalome pozicijas
            cur.execute("DELETE FROM positions")
            # Atstatome pradinį kapitalą
            cur.execute("DELETE FROM equity_history")
            cur.execute("""
                INSERT INTO equity_history 
                (ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions)
                VALUES (?, 10000, 0, 0, 10000, 0, 0)
            """, (datetime.now(timezone.utc).isoformat(),))
            conn.commit()
            logging.info("[DB_MANAGER] Testinis reset atliktas")
    except Exception as e:
        logging.error(f"[DB_MANAGER] Klaida atliekant reset: {e}")
        