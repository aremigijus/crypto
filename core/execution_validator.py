# ============================================================
# core/execution_validator.py
# Safe AI v4 (konservatyvus režimas, 2025-11-04)
# Tikslas:
#  1) PRIEŠ ĮĖJIMĄ: patikrinti AI/edge, spread, likvidumą, slippage,
#     biržos lot/tick/minNotional taisykles, eksponavimo ribas ir grynųjų pakankamumą.
#  2) PO ĮVYKDYMO: įrašyti vykdymo kokybės metrikas (latency, slippage).
# ============================================================

from __future__ import annotations
import os
import json
import time
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

# send_telegram_message funkcijos apibrėžimas, kad nereikėtų JSON metrikų.
def send_telegram_message(msg: str):
    """Vieta, kurioje turi būti įgyvendinta Telegram žinutės siuntimo funkcija."""
    try:
        from notify.telegram import send_telegram_message as real_send
        real_send(msg)
    except Exception:
        pass

@dataclass
class Orderbook:
    bids: Optional[List[Tuple[float, float]]] = None
    asks: Optional[List[Tuple[float, float]]] = None


@dataclass
class EntryContext:
    symbol: str
    side: str
    price: float
    quote_balance: float
    quote_per_trade: float
    ai_confidence: Optional[float] = None
    edge_pct: Optional[float] = None
    rsi: Optional[float] = None
    momentum: Optional[float] = None
    open_positions_exposure_pct: Optional[float] = None
    per_asset_exposure_pct: Optional[float] = None
    orderbook: Optional[Orderbook] = None
    exchange_info: Optional[ExchangeInfo] = None
    config: Optional[Dict[str, Any]] = None
    recent_loss_pct: Optional[float] = None


# ============================================================
# Validatorius
# ============================================================

