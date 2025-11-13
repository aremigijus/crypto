# ============================================================
# ai/ai_sizer.py — Dinaminis AI pozicijų dydžio skaičiuotuvas
# Atnaujinta: 2025-11-10 (Safe AI v6.6)
# ------------------------------------------------------------
# Nauja:
# - Pridėtas realus boost_avg ir vol_avg skaičiavimas
# - Saugi fallback logika jei nėra AI metrikų
# ============================================================

import math
import json
import logging
import statistics
from pathlib import Path
from core.config import CONFIG
from ai.ai_sizer_summary import get_ai_sizer_summary

class SizerConfig:
    def __init__(self,
                 base_risk_pct: float,
                 conf_min: float,
                 conf_max: float,
                 conf_scale_min: float,
                 conf_scale_max: float,
                 edge_ref: float,
                 edge_scale: float,
                 dd_slowdown_perc_per_1pct: float,
                 per_asset_soft_cap_pct: float,
                 min_notional: float):
        self.base_risk_pct = base_risk_pct
        self.conf_min = conf_min
        self.conf_max = conf_max
        self.conf_scale_min = conf_scale_min
        self.conf_scale_max = conf_scale_max
        self.edge_ref = edge_ref
        self.edge_scale = edge_scale
        self.dd_slowdown_perc_per_1pct = dd_slowdown_perc_per_1pct
        self.per_asset_soft_cap_pct = per_asset_soft_cap_pct
        self.min_notional = min_notional

    @classmethod
    def from_config(cls, cfg: dict):
        s = cfg.get("SIZER", {})
        p = cfg.get("PORTFOLIO", {})
        return cls(
            base_risk_pct=float(p.get("RISK_PER_TRADE_PCT", 0.0075)),
            conf_min=float(s.get("CONF_MIN", 0.55)),
            conf_max=float(s.get("CONF_MAX", 0.90)),
            conf_scale_min=float(s.get("CONF_SCALE_MIN", 0.6)),
            conf_scale_max=float(s.get("CONF_SCALE_MAX", 1.35)),
            edge_ref=float(s.get("EDGE_REF", 0.002)),
            edge_scale=float(s.get("EDGE_SCALE", 0.5)),
            dd_slowdown_perc_per_1pct=float(s.get("DD_SLOWDOWN_PERC_PER_1PCT", 0.15)),
            per_asset_soft_cap_pct=float(s.get("PER_ASSET_SOFT_CAP_PCT", 25.0)),
            min_notional=float(s.get("MIN_NOTIONAL", 5.0))
        )

class AISizer:
    def __init__(self, config=None):
        self.cfg = SizerConfig.from_config(config or CONFIG.all())
        logging.info("[AISizer] Inicializuotas dinaminis pozicijos dydžio modulis")

    def _scale_by_confidence(self, conf: float) -> float:
        c = max(min(conf, self.cfg.conf_max), self.cfg.conf_min)
        ratio = (c - self.cfg.conf_min) / (self.cfg.conf_max - self.cfg.conf_min)
        return self.cfg.conf_scale_min + ratio * (self.cfg.conf_scale_max - self.cfg.conf_scale_min)

    def _scale_by_edge(self, edge: float) -> float:
        if edge <= 0:
            return 0.0
        ratio = edge / self.cfg.edge_ref
        return 1.0 + (ratio - 1.0) * self.cfg.edge_scale

    def _scale_by_drawdown(self, dd_pct: float) -> float:
        if dd_pct <= 0:
            return 1.0
        return max(0.1, 1.0 - (dd_pct * self.cfg.dd_slowdown_perc_per_1pct))

    def compute_dynamic_limits(self, equity: float):
        min_usd = max(5.0, equity * 0.0025)
        max_usd = max(min_usd, equity * 0.05)
        return min_usd, max_usd

    def suggest_position_size(self, equity_now: float, conf: float, edge: float, dd_pct: float = 0.0):
        try:
            min_usd, max_usd = self.compute_dynamic_limits(equity_now)
            base_usd = equity_now * self.cfg.base_risk_pct
            conf_scale = self._scale_by_confidence(conf)
            edge_scale = self._scale_by_edge(edge)
            dd_scale = self._scale_by_drawdown(dd_pct)
            raw_size = base_usd * conf_scale * edge_scale * dd_scale
            return max(min(raw_size, max_usd), min_usd)
        except Exception as e:
            logging.exception(f"[AISizer] Klaida skaičiuojant dydį: {e}")
            return 0.0

    def quote_for_signal(self,
                         symbol: str,
                         confidence: float,
                         edge: float,
                         price: float,
                         free_cash: float,
                         equity: float,
                         open_positions: dict,
                         slots_left: int,
                         daily_pnl_pct: float = 0.0):
        try:
            dd_scale = 0.0 if daily_pnl_pct > 0 else abs(daily_pnl_pct)
            size = self.suggest_position_size(equity_now=equity, conf=confidence, edge=edge, dd_pct=dd_scale)

            if free_cash < size:
                size = free_cash * 0.9

            existing = sum(float(p.get("qty", 0)) * float(p.get("current_price", 0))
                           for p in open_positions.values())
            exposure_pct = existing / equity * 100 if equity > 0 else 0
            if exposure_pct > self.cfg.per_asset_soft_cap_pct:
                size *= 0.5

            if slots_left > 1:
                size *= 1.0 / slots_left

            size = max(size, self.cfg.min_notional)
            logging.info(f"[AISizer] {symbol}: conf={confidence:.2f}, edge={edge:.4f} → {size:.2f}USDC")
            return size
        except Exception as e:
            logging.exception(f"[AISizer] quote_for_signal() klaida: {e}")
            return 0.0

    # ========================================================\
    # 🧠 Papildoma: Boost / Volatility vidurkių analizė (DB-Only)
    # ========================================================\
    def get_ai_metrics_summary(self):
        """Grąžina AI metrikų santrauką iš DB per ai_sizer_summary modulį."""
        try:
            # Anksčiau naudojo ai_metrics.json. Dabar naudojame bendrą santrauką iš DB.
            summary = get_ai_sizer_summary()
            return {
                "boost_avg": summary.get("boost_avg", 0.0),
                "vol_avg": summary.get("vol_avg", 0.0),
            }
        except Exception as e:
            logging.exception(f"[AISizer] Klaida skaitant AI metrikas: {e}")
            return {"boost_avg": 0.0, "vol_avg": 0.0}