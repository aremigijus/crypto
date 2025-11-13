# ============================================================
# ai/ai_boost_layer.py — AI Confidence Booster pagal volatilumą
# Atnaujinta: 2025-11-10 (Safe AI v6.5)
# ------------------------------------------------------------
# Pataisymai:
# - Dinaminis BOOST_THRESHOLD (pagal AI_CONFIDENCE_THRESHOLD)
# - Apsauga nuo per mažo confidence ir per didelio vol
# - Daugiau logų ir aiškesnė skalė
# ============================================================

import math
import json
import time
import logging
import threading
from statistics import pstdev, mean
from typing import List, Dict
from pathlib import Path
from core.config import CONFIG
from core.ws_bridge import get_price_history

LOG_PATH = Path("data") / "boost_activity.log"


def _compute_volatility(symbol: str, period: int = 24) -> float:
    """Apskaičiuoja paskutinių N valandų kainų procentinį svyravimą (stdev)."""
    try:
        ohlcv = get_price_history(symbol, interval="1h", limit=period)
        closes = [float(x["close"]) for x in ohlcv if "close" in x]
        if len(closes) < 5:
            return 0.0
        returns = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
        return round(pstdev(returns), 2)
    except Exception as e:
        logging.warning(f"[AI-BOOST] Nepavyko apskaičiuoti volatilumo {symbol}: {e}")
        return 0.0


def boost_signals(signals: List[Dict]) -> List[Dict]:
    """Padidina confidence ir edge reikšmes pagal rinkos volatilumą."""
    settings = CONFIG.get("AI_SETTINGS", {})
    if not settings.get("BOOST_ENABLED", False):
        return signals

    base_thr = float(CONFIG.get("AI_CONFIDENCE_THRESHOLD", 0.55))
    boost_thr = float(settings.get("BOOST_THRESHOLD", base_thr + 0.2))
    vol_ceiling = float(settings.get("VOLATILITY_CEILING_PCT", 8.0))
    boost_max = 0.15
    vol_low = 2.0

    boosted, telemetry = [], []

    for s in signals:
        sym = s.get("symbol")
        conf = float(s.get("confidence", 0))
        edge = float(s.get("edge", 0))
        if not sym:
            continue

        vol = _compute_volatility(sym)
        if vol <= 0:
            boosted.append(s)
            continue

        # Boost skalė pagal volatilumą
        if vol >= vol_ceiling:
            boost_factor = 1.0 + boost_max
        elif vol <= vol_low:
            boost_factor = 1.0 - 0.10
        else:
            scale = (vol - vol_low) / (vol_ceiling - vol_low)
            boost_factor = 1.0 + (scale * boost_max * 0.8)

        new_conf = round(conf * boost_factor, 3)
        new_conf = min(1.0, new_conf)
        if new_conf < 0.1:
            new_conf = 0.1

        # Papildomas edge didinimas jei confidence > slenksčio
        if new_conf > boost_thr:
            edge *= 1.1

        boosted_sig = {
            **s,
            "confidence": new_conf,
            "edge": round(edge, 4),
            "volatility_pct": vol,
        }
        boosted.append(boosted_sig)

        telemetry.append({
            "symbol": sym,
            "volatility": vol,
            "conf_before": conf,
            "conf_after": new_conf,
            "edge_after": edge,
        })
        logging.info(f"[AI-BOOST] {sym}: vol={vol:.2f}% → conf {conf:.3f} → {new_conf:.3f}")

    _log_telemetry(telemetry)
    return boosted


def _log_telemetry(data: List[Dict]):
    """Įrašo suvestinę į boost_activity.log."""
    try:
        if not data:
            return
        avg_vol = mean([d["volatility"] for d in data])
        avg_conf_b = mean([d["conf_before"] for d in data])
        avg_conf_a = mean([d["conf_after"] for d in data])
        record = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "avg_volatility": round(avg_vol, 2),
            "avg_conf_before": round(avg_conf_b, 3),
            "avg_conf_after": round(avg_conf_a, 3),
            "count": len(data)
        }
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.warning(f"[AI-BOOST] Telemetry įrašymo klaida: {e}")


def _auto_log_loop():
    """Kas valandą įrašo heartbeat į boost_activity.log."""
    while True:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "heartbeat": True}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        time.sleep(3600)


threading.Thread(target=_auto_log_loop, daemon=True).start()
