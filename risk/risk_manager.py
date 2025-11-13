# ============================================================
# risk/risk_manager.py — Rizikos valdymas (DB režimas)
# Atnaujinta: 2025-11-11
# ------------------------------------------------------------
# - update_equity ignoruoja equity<=0 (nestabdo starto)
# - get_summary grąžina guard_status ir pnl_today
# - has_position tikrina DB lentelę positions
# - minimalus DailyGuard su max DD per dieną
# ============================================================

import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, date

from core.db_manager import DB_PATH


@dataclass
class RiskConfig:
    daily_max_loss_pct: float = 2.0
    tp_base: float = 0.06
    sl_base: float = 0.02
    tsl_base: float = 0.015
    min_hold_time_h: float = 0.083
    ai_exit_min_hold_h: float = 0.167
    hold_timeout_h: float = 12.0
    max_hold_h: float = 24.0
    vol_scale: bool = True
    confidence_scale: bool = True
    max_positions: int = 8
    max_exposure_pct: float = 85.0


class DailyGuard:
    def __init__(self, max_dd_pct: float):
        self.max_dd_pct = float(max_dd_pct)
        self.sod_equity = None  # start-of-day equity
        self.status = "OK"

    def update(self, equity_now: float):
        if equity_now is None or equity_now <= 0 or self.sod_equity is None or self.sod_equity <= 0:
            return
        dd_pct = (equity_now / self.sod_equity - 1.0) * 100.0
        # Jei kritimas žemiau -max_dd, STOP
        if dd_pct <= -abs(self.max_dd_pct):
            self.status = "STOP"

    def set_sod_equity_if_needed(self, equity_now: float):
        try:
            today = date.today().isoformat()
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            row = cur.execute(
                "SELECT equity FROM equity_history WHERE ts LIKE ? ORDER BY ts ASC LIMIT 1;",
                (f"{today}%",),
            ).fetchone()
            con.close()
            if row:
                self.sod_equity = float(row[0] or 0.0)
            else:
                self.sod_equity = float(equity_now or 0.0)
        except Exception:
            self.sod_equity = float(equity_now or 0.0)

    def get_status(self):
        return {"status": self.status, "max_dd_pct": -abs(self.max_dd_pct)}


class RiskManager:
    def __init__(self, cfg: RiskConfig, exchange=None, dry_run=True):
        self.cfg = cfg
        self.exchange = exchange
        self.dry_run = dry_run
        self.daily_guard = DailyGuard(max_dd_pct=cfg.daily_max_loss_pct)

    # kviečiama iš main
    def update_equity(self, equity_now: float):
        # Saugiklis, kad nestabdytų su 0
        if equity_now is None or equity_now <= 0:
            logging.warning("[RiskManager] Equity=0 — praleidžiam DD tikrinimą.")
            return
        # start-of-day equity nustatymas (jei dar nėra)
        if self.daily_guard.sod_equity is None:
            self.daily_guard.set_sod_equity_if_needed(equity_now)
        # DD skaičiavimas
        self.daily_guard.update(equity_now)

    def get_summary(self) -> dict:
        """Grąžina dashboard’ui reikalingą santrauką (įskaitant dd ir pnl_today)."""
        try:
            today = date.today().isoformat()
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            # šiandieninis pirmasis equity įrašas
            first = cur.execute(
                "SELECT equity FROM equity_history WHERE ts LIKE ? ORDER BY ts ASC LIMIT 1;",
                (f"{today}%",),
            ).fetchone()
            last = cur.execute(
                "SELECT equity FROM equity_history WHERE ts LIKE ? ORDER BY ts DESC LIMIT 1;",
                (f"{today}%",),
            ).fetchone()
            con.close()

            if first and last:
                sod = float(first[0] or 0.0)
                eod = float(last[0] or 0.0)
                pnl_today = ((eod / sod - 1.0) * 100.0) if sod > 0 else 0.0
            else:
                pnl_today = 0.0
        except Exception:
            pnl_today = 0.0

        status = self.daily_guard.get_status()
        return {
            "guard_status": status.get("status", "OK"),
            "pnl_today": pnl_today,
        }

    def has_position(self, symbol: str) -> bool:
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            row = cur.execute(
                "SELECT 1 FROM positions WHERE symbol=? AND state='OPEN' AND qty>0 LIMIT 1;",
                (symbol,),
            ).fetchone()
            con.close()
            return bool(row)
        except Exception:
            return False

    # suderinamumui su senu kodu
    def register_entry(self, symbol: str, entry_price: float, confidence: float):
        # įrašymas atliekamas OrderExecutor’e; čia – no-op
        return
