# ============================================================
# core/exchange_adapter.py — Binance prekybos adapteris
# Atnaujinta: 2025-11-13 (DB-Only)
# ============================================================

import json
import time
import hmac
import hashlib
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import requests

from .config import CONFIG
from . import ws_bridge
# import core.paper_account as PaperAccount  # ❌ PAŠALINTA: ciklinis importas

API_BASE = "https://api.binance.com"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# ------------------------------------------------------------
def _timestamp_ms() -> int:
    return int(time.time() * 1000)

def _now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _sign(params: Dict[str, Any], secret: str) -> Dict[str, Any]:
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params

# ============================================================
# Adapterio klasė
# ============================================================

class ExchangeAdapter:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.fee_taker = CONFIG.get("FEE_TAKER", 0.0006)
        self.fee_maker = CONFIG.get("FEE_MAKER", 0.0004)
        self.base_quote = CONFIG.get("BASE_QUOTE", "USDC").upper()
        self.dry_run = CONFIG.get("DRY_RUN", True)  # ✅ PRIDĖTA: dry_run savybė

        if CONFIG.get("USE_TESTNET", False):
            logging.warning("[ExchangeAdapter] Dėmesio: TESTNET nustatymas ignoruojamas. Naudojamas tik DRY_RUN (jei įjungtas).")

    # ------------------------------------------------------------
    # Pagrindinis pavedimo vykdymo metodas
    # ------------------------------------------------------------
    def execute_market_order(self, symbol: str, side: str, qty: float, reason: str, confidence: float) -> dict:
        """
        Vykdo market pavedimą, naudodamas DRY_RUN/LIVE logiką.
        qty turi būti bazinės monetos kiekis (pvz., BTC kiekis pirkimui).
        """
        qty = max(0.0, qty)
        if qty == 0.0:
            return {"ok": False, "error": "Kiekis (qty) negali būti nulis."}

        # 1. Gauname dabartinę kainą (reikalinga fill kainos simuliacijai)
        price_now = ws_bridge.get_price(symbol)
        if not price_now:
            return {"ok": False, "error": f"Nepavyko gauti kainos {symbol}"}
        
        # 2. Vykdymas pagal režimą
        if self.dry_run:
            return self._dry_run_order(symbol, side, qty, price_now, reason, confidence)
        else:
            return self._real_order(symbol, side, qty, reason, confidence)

    # ------------------------------------------------------------
    # Pagalbiniai metodai (Dry Run / Real)
    # ------------------------------------------------------------
    
    def _dry_run_order(self, symbol: str, side: str, qty: float, price_now: float, reason: str, confidence: float) -> dict:
        """Simuliuoja pavedimą (popierinė prekyba)."""
        
        # Simuliuojama fill kaina (pvz., pridedant 0.05% slippage)
        fill_price = price_now * (1.0005 if side == "BUY" else 0.9995)
        executed_qty = qty
        
        # Simuliuojamas mokestis
        fee = executed_qty * fill_price * self.fee_taker
        
        result = {
            "ok": True,  # ✅ PRIDĖTA: reikalinga order_executor.py
            "symbol": symbol,
            "side": side,
            "qty": executed_qty,
            "fill_price": fill_price,
            "fee": fee,
            "timestamp": _now_str(),
            "dry_run": True,
            "reason": reason,
            "confidence": confidence,
        }
        
        logging.info(f"[DryRunOrder] ✅ {side} {executed_qty} {symbol} @ {fill_price:.6f} (simuliacija)")
        return result

    def _real_order(self, symbol: str, side: str, qty: float, reason: str, confidence: float) -> dict:
        """Vykdo realų pavedimą per Binance API."""
        try:
            ts = _timestamp_ms()
            order_type = "MARKET"
            
            params = {"symbol": symbol, "side": side, "type": order_type, 
                      "quantity": qty, "timestamp": ts}
            
            _sign(params, self.api_secret)
            headers = {"X-MBX-APIKEY": self.api_key}
            
            # Siunčiame pavedimą
            r = requests.post(f"{API_BASE}/api/v3/order", params=params, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            
            # Apdorojame atsakymą
            executed_qty = float(data.get("executedQty", qty))
            fill_price = float(data.get("fills", [{}])[0].get("price", data.get("price", ws_bridge.get_price(symbol))))
            
            # Apskaičiuojame mokestį
            fee = executed_qty * fill_price * self.fee_taker
            
            result = {
                "ok": True,  # ✅ PRIDĖTA: reikalinga order_executor.py
                "symbol": symbol,
                "side": side,
                "qty": executed_qty,
                "fill_price": fill_price,
                "fee": fee,
                "timestamp": _now_str(),
                "dry_run": False,
                "reason": reason,
                "confidence": confidence,
            }
            logging.info(f"[BinanceOrder] ✅ {side} {executed_qty} {symbol} @ {fill_price:.6f}")
            return result
        
        except Exception as e:
            logging.exception(f"[BinanceAdapter] Klaida vykdant pavedimą {symbol}: {e}")
            return {"ok": False, "error": str(e)}

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100):
            """Gauna istorinius kainų duomenis iš Binance."""
            try:
                url = f"{API_BASE}/api/v3/klines"
                params = {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit
                }
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                klines = response.json()
                
                # Konvertuojame į dict formatą
                result = []
                for k in klines:
                    result.append({
                        "timestamp": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5])
                    })
                return result
            except Exception as e:
                logging.error(f"[ExchangeAdapter] Klaida gaunant klines {symbol}: {e}")
                return []
    # ------------------------------------------------------------
    # Rinkos duomenų pagalbiniai metodai
    # ------------------------------------------------------------
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Gauna tikslesnę paskutinę kainą per WS tiltą."""
        return ws_bridge.get_price(symbol)
    
    def get_paper_account(self) -> Optional[dict]:
        """Grąžina paper account būseną (tik DRY_RUN režimui)."""
        if self.dry_run:
            from core.paper_account import get_state  # ✅ VĖLYVAS IMPORTAS, kad išvengtume ciklo
            return get_state()
        return None

    def is_paper_mode(self) -> bool:
        """✅ PRIDĖTA: Patikrina ar veikia paper režime."""
        return self.dry_run

    # ❌ PAŠALINTA: Šios funkcijos nėra ir nereikia
    # def update_paper_account_on_sell(self, symbol, qty, entry_price, exit_price, usdc_gain):
    #     pass
    
# ------------------------------------------------------------
# Global adapter factory
# ------------------------------------------------------------
ADAPTER: Optional[ExchangeAdapter] = None

def get_adapter() -> ExchangeAdapter:
    global ADAPTER
    if ADAPTER is None:
        try:
            # Fiksuotas init - pašalintas dublikatas
            ADAPTER = ExchangeAdapter(
                CONFIG.get("API_KEY", ""), 
                CONFIG.get("API_SECRET", "")
            )
        except Exception as e:
            logging.error(f"[ExchangeAdapter] FATAL: Nepavyko inicializuoti adapterio: {e}")
            raise RuntimeError("Nepavyko inicializuoti ExchangeAdapter. Patikrinkite ENV failą.")
    return ADAPTER