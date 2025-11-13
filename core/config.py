# core/config.py
# Visiškai supaprastintas konfigūracijų valdymas (tik JSON, be funkcijų)

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# ----------------------------------------------------
# Įkeliame konfigūraciją vieną kartą
# ----------------------------------------------------
try:
    CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
except Exception:
    CONFIG = {}

# ----------------------------------------------------
# Pagalbinė funkcija išsaugoti (naudojama tik API pusėje)
# ----------------------------------------------------
def save_config(new_config: dict):
    CONFIG_PATH.write_text(json.dumps(new_config, indent=2), encoding="utf-8")
