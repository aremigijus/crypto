# ============================================================
# core/paper_account.py — Pozicijų valdymas (DB versija)
# ------------------------------------------------------------
# Test režime palaiko pradinį balansą (10 000 USDC)
# Visos būsenos operacijos atliekamos per DB.
# ============================================================

import sqlite3
import logging
from datetime import datetime, timezone
from core.db_manager import DB_PATH, fetch_risk_state, update_risk_state
from core.config import CONFIG

START_CAPITAL = 10_000.0  # testinės sąskaitos pradinis kapitalas

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _get_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 📊 Pagrindinės operacijos
# ============================================================

def get_open_positions() -> dict:
    """Grąžina visas atidarytas pozicijas iš DB."""
    con = _get_conn()
    rows = con.execute("SELECT * FROM positions WHERE state='OPEN'").fetchall()
    con.close()
    return {
        r["symbol"]: {
            "entry_price": r["entry_price"],
            "qty": r["qty"],
            "confidence": r["confidence"],
            "opened_at": r["opened_at"]
        }
        for r in rows
    }


def get_equity_from_db() -> float:
    """Grąžina paskutinį įrašą iš equity_history lentelės."""
    try:
        con = _get_conn()
        row = con.execute("SELECT equity FROM equity_history ORDER BY ts DESC LIMIT 1").fetchone()
        con.close()
        return float(row["equity"]) if row else START_CAPITAL
    except Exception:
        return START_CAPITAL


def get_state() -> dict:
    """
    Grąžina dabartinę sąskaitos būseną (balansą, pozicijas) iš DB.
    Ši funkcija pakeičia seną JSON įkėlimo logiką.
    """
    try:
        equity = get_equity_from_db()
        positions = get_open_positions()

        used_usdc = sum(
            pos["qty"] * pos["entry_price"]
            for pos in positions.values()
        )
        free_usdc = equity - used_usdc

        # Skaičiuojame PnL tik dienai (šis duomenys gaunamas iš daily guard)
        risk_state = fetch_risk_state()
        dd_day_pct = float(risk_state.get('dd_day_pct', 0.0))
        
        return {
            "balance_usdc": equity,
            "equity": equity,
            "free_usdc": free_usdc,
            "used_usdc": used_usdc,
            "positions": positions,
            "open_positions": len(positions),
            "daily_pnl_pct": dd_day_pct,
            "timestamp": _now_iso(),
        }
    except Exception as e:
        logging.error(f"[PaperAccount] Klaida gaunant būseną iš DB: {e}")
        return {
            "balance_usdc": START_CAPITAL,
            "equity": START_CAPITAL,
            "free_usdc": START_CAPITAL,
            "used_usdc": 0,
            "positions": {},
            "open_positions": 0,
            "daily_pnl_pct": 0.0,
            "timestamp": _now_iso(),
        }

def update_balance_after_sell(symbol: str, qty: float, entry_price: float, exit_price: float, usdc_gain: float):
    """
    Atnaujina virtualios sąskaitos (Paper Account) balansą po pozicijos uždarymo.
    Supaprastinta versija - tiesiog loginu PnL, nes balansas atnaujinamas per equity_tracker automatiškai.
    """
    try:
        logging.info(f"[PaperAccount] 📊 SELL {symbol}: PnL = {usdc_gain:+.2f} USDC | Qty: {qty} @ {exit_price:.6f}")
        # Balansas automatiškai atnaujinamas per equity_tracker.py ir get_state() funkciją
        # Nereikia rankinio atnaujinimo, nes sistema veikia per DB
    except Exception as e:
        logging.error(f"[PaperAccount] Klaida atnaujinant balansą: {e}")
        
def clear_closed_positions(older_than_days: int = 30):
    """Pašalina CLOSED pozicijas, senesnes nei N dienų, kad išvalytų DB."""
    try:
        from datetime import timedelta  # ✅ PRIDĖTA: trūksta šio importo
        
        con = _get_conn()
        cur = con.cursor()
        threshold_iso = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        
        cur.execute("DELETE FROM positions WHERE state='CLOSED' AND closed_at < ?", (threshold_iso,))
        count = cur.rowcount
        con.commit()
        con.close()
        if count > 0:
             logging.info(f"[PaperAccount] 🧹 Išvalytos senos CLOSED pozicijos (> {older_than_days} d.) - {count} įrašai.")
    except Exception as e:
        logging.error(f"[PaperAccount] Klaida valant senas pozicijas: {e}")


# ============================================================
# 🔍 Diagnostika
# ============================================================

def debug_dump():
    """Išspausdina visas pozicijas iš DB."""
    con = _get_conn()
    rows = con.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
    con.close()
    print("=== Pozicijos DB ===")
    for r in rows:
        print(dict(r))
    print("====================")

def get_account_state():
    """
    Grąžina dabartinę virtualios (paper) sąskaitos būseną — balansą, equity ir pozicijas iš DB.
    Šalina priklausomybę nuo paper_account.json.
    """
    try:
        # 1. Pasiimame atidarytas pozicijas
        positions = get_open_positions()

        # 2. Pasiimame paskutinį equity įrašą
        con = _get_conn()
        row = con.execute("""
            SELECT ts, equity, free_usdc, used_usdc
            FROM equity_history
            ORDER BY ts DESC
            LIMIT 1
        """).fetchone()
        con.close()

        if row:
            return {
                "balance_usdc": float(row["free_usdc"]),
                "positions": positions,
                "equity": float(row["equity"]),
                "free_usdc": float(row["free_usdc"]),
                "used_usdc": float(row["used_usdc"]),
                "timestamp": row["ts"]
            }
        else:
            logging.warning("[PaperAccount] Nepavyko gauti būsenos iš DB. Grąžinama pradinė būsena.")
            now = datetime.now(timezone.utc).isoformat()
            return {
                "balance_usdc": START_CAPITAL,
                "positions": {},
                "equity": START_CAPITAL,
                "free_usdc": START_CAPITAL,
                "used_usdc": 0.0,
                "timestamp": now
            }

    except Exception as e:
        logging.exception(f"[PaperAccount] Klaida skaitant būseną iš DB: {e}")
        now = datetime.now(timezone.utc).isoformat()
        return {
            "balance_usdc": START_CAPITAL,
            "positions": {},
            "equity": START_CAPITAL,
            "free_usdc": START_CAPITAL,
            "used_usdc": 0.0,
            "timestamp": now
        }