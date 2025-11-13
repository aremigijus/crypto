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
import ai.ai_learning as ai_learning

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
            res = self.exchange.execute_market_order(
                symbol=symbol,
                side="BUY",
                qty=quote_amount / float(self.exchange.get_price(symbol) or 1),
                reason="AI BUY",
                confidence=ai_confidence,
            )
            if not res:
                raise ValueError("Nėra atsakymo iš execute_market_order")

            # Įrašome į DB lentelę positions
            entry_price = float(res.get("fill_price") or 0)
            qty = float(res.get("qty") or 0)
            opened_at = datetime.now(timezone.utc).isoformat()
            conf = float(res.get("confidence") or 0.0)

            # Pašaliname poziciją iš DB
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("DELETE FROM positions WHERE symbol = ?;", (symbol,))
            con.commit()
            con.close()

            # Jei esame Paper Mode, atnaujiname paper sąskaitą per adapterį.
            # Adapteris turi žinoti, ar jis yra "Paper" režime, kad būtų iškviesta teisinga funkcija.
            if self.exchange.is_paper_mode():  # Pataisyta: Patikrinimas per adapterį
                self.exchange.update_paper_account_on_sell(
                    symbol=symbol,
                    qty=qty,
                    entry_price=entry_price,
                    exit_price=sell_price,
                    usdc_gain=usdc_gain,
                )
                
            logging.info(f"[OrderExecutor] 🔴 SELL {symbol} {qty} @ {sell_price:.6f} | PnL={usdc_gain:+.2f}")
            return {"ok": True, "symbol": symbol, "qty": qty, "price": sell_price, "usdc_gain": usdc_gain}

        except Exception as e:
            logging.exception(f"[OrderExecutor] Klaida market_sell {symbol}: {e}")

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
            if not res:
                raise ValueError("Nėra atsakymo iš execute_market_order")

            sell_price = float(res.get("fill_price") or 0)
            qty = float(res.get("qty") or base_qty)
            usdc_gain = (sell_price - entry_price) * qty if entry_price and qty else 0.0

            # Pašaliname poziciją iš DB
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("DELETE FROM positions WHERE symbol = ?;", (symbol,))
            con.commit()
            con.close()

            logging.info(f"[OrderExecutor] 🔴 SELL {symbol} {qty} @ {sell_price:.6f} | PnL={usdc_gain:+.2f}")
            return {"ok": True, "symbol": symbol, "qty": qty, "price": sell_price, "usdc_gain": usdc_gain}

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
