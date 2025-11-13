# ============================================================
# ai/ai_sizer_debug.py — Pozicijos dydžio skaičiavimas (debug)
# Atnaujinta: 2025-11-10 (Safe AI v6.5)
# ============================================================

import os
import json
import math
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Any, Optional
from core.config import CONFIG

@dataclass
class SizerConfig:
    min_per_trade_usdc: float = 25.0
    max_allocation_pct_per_trade: float = 0.12
    max_exposure_pct: float = 85.0
    conf_min: float = 0.55
    conf_max: float = 0.90
    conf_scale_min: float = 0.60
    conf_scale_max: float = 1.35
    edge_ref: float = 0.0020
    edge_scale: float = 0.50
    dd_slowdown_perc_per_1pct: float = 0.15
    per_asset_soft_cap_pct: float = 25.0
    min_notional: float = 5.0

    @staticmethod
    def from_config(cfg: Dict[str, Any]) -> "SizerConfig":
        s = cfg.get("SIZER", {})
        p = cfg.get("PORTFOLIO", {})
        return SizerConfig(
            min_per_trade_usdc=float(cfg.get("MIN_PER_TRADE_USDC", s.get("MIN_PER_TRADE_USDC", 25))),
            max_allocation_pct_per_trade=float(p.get("MAX_ALLOCATION_PCT_PER_TRADE", 0.12)),
            max_exposure_pct=float(p.get("MAX_EXPOSURE_PCT", 85.0)),
            conf_min=float(s.get("CONF_MIN", 0.55)),
            conf_max=float(s.get("CONF_MAX", 0.90)),
            conf_scale_min=float(s.get("CONF_SCALE_MIN", 0.60)),
            conf_scale_max=float(s.get("CONF_SCALE_MAX", 1.35)),
            edge_ref=float(s.get("EDGE_REF", 0.0020)),
            edge_scale=float(s.get("EDGE_SCALE", 0.50)),
            dd_slowdown_perc_per_1pct=float(s.get("DD_SLOWDOWN_PERC_PER_1PCT", 0.15)),
            per_asset_soft_cap_pct=float(s.get("PER_ASSET_SOFT_CAP_PCT", 25.0)),
            min_notional=float(s.get("MIN_NOTIONAL", 5.0)),
        )

def _linear_scale(x, x0, x1, y0, y1):
    if x1 == x0: return (y0 + y1) / 2
    t = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
    return y0 + t * (y1 - y0)

def _write_debug_log(data):
    try:
        os.makedirs("data", exist_ok=True)
        data["ts"] = datetime.utcnow().isoformat()
        with open("data/sizer_debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception:
        pass

class AISizerDebug:
    def __init__(self, config=None, debug_enabled=True):
        self.cfg = SizerConfig.from_config(config or CONFIG.all())
        self.debug_enabled = debug_enabled
        logging.info("[AISizerDebug] 🧩 Debug režimas įjungtas")

    def quote_for_signal(self, *, symbol, confidence, edge, price, free_cash, equity, open_positions, slots_left, daily_pnl_pct):
        if equity <= 0 or free_cash <= 0: return 0.0

        base = free_cash if slots_left <= 1 else free_cash / slots_left
        hard_cap = equity * self.cfg.max_allocation_pct_per_trade
        conf_scale = _linear_scale(confidence, self.cfg.conf_min, self.cfg.conf_max, self.cfg.conf_scale_min, self.cfg.conf_scale_max)
        edge_scale = 1.0 + ((edge / max(1e-9, self.cfg.edge_ref)) - 1.0) * self.cfg.edge_scale
        dd_factor = 1.0 if daily_pnl_pct >= 0 else max(0.5, 1.0 + daily_pnl_pct * self.cfg.dd_slowdown_perc_per_1pct)

        quote = base * conf_scale * edge_scale * dd_factor
        quote = min(quote, hard_cap, free_cash)
        if quote < max(self.cfg.min_per_trade_usdc, self.cfg.min_notional): quote = 0.0

        if self.debug_enabled:
            _write_debug_log({
                "symbol": symbol,
                "confidence": confidence,
                "edge": edge,
                "conf_scale": conf_scale,
                "edge_scale": edge_scale,
                "dd_factor": dd_factor,
                "slots_left": slots_left,
                "quote_final": quote
            })
        return round(quote, 2)
