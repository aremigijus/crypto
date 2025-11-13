# ============================================================
# core/equity_tracker.py — Equity ir PnL istorijos sekimas (DB versija)
# ============================================================

import sqlite3
import time
import threading
from datetime import datetime, timezone
from core.config import CONFIG
from notify.notifier import notify
from core.db_manager import DB_PATH, init_db
from core.paper_account import get_state

START_CAPITAL = 10_000.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_equity_row(entry: dict):
    """Įrašo vieną equity įrašą į DB."""
    init_db()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO equity_history
            (ts, equity, day_pnl_pct, equity_pct_from_start, free_usdc, used_usdc, positions)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        entry["timestamp"],
        entry["equity"],
        entry["day_pnl_pct"],
        entry["equity_pct_from_start"],
        entry["free_usdc"],
        entry["used_usdc"],
        entry["positions"]
    ))
    con.commit()
    con.close()


def update_equity_history(state: dict):
    """Apskaičiuoja equity pokyčius ir įrašo į DB."""
    try:
        if not isinstance(state, dict):
            return

        equity = float(state.get("equity_now", state.get("equity", 0.0)) or 0.0)
        free_usdc = float(state.get("free_usdc", 0.0))
        used_usdc = float(state.get("used_usdc", 0.0))
        positions = len(state.get("positions", {}))

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.row_factory = sqlite3.Row

        cur.execute("SELECT equity FROM equity_history ORDER BY ts ASC LIMIT 1")
        first = cur.fetchone()
        start_equity = float(first["equity"]) if first else START_CAPITAL

        cur.execute("SELECT equity FROM equity_history ORDER BY ts DESC LIMIT 1")
        prev = cur.fetchone()
        prev_equity = float(prev["equity"]) if prev else equity

        day_pnl_pct = ((equity - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0.0
        equity_pct_from_start = ((equity - start_equity) / start_equity * 100) if start_equity > 0 else 0.0
        con.close()

        entry = {
            "timestamp": _now_iso(),
            "equity": round(equity, 6),
            "day_pnl_pct": round(day_pnl_pct, 4),
            "equity_pct_from_start": round(equity_pct_from_start, 4),
            "free_usdc": round(free_usdc, 6),
            "used_usdc": round(used_usdc, 6),
            "positions": positions,
        }

        insert_equity_row(entry)

    except Exception as e:
        print(f"[EquityTracker] Klaida: {e}")


def get_latest_summary() -> dict:
    """Grąžina paskutinį equity įrašą (naudojama /api/summary)."""
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM equity_history ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not row:
            return {
                "timestamp": _now_iso(),
                "equity": 0.0,
                "day_pnl_pct": 0.0,
                "equity_pct_from_start": 0.0,
                "free_usdc": 0.0,
                "used_usdc": 0.0,
                "positions": 0
            }
        return dict(row)
    except Exception as e:
        print(f"[EquityTracker] Klaida get_latest_summary: {e}")
        return {}


def start_equity_auto_tracker(interval_sec: int = 300, alert_drop_pct: float = -2.0):
    """Automatinis equity sekimas kas X sekundžių (rašymas į DB, be JSON)."""
    last_alert_sent = False
    start_equity = None

    def _worker():
        nonlocal last_alert_sent, start_equity
        while True:
            try:
                state = get_state()
                update_equity_history(state)

                eq = float(state.get("equity", 0))
                used = float(state.get("used_usdc", 0))
                if start_equity is None and eq > 0:
                    start_equity = eq

                if start_equity:
                    change_pct = ((eq / start_equity) - 1) * 100
                    print(f"[EquityTracker] ✅ Equity={eq:.2f} | PnL={change_pct:+.2f}%")

                    if change_pct <= alert_drop_pct and not last_alert_sent:
                        msg = f"⚠️ Equity sumažėjo {change_pct:.2f}% (nuo {start_equity:.2f} → {eq:.2f})"
                        try:
                            notify(msg)
                        except Exception as e:
                            print(f"[EquityTracker] ⚠️ Telegram klaida: {e}")
                        last_alert_sent = True
                    elif change_pct > alert_drop_pct:
                        last_alert_sent = False
            except Exception as e:
                print(f"[EquityTracker] ⚠️ Auto klaida: {e}")
            time.sleep(interval_sec)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    print(f"[EquityTracker] 🟢 Automatinis sekimas (DB režimas, kas {interval_sec//60} min.)")
