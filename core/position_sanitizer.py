# ============================================================
# core/position_sanitizer.py — ExitManager ↔ PaperAccount sanitaras
# Tikslas: išvalyti "dangling" pozicijas ir loginti neatitikimus
# ============================================================

import time
import logging
from typing import Dict, Any

from notify.notifier import notify


class PositionSanitizer:
    """
    Periodiškai sulygina ExitManager būseną su PaperAccount:
      - jei ExitManager turi poziciją, bet PaperAccount qty == 0 → clear + notify
      - jei Pafor sym, strAccount turi poziciją, o ExitManager neturi → tik perspėjimas (paliekame žmogui/AI spręsti)
    """

    def __init__(self, check_interval_sec: int = 15):
        self.interval = int(check_interval_sec)
        self._last_run = 0.0

    def maybe_run(self, exchange, exit_manager) -> None:
        now = time.time()
        if now - self._last_run < self.interval:
            return
        self._last_run = now
        try:
            self._run_once(exchange, exit_manager)
        except Exception as e:
            logging.error(f"[PositionSanitizer] Klaida: {e}")

    # --------------------------------------------------------
    # Vidinė logika
    # --------------------------------------------------------
    def _run_once(self, exchange, exit_manager) -> None:
        pa = None
        try:
            pa = exchange.get_paper_account()  # dict arba None
        except Exception:
            pass

        if not pa or not isinstance(pa, dict):
            # jei nėra paper account (LIVE režimas) – nieko nedarom
            return

        positions: Dict[str, Any] = pa.get("positions", {}) or {}

        # 1) ExitManager → PaperAccount (dangling clear)
        for sym, st in getattr(exit_manager, "positions", {}).items():
            qty = float(positions.get(sym, {}).get("qty", 0.0))
            if qty <= 1e-12:
                exit_manager.clear(sym)
                msg = f"🧹 [Sanitizer] Išvalyta pakibusi pozicija {sym} (ExitManager turėjo, PaperAccount neturi)."
                logging.warning(msg)
                try:
                    notify(msg, level="warn")
                except Exception:
                    pass

        # 2) PaperAccount → ExitManager (missing registration)
        for sym, pos in positions.items():
            qty = float(pos.get("qty", 0.0))
            if qty > 1e-12 and not exit_manager.has_position(sym):
                # Kol kas tik perspėjimas (nenorim automatiškai spėlioti entry_price/lygių)
                msg = f"⚠️ [Sanitizer] PaperAccount turi {sym} qty={qty:.6f}, bet ExitManager neturi — patikrink registraciją."
                logging.warning(msg)
                try:
                    notify(msg, level="warn")
                except Exception:
                    pass
