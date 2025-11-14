# ============================================================
# core/order_executor.py — pavedimų vykdymas (DB integruotas)
# Safe AI v7.2 (2025-11-12)
# ------------------------------------------------------------
# - Rašo atidarytas pozicijas į DB (lentelė: positions)
# - Uždarius poziciją, ją pašalina arba pažymi CLOSED
# - Suderinta su app.py /api/open_positions
# ============================================================

import sqlite3
import logging
from datetime import datetime, timezone
from core.db_manager import DB_PATH
from core.exchange_adapter import get_adapter
# import ai.ai_learning as ai_learning  # ❌ PAŠALINTA: ciklinis importas

class OrderExecutor:
    def __init__(self, exchange=None, daily_guard=None):
        self.exchange = exchange or get_adapter()
        self.daily_guard = daily_guard
        self._last_buy_ts = None

    # ======================================================
    # 💰 BUY
    # ======================================================
    def market_buy(self, symbol: str, quote_amount: float,
                   expected_edge_pct: float = 0.0,
                   ai_confidence: float = 0.0) -> dict:
        try:
            # Gauti kainą
            price = self.exchange.get_price(symbol)
            if not price:
                return {"ok": False, "error": f"Nepavyko gauti kainos {symbol}"}
            
            # Apskaičiuoti kiekį
            qty = quote_amount / float(price)
            
            # Vykdyti pavedimą
            res = self.exchange.execute_market_order(
                symbol=symbol,
                side="BUY",
                qty=qty,
                reason="AI BUY",
                confidence=ai_confidence,
            )
            
            if not res or not res.get("ok", True):
                error_msg = res.get("error", "Nežinoma klaida") if res else "Nėra atsakymo"
                return {"ok": False, "error": error_msg}

            # Įrašome į DB lentelę positions
            entry_price = float(res.get("fill_price", price))
            executed_qty = float(res.get("qty", qty))
            opened_at = datetime.now(timezone.utc).isoformat()

            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO positions 
                (symbol, entry_price, qty, opened_at, confidence, state)
                VALUES (?, ?, ?, ?, ?, 'OPEN')
            """, (symbol, entry_price, executed_qty, opened_at, ai_confidence))
            con.commit()
            con.close()

            logging.info(f"[OrderExecutor] 🟢 BUY {symbol} {executed_qty} @ {entry_price:.6f} | {quote_amount:.2f} USDC")
            return {
                "ok": True, 
                "symbol": symbol, 
                "qty": executed_qty, 
                "price": entry_price, 
                "usdc_amount": quote_amount
            }

        except Exception as e:
            logging.exception(f"[OrderExecutor] Klaida market_buy {symbol}: {e}")
            return {"ok": False, "error": str(e)}

    # ======================================================
    # 🔴 SELL
    # ======================================================
    def market_sell(self, symbol: str, base_qty: float,
                    expected_edge_pct: float = 0.0,
                    ai_confidence: float = 0.0,
                    allow_partial: bool = True,
                    reason: str = "MANUAL",
                    entry_price: float = 0.0) -> dict:
        try:
            res = self.exchange.execute_market_order(
                symbol=symbol,
                side="SELL",
                qty=base_qty,
                reason=reason,
                confidence=ai_confidence,
            )
            
            if not res or not res.get("ok", True):
                error_msg = res.get("error", "Nežinoma klaida") if res else "Nėra atsakymo"
                return {"ok": False, "error": error_msg}

            sell_price = float(res.get("fill_price", 0))
            executed_qty = float(res.get("qty", base_qty))
            usdc_gain = (sell_price - entry_price) * executed_qty if entry_price and executed_qty else 0.0

            # Pašaliname poziciją iš DB arba pažymime kaip CLOSED
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            
            # Variantas 1: Ištriname poziciją
            cur.execute("DELETE FROM positions WHERE symbol = ?;", (symbol,))
            
            # Variantas 2: Arba pažymime kaip CLOSED (išsaugo istoriją)
            # cur.execute("""
            #     UPDATE positions SET state='CLOSED', closed_at=?, close_price=?, pnl_usdc=?
            #     WHERE symbol=? AND state='OPEN'
            # """, (datetime.now(timezone.utc).isoformat(), sell_price, usdc_gain, symbol))
            
            con.commit()
            con.close()

            # Atnaujiname paper account balansą
            try:
                from core.paper_account import update_balance_after_sell
                update_balance_after_sell(symbol, executed_qty, entry_price, sell_price, usdc_gain)
            except Exception as e:
                logging.warning(f"[OrderExecutor] Nepavyko atnaujinti paper account: {e}")

            logging.info(f"[OrderExecutor] 🔴 SELL {symbol} {executed_qty} @ {sell_price:.6f} | PnL={usdc_gain:+.2f} USDC")
            return {
                "ok": True, 
                "symbol": symbol, 
                "qty": executed_qty, 
                "price": sell_price, 
                "usdc_gain": usdc_gain
            }

        except Exception as e:
            logging.exception(f"[OrderExecutor] Klaida market_sell {symbol}: {e}")
            return {"ok": False, "error": str(e)}

    # ======================================================
    # 📊 Pagalbinės funkcijos
    # ======================================================
    def get_available_qty(self, symbol: str) -> float:
        """Grąžina turimą kiekį DB lentelėje positions."""
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            row = cur.execute(
                "SELECT qty FROM positions WHERE symbol=? AND state='OPEN';", (symbol,)
            ).fetchone()
            con.close()
            if not row:
                return 0.0
            return float(row[0] or 0.0)
        except Exception as e:
            logging.warning(f"[OrderExecutor] Nepavyko gauti qty {symbol}: {e}")
            return 0.0