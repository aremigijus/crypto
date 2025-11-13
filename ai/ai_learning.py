# FILE: ai/ai_learning.py
# ============================================================
# AI mokymosi būsena ir adaptacija (DB-only versija)
# Atnaujinta: 2025-11-13 (JSON failų I/O logika pašalinta, reikalinga DB persistencija)
# ============================================================

import logging
from datetime import datetime
from typing import Any, Dict

# IŠTRINTOS: Visos JSON failų konstantos ir pagalbinės funkcijos (_safe_load, _safe_dump).
# Būsena dabar veikia tik atmintyje (RAM).


class AILearningState:
    """
    Aukštesnio lygio būsena adaptacijai.
    PASTABA: Šios klasės duomenys šiuo metu nebus persistinami,
    kadangi JSON I/O buvo pašalintas. Persistencijai reikia atnaujinti
    įrašymą į DB.
    """
    def __init__(self):
        self._state: Dict[str, Any] = {}
        logging.warning("[AILearningState] JSON failų naudojimas pašalintas. Būsena nepersistinama!")

    def get(self) -> Dict[str, Any]:
        """Grąžina dabartinę atminties būseną."""
        return self._state

    def set_value(self, key: str, value: Any):
        """Atnaujina būsenos reikšmę atmintyje."""
        self._state[key] = value

    def save(self):
        """Išsaugojimas į DB turi būti įgyvendintas čia, bet JSON logika pašalinta."""
        pass

# Globalus objektas
AILearningState = AILearningState()

def get_learning_state() -> Dict[str, Any]:
    """Grąžina globalų AILearningState objektą."""
    return AILearningState.get()

def record_trade_for_learning(symbol: str, action: str, entry_price: float, exit_price: float,
                              pnl_pct: float, pnl_usd: float, confidence: float,
                              hold_time_h: float, market_state: str):
    """
    Įrašo prekybos rezultatus į atminties būseną.
    Sandoriai į 'trades' DB lentelę įrašomi per OrderExecutor/ExitManager.
    """
  
    AILearningState.set_value("last_trade_ts", datetime.utcnow().isoformat())
    AILearningState.set_value("last_pnl_pct", pnl_pct)
    AILearningState.set_value("last_confidence", confidence)