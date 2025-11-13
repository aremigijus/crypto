# ============================================================
# notify/notifier.py — Centralizuota pranešimų sistema su throttling + Telegram
# Atnaujinta: 2025-11-03
# ============================================================

import time
import logging
from datetime import datetime

try:
    from notify.telegram import send_telegram_message
    _HAS_TELEGRAM = True
except Exception:
    _HAS_TELEGRAM = False

_LAST_NOTIFY_TS = {}
_THROTTLE_SEC = {
    "BUY": 300,
    "SELL": 30,
    "RISK": 120,
    "INFO": 60,
    "DEFAULT": 30
}

def notify(message: str, category: str = "DEFAULT", force: bool = False):
    global _LAST_NOTIFY_TS
    now = time.time()
    category = category.upper().strip()

    throttle = _THROTTLE_SEC.get(category, _THROTTLE_SEC["DEFAULT"])
    last_ts = _LAST_NOTIFY_TS.get(category, 0)
    if not force and (now - last_ts) < throttle:
        logging.debug(f"[Notify] ⏳ Praleista (throttle) {category}: {message}")
        return False

    ts = datetime.utcnow().strftime("%H:%M:%S")
    logging.info(f"[{ts}] [{category}] {message}")

    if _HAS_TELEGRAM:
        try:
            send_telegram_message(f"[{category}] {message}")
        except Exception as e:
            logging.warning(f"[Notify] Telegram klaida: {e}")

    _LAST_NOTIFY_TS[category] = now
    return True
