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

                # --- kaina (su apsauga nuo None)
                try:
                    if prices and symbol in prices:
                        price_data = prices.get(symbol, {})
                        current_price = price_data.get("price") if isinstance(price_data, dict) else price_data
                    else:
                        current_price = self.adapter.get_price(symbol)
                    
                    # ✅ PRIDĖTA: Apsauga nuo None ir neteisingų reikšmių
                    if current_price is None or current_price <= 0:
                        logging.debug(f"[ExitManager] Nepavyko gauti kainos {symbol}, praleidžiama")
                        continue
                        
                except Exception as e:
                    logging.debug(f"[ExitManager] Klaida gaunant kainą {symbol}: {e}")
                    continue

                # --- PnL (su apsauga nuo None ir 0)
                try:
                    if entry_price and current_price and entry_price > 0:
                        pnl_pct = ((current_price / entry_price) - 1) * 100
                        pnl_usdc = (current_price - entry_price) * qty
                    else:
                        pnl_pct = 0.0
                        pnl_usdc = 0.0
                        logging.debug(f"[ExitManager] Neteisingi duomenys {symbol}: entry={entry_price}, current={current_price}")
                        continue
                except Exception as e:
                    logging.debug(f"[ExitManager] Klaida skaičiuojant PnL {symbol}: {e}")
                    continue

                # --- Paprastos demo sąlygos
                close_reason = None
                if pnl_pct <= -3.0:
                    close_reason = "Stop Loss (-3%)"
                elif pnl_pct >= 5.0:
                    close_reason = "Take Profit (+5%)"
                elif held_for_sec > 86400:  # 24 valandos
                    close_reason = "Laikymo limitas 24h"

                if close_reason:
                    success = self._close_position(symbol, current_price, pnl_pct, pnl_usdc, close_reason)
                    if success:
                        closed_count += 1
                        logging.info(f"[ExitManager] {symbol} uždaryta ({close_reason}) | PnL={pnl_pct:.2f}% | {pnl_usdc:+.2f} USDC")

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

            # Pažymime kaip uždarytą
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

            # Įrašome į trades istoriją
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

            logging.info(f"[ExitManager] {symbol} uždaryta ({reason}) | PnL={pnl_pct:.2f}% | {pnl_usdc:+.2f} USDC")
            return True

        except Exception as e:
            logging.exception(f"[ExitManager] Klaida _close_position({symbol}): {e}")
            return False