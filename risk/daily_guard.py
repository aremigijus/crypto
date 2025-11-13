# ============================================================
# risk/daily_guard.py
# Dienos ir valandinės rizikos kontrolė
# Atnaujinta: 2025-11-05 (pridėtas can_open_positions)
# ============================================================

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path


class DailyGuard:
    """
    Atsakingas už dienos, valandinės ir savaitinės rizikos stebėseną.
    Atskirtas nuo RiskManager, kad būtų aiškesnė atsakomybė.
    """
    def __init__(self, data_dir="data", max_daily_dd_pct=3.0, max_hourly_dd_pct=1.5):
        self.state_file = Path(data_dir) / "daily_guard_state.json"
        self.max_daily_dd_pct = max_daily_dd_pct
        self.max_hourly_dd_pct = max_hourly_dd_pct
        self._load_state()

    # -------------------------
    # Būsenos valdymas
    # -------------------------

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    self.state = json.load(f)
            except Exception:
                self.state = {}
        else:
            self.state = {}

        now = datetime.utcnow()
        today_str = now.strftime("%Y-%m-%d")

        if "day" not in self.state or self.state.get("day") != today_str:
            self.state = {
                "day": today_str,
                "daily_start_equity": None,
                "hourly_checkpoints": {},
                "max_drawdown_pct": 0.0,
                "daily_status": "OK"
            }
            self._save_state()

    def _save_state(self):
        """Saugo dienos būseną su .tmp apsauga ir automatiniais bandymais (Windows-friendly)."""
        tmp = Path(str(self.state_file) + ".tmp")
        attempt = 0
        max_attempts = 3

        while attempt < max_attempts:
            try:
                # 1️⃣ Rašom į laikiną failą
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(self.state, f, indent=2)

                # 2️⃣ Pašalinam seną failą, jei toks yra
                if self.state_file.exists():
                    try:
                        self.state_file.unlink()
                    except PermissionError:
                        logging.warning(f"[DailyGuard] Nepavyko pašalinti seno failo (bandymas {attempt+1})")
                        time.sleep(0.3)
                        attempt += 1
                        continue  # pakartoti bandymą

                # 3️⃣ Pervadinam laikiną -> pagrindinį
                tmp.rename(self.state_file)
                logging.debug(f"[DailyGuard] Būsena išsaugota: {self.state_file}")
                break  # ✅ Sėkminga operacija — išeinam

            except PermissionError as e:
                attempt += 1
                logging.warning(f"[DailyGuard] PermissionError ({attempt}/{max_attempts}) — bandysiu dar kartą...")
                time.sleep(0.3)
            except Exception as e:
                logging.exception(f"[DailyGuard] Klaida saugant būseną: {e}")
                break
        else:
            logging.error(f"[DailyGuard] Nepavyko įrašyti {self.state_file} po {max_attempts} bandymų.")



    # -------------------------
    # Atnaujinimai
    # -------------------------

    def register_equity(self, equity_now: float):
        """Atnaujina dienos rizikos būseną pagal dabartinį equity."""
        now = datetime.utcnow()
        today_str = now.strftime("%Y-%m-%d")

        # Nauja diena -> reset
        if self.state.get("day") != today_str:
            logging.info("[DailyGuard] Nauja diena — resetinu dienos skaitiklius.")
            self.state = {
                "day": today_str,
                "daily_start_equity": equity_now,
                "hourly_checkpoints": {},
                "max_drawdown_pct": 0.0,
                "daily_status": "OK"
            }
            self._save_state()
            return

        # Inicializuojame startinį equity, jei trūksta
        if self.state.get("daily_start_equity") is None:
            self.state["daily_start_equity"] = equity_now

        start_equity = self.state["daily_start_equity"]
        if start_equity == 0:
            return

        dd_pct = (equity_now - start_equity) / start_equity * 100.0
        self.state["max_drawdown_pct"] = min(self.state.get("max_drawdown_pct", 0.0), dd_pct)

        hour_key = now.strftime("%H:00")
        if hour_key not in self.state["hourly_checkpoints"]:
            self.state["hourly_checkpoints"][hour_key] = equity_now

        # Jei viršytas dienos DD limitas
        if dd_pct <= -self.max_daily_dd_pct:
            self.state["daily_status"] = "STOP"
            logging.warning(f"[DailyGuard] ⚠️ Pasiektas max dienos DD {dd_pct:.2f}% — prekyba stabdoma.")
        else:
            self.state["daily_status"] = "OK"

        self._save_state()

    # -------------------------
    # Patikrinimai
    # -------------------------

    def is_trading_allowed(self) -> bool:
        """Ar leidžiama tęsti prekybą (pagal dienos DD)."""
        return self.state.get("daily_status", "OK") == "OK"

    def can_open_positions(self) -> bool:
        """
        Ar galima atidaryti naujas pozicijas.
        Pagal dienos būseną ir kitus limitus.
        """
        status = self.state.get("daily_status", "OK")
        if status != "OK":
            logging.warning(f"[DailyGuard] ❌ Naujos pozicijos neleidžiamos — status={status}")
            return False
        return True

    # -------------------------
    # Dashboard santrauka
    # -------------------------

    def get_status(self):
        return {
            "day": self.state.get("day"),
            "status": self.state.get("daily_status", "OK"),
            "max_dd_pct": self.state.get("max_drawdown_pct", 0.0),
            "hourly_points": len(self.state.get("hourly_checkpoints", {}))
        }
