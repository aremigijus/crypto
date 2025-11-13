# ============================================================
# core/exit_manager.py — pozicijų uždarymo logika
# Atnaujinta: 2025-11-13
# ============================================================

import time
import sqlite3
import logging
from datetime import datetime, timezone
from core.db_manager import DB_PATH
from core.exchange_adapter import get_adapter


class ExitManager:
    """Atsakingas už pozicijų uždarymo sąlygų tikrinimą."""

    def __init__(self, risk_cfg=None, order_executor=None, paper_account=None):
        self.risk_cfg = risk_cfg
        self.order_executor = order_executor
        self.paper_account = paper_account
        self.adapter = get_adapter()
        logging.info("[ExitManager] Inicializuotas (DB režimas, suderinta su main.py)")

    # --------------------------------------------------------
    def check_exits(self, prices: dict = None):
        """Tikrina, ar reikia uždaryti pozicijas pagal PnL, laiką ar signalus."""
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()

            rows = cur.execute("""
                SELECT symbol, entry_price, qty, opened_at
                FROM positions
                WHERE qty > 0 AND state='OPEN'
            """).fetchall()
            con.close()

            if not rows:
                return 0

            now = time.time()
            closed_count = 0

            for symbol, entry_price, qty, opened_at in rows:
                # --- laikymo trukmė
                try:
                    entry_ts = time.mktime(
                        time.strptime(opened_at.split(".")[0], "%Y-%m-%dT%H:%M:%S")
                    )
                except Exception:
                    entry_ts = now
                held_for_sec = now - entry_ts

                # --- kaina
                try:
                    current_price = prices.get(symbol, {}).get("price") if prices else self.adapter.get_price(symbol)
                except Exception:
                    current_price = entry_price

                # --- PnL
                pnl_pct = ((current_price / entry_price) - 1) * 100 if entry_price else 0.0
                pnl_usdc = (current_price - entry_price) * qty if entry_price else 0.0

                # --- Paprastos demo sąlygos
                if pnl_pct <= -3.0:
                    self._close_position(symbol, current_price, pnl_pct, pnl_usdc, "Stop Loss (-3%)")
                    closed_count += 1
                elif pnl_pct >= 5.0:
                    self._close_position(symbol, current_price, pnl_pct, pnl_usdc, "Take Profit (+5%)")
                    closed_count += 1
                elif held_for_sec > 86400:
                    self._close_position(symbol, current_price, pnl_pct, pnl_usdc, "Laikymo limitas 24h")
                    closed_count += 1

            return closed_count

        except Exception as e:
            logging.exception(f"[ExitManager] Klaida check_exits(): {e}")
            return 0

    # --------------------------------------------------------
    def _close_position(self, symbol, close_price, pnl_pct, pnl_usdc, reason):
        """Uždaro poziciją DB ir loguoja įvykį."""
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()

            # pažymime kaip uždarytą
            cur.execute("""
                UPDATE positions
                SET state='CLOSED', closed_at=?, close_price=?, pnl_pct=?, pnl_usdc=?, close_reason=?
                WHERE symbol=? AND state='OPEN'
            """, (
                datetime.now(timezone.utc).isoformat(),
                close_price,
                pnl_pct,
                pnl_usdc,
                reason,
                symbol
            ))

            # įrašome į trades istoriją
            cur.execute("""
                INSERT INTO trades (ts, event, symbol, price, qty, usd_value, pnl_pct, reason)
                SELECT ?, 'CLOSE', symbol, ?, qty, qty * ?, ?, ?
                FROM positions WHERE symbol=? LIMIT 1
            """, (
                datetime.now(timezone.utc).isoformat(),
                close_price,
                close_price,
                pnl_pct,
                reason,
                symbol
            ))

            con.commit()
            con.close()

            logging.info(
                f"[ExitManager] {symbol} uždaryta ({reason}) | "
                f"PnL={pnl_pct:.2f}% | {pnl_usdc:.2f} USDC"
            )

        except Exception as e:
            logging.exception(f"[ExitManager] Klaida _close_position({symbol}): {e}")
