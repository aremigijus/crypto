# ============================================================
# core/exchange_adapter.py — Binance prekybos adapteris
# Atnaujinta: 2025-11-13 (DB-Only)
# ============================================================

import json
import time
import hmac
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import requests

from .config import CONFIG
from . import ws_bridge
import core.paper_account as PaperAccount

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

        if CONFIG.get("USE_TESTNET", False):
            # Šioje versijoje TESTNET nustatymų neturime, naudojame tik DRY_RUN
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
        if CONFIG.get("DRY_RUN", True):
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
            "symbol": symbol,
            "side": side,
            "qty": executed_qty,
            "fill_price": fill_price,
            "fee": fee,
            "timestamp": _now_str(),
            "dry_run": True, # Indikatorius, kad pavedimas buvo simuliuotas
            "reason": reason,
            "confidence": confidence,
        }
        
        # Atnaujiname PaperAccount būseną (per OrderExecutor perimamoji logika)
        # Grąžiname tik vykdymo rezultatą.
        logging.info(f"[DryRunOrder] ✅ {side} {executed_qty} {symbol} @ {fill_price:.2f} (simuliacija)")
        return result

    def _real_order(self, symbol: str, side: str, qty: float, reason: str, confidence: float) -> dict:
        """Vykdo realų pavedimą per Binance API."""
        try:
            ts = _timestamp_ms()
            order_type = "MARKET"
            
            # Binance API reikalauja, kad pardavimo (SELL) pavedimuose būtų nurodomas
            # bazinės monetos kiekis (pvz., BTC, jei symbol yra BTCUSDC).
            # Pirkimo (BUY) atveju galėtų būti naudojamas QUOTE ORDER QTY, bet paprastumo dėlei
            # čia naudojame tik kiekį (qty) ir MARKET tipo pavedimą.
            
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
            # Ieškome vidutinės fill kainos. Jei yra 'fills' laukas, naudojame pirmo fill kainą
            # arba geriausiu atveju grąžintą 'price'
            fill_price = float(data.get("fills", [{}])[0].get("price", data.get("price", ws_bridge.get_price(symbol))))
            
            # Apskaičiuojame mokestį (naudojame 'taker' mokesčio normą)
            fee = executed_qty * fill_price * self.fee_taker
            
            result = {
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
            logging.info(f"[BinanceOrder] ✅ {side} {executed_qty} {symbol} @ {fill_price:.2f}")
            return result
        
        except Exception as e:
            logging.exception(f"[BinanceAdapter] Klaida vykdant pavedimą {symbol}: {e}")
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------
    # Rinkos duomenų pagalbiniai metodai
    # ------------------------------------------------------------
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Gauna tikslesnę paskutinę kainą per WS tiltą."""
        return ws_bridge.get_price(symbol)
    
    def get_paper_account(self) -> Optional[dict]:
        """Grąžina paper account būseną (tik DRY_RUN režimui)."""
        if CONFIG.get("DRY_RUN", True):
            return PaperAccount.get_state()
        return None
    
# ------------------------------------------------------------
# Global adapter factory
# ------------------------------------------------------------
ADAPTER: Optional[ExchangeAdapter] = None

def get_adapter() -> ExchangeAdapter:
    global ADAPTER
    if ADAPTER is None:
        # Apsauga, jei CONFIG.py dar nespėjo įsikelti
        try:
            # Pakeistas init, nenaudojame get() su numatytomis vertėmis (bus klaida, jei nėra ENV)
            ADAPTER = ExchangeAdapter(CONFIG.get("API_KEY", ""), CONFIG.get("API_SECRET", ""))
        except Exception as e:
            logging.error(f"[ExchangeAdapter] FATAL: Nepavyko inicializuoti adapterio: {e}")
            raise RuntimeError("Nepavyko inicializuoti ExchangeAdapter. Patikrinkite ENV failą.")
    return ADAPTER
    global ADAPTER
    if ADAPTER is None:
        # Apsauga, jei CONFIG.py dar nespėjo įsikelti
        try:
            ADAPTER = ExchangeAdapter(CONFIG.get("API_KEY", ""), CONFIG.get("API_SECRET", ""))
        except Exception as e:
            logging.exception(f"Klaida kuriant ExchangeAdapter: {e}")
            ADAPTER = ExchangeAdapter("", "") # Tuščias adapteris

    return ADAPTER