class ExecutionValidator:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg or {}
        self.min_liq_usdc = float(self._get("MIN_LIQUIDITY_USDC", 500.0))
        self.max_spread_bps = float(self._get("MAX_SPREAD_BPS", 10.0))
        self.max_slippage_bps = float(self._get("MAX_SLIPPAGE_BPS", 20.0))
        self.fee_taker = float(self._get("FEE_TAKER", 0.0006))
        self.ai_thr = float(self._get("AI_CONFIDENCE_THRESHOLD", 0.58))
        self.edge_min = float(self._get("EDGE_MIN_PCT", 0.001))
        self.rsi_on = bool(self._get("RSI_FILTER_ENABLED", True))
        self.rsi_min = float(self._get("RSI_MIN", 45))
        self.rsi_max = float(self._get("RSI_MAX", 75))
        self.max_total_exp_pct = float(self._get("MAX_TOTAL_EXPOSURE_PCT", 70.0))
        self.max_per_asset_pct = float(self._get("MAX_PER_ASSET_PCT", 20.0))
        self.capital_recov_dd_pct = float(self._get("CAPITAL_RECOVERY_PCT", 5.0))
        self.capital_recov_mult = float(self._get("CAPITAL_RECOVERY_SIZE_MULT", 0.5))

    # ========================================================
    def validate_entry(self, ctx: EntryContext) -> Tuple[bool, str, Dict[str, Any]]:
        if not ctx.symbol or not ctx.side:
            return self._fail("INVALID_CTX", {"msg": "trūksta symbol/side"})
        if ctx.price is None or ctx.price <= 0:
            return self._fail("INVALID_PRICE", {"price": ctx.price})

        # Capital recovery
        size_mult = 1.0
        if ctx.recent_loss_pct is not None and ctx.recent_loss_pct <= -abs(self.capital_recov_dd_pct):
            size_mult = self.capital_recov_mult

        # AI filtrai
        ai_ok, ai_reason, ai_det = self._check_ai_filters(ctx)
        if not ai_ok:
            return self._fail(ai_reason, ai_det)

        # Orderbook tikrinimas
        ob_ok, ob_reason, ob_det = self._check_orderbook(ctx)
        if not ob_ok:
            return self._fail(ob_reason, ob_det)

        # Lot/tick/minNotional
        lot_ok, lot_reason, lot_det = self._check_lot_rules(ctx, size_mult)
        if not lot_ok:
            return self._fail(lot_reason, lot_det)

        # Eksponavimas ir cash
        exp_ok, exp_reason, exp_det = self._check_exposure(ctx, size_mult)
        if not exp_ok:
            return self._fail(exp_reason, exp_det)

        details = {"size_mult": size_mult, **ai_det, **ob_det, **lot_det, **exp_det}
        return True, "OK", details

    # ========================================================
    def _check_ai_filters(self, ctx: EntryContext):
        if ctx.ai_confidence is not None and ctx.ai_confidence < self.ai_thr:
            return False, "AI_CONF_TOO_LOW", {"ai_conf": ctx.ai_confidence, "thr": self.ai_thr}
        if ctx.edge_pct is not None and ctx.edge_pct < self.edge_min:
            return False, "EDGE_TOO_LOW", {"edge_pct": ctx.edge_pct, "min_edge": self.edge_min}
        if self.rsi_on and ctx.rsi is not None and (ctx.rsi < self.rsi_min or ctx.rsi > self.rsi_max):
            return False, "RSI_OUT_OF_RANGE", {"rsi": ctx.rsi}
        return True, "OK", {}

    # ========================================================
    def _check_orderbook(self, ctx: EntryContext):
        ob = ctx.orderbook
        if not ob or not ob.bids or not ob.asks:
            return False, "NO_ORDERBOOK", {"msg": "trūksta orderbook depth"}

        try:
            best_bid = float(ob.bids[0][0])
            best_ask = float(ob.asks[0][0])
        except Exception:
            return False, "INVALID_ORDERBOOK", {"msg": "nepavyko nuskaityti BBO"}

        if best_ask <= 0 or best_bid <= 0 or best_ask <= best_bid:
            return False, "INVALID_BBO", {"bid": best_bid, "ask": best_ask}

        mid = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid * 10_000
        if spread_bps > self.max_spread_bps:
            return False, "SPREAD_TOO_WIDE", {"spread_bps": spread_bps}

        top_liq = self._top_liquidity_usdc(ob, 5, "ask")
        if top_liq < self.min_liq_usdc:
            return False, "LIQUIDITY_TOO_LOW", {"top_liq_usdc": top_liq}

        target_quote = ctx.quote_per_trade
        filled_quote, worst_px = self._simulate_take_fill(ob.asks, target_quote, fee=self.fee_taker)
        slip_bps = (worst_px - best_ask) / best_ask * 10_000
        if slip_bps > self.max_slippage_bps:
            return False, "SLIPPAGE_TOO_HIGH", {"slip_bps": slip_bps}

        return True, "OK", {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_bps": spread_bps,
            "slip_bps": slip_bps,
            "top_liq_usdc": top_liq
        }

    # ========================================================
    def _check_lot_rules(self, ctx: EntryContext, size_mult: float):
        exi = ctx.exchange_info or ExchangeInfo()
        quote = float((ctx.quote_per_trade or 0) * size_mult)
        qty_raw = quote / float(ctx.price)
        qty = self._round_step(qty_raw, exi.step_size) if exi.step_size else qty_raw
        px = self._round_tick(ctx.price, exi.tick_size) if exi.tick_size else ctx.price
        notional = qty * px
        if exi.min_notional and notional < exi.min_notional:
            return False, "MIN_NOTIONAL", {"notional": notional}
        if exi.min_qty and qty < exi.min_qty:
            return False, "MIN_QTY", {"qty": qty}
        if qty <= 0:
            return False, "QTY_ZERO", {"qty": qty}
        return True, "OK", {"qty": qty, "notional": notional}

    # ========================================================
    def _check_exposure(self, ctx: EntryContext, size_mult: float):
        total_exp = float(ctx.open_positions_exposure_pct or 0.0)
        asset_exp = float(ctx.per_asset_exposure_pct or 0.0)
        if total_exp > self.max_total_exp_pct:
            return False, "TOTAL_EXPOSURE_LIMIT", {"total": total_exp}
        if asset_exp > self.max_per_asset_pct:
            return False, "ASSET_EXPOSURE_LIMIT", {"asset": asset_exp}
        need = (ctx.quote_per_trade or 0) * size_mult
        if ctx.quote_balance < need:
            return False, "NO_CASH", {"have": ctx.quote_balance, "need": need}
        return True, "OK", {"total_exp": total_exp, "asset_exp": asset_exp}

    # ========================================================
    def _simulate_take_fill(self, asks: List[Tuple[float, float]], target_quote: float, fee: float):
        filled, remaining, worst_px = 0.0, target_quote, 0.0
        for px, qty in asks:
            level_quote = px * qty
            take = min(level_quote, remaining)
            filled += take * (1 - fee)
            worst_px = px
            remaining -= take
            if remaining <= 0:
                break
        return filled, worst_px

    def _top_liquidity_usdc(self, ob: Orderbook, depth_levels: int, side: str):
        levels = ob.asks if side == "ask" else ob.bids or []
        return sum(float(px) * float(qty) for px, qty in levels[:depth_levels])

    @staticmethod
    def _round_step(qty: float, step: float):
        if step and step > 0:
            return math.floor(qty / step) * step
        return qty

    @staticmethod
    def _round_tick(px: float, tick: float):
        if tick and tick > 0:
            return math.floor(px / tick) * tick
        return px

    def _fail(self, reason: str, details: Dict[str, Any]):
        print(f"[ENTRY_BLOCKED] {reason} | {details}")
        return False, reason, details

    def _get(self, key: str, default: Any):
        try:
            return self.cfg.get(key, default)
        except Exception:
            return default
