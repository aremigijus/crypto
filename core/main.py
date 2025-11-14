# core/main.py
# ============================================================
# core/main.py — AI valdomas prekybos botas (Safe AI v7.1, DB režimas)
# ============================================================

import time
import logging
import numpy as np
from datetime import datetime, timezone
from dotenv import load_dotenv
from core.db_init import init_full_db
from core.order_executor import OrderExecutor
from core.exchange_adapter import get_adapter
from core.ws_bridge import start_ws_auto, get_all_prices, is_connected
from core.position_sanitizer import PositionSanitizer
from notify.notifier import notify
from risk.risk_manager import RiskManager, RiskConfig
from ai.ai_signals import get_trade_signals
from ai.ai_performance import get_ai_performance
from core.exit_manager import ExitManager
from core.config import CONFIG

def ema(series, period):
    if not series or len(series) < period:
        return None
    import numpy as _np
    weights = _np.exp(_np.linspace(-1., 0., period))
    weights /= weights.sum()
    return _np.convolve(series, weights, mode="valid")[-1]


def get_trend(prices_list: list) -> str:
    tf_cfg = CONFIG.get("TREND_FILTER", {})
    if not tf_cfg.get("ENABLED", True):
        return "NEUTRAL"
    ema_fast_n = int(tf_cfg.get("EMA_FAST", 9))
    ema_slow_n = int(tf_cfg.get("EMA_SLOW", 50))
    bias_up = float(tf_cfg.get("TREND_UP_BIAS", 0.0005))
    bias_down = float(tf_cfg.get("TREND_DOWN_BIAS", -0.0005))
    if len(prices_list) < ema_slow_n:
        return "NEUTRAL"
    ema_fast = ema(prices_list[-ema_fast_n:], ema_fast_n)
    ema_slow = ema(prices_list[-ema_slow_n:], ema_slow_n)
    if ema_fast is None or ema_slow is None:
        return "NEUTRAL"
    diff = (ema_fast / ema_slow) - 1
    if diff >= bias_up:
        return "UP"
    elif diff <= bias_down:
        return "DOWN"
    return "NEUTRAL"


def main_loop():
    load_dotenv()
    init_full_db()  # užtikrina DB struktūrą

    logging.info("🚀 Starting Bot (DB režimas)")

    try:
        notify("🤖 CRYPTO BOT STARTUOJA — inicializuojamas adapteris ir WS.")
    except Exception:
        pass

    # --- Adapteris
    exchange = get_adapter()

    # --- WS režimo parinkimas iš CONFIG
    use_testnet = bool(CONFIG.get("USE_TESTNET", True))
    mode_label = "MAINNET" if not use_testnet else "TEST"

    logging.info(f"[INIT] Paleidimo režimas: {mode_label} (dry_run={exchange.dry_run})")
    start_ws_auto(testnet=use_testnet)

    for i in range(30):
        if is_connected():
            logging.info(f"✅ [INIT] WS prisijungė po {i+1}s.")
            break
        logging.info(f"[INIT] Laukiama WS prisijungimo... ({i+1}/30)")
        time.sleep(1.0)

    # --- Rizika
    rc = RiskConfig(
        daily_max_loss_pct=float(CONFIG.get("DAILY_MAX_DRAWDOWN_PCT", 2.0)),
        tp_base=float(CONFIG.get("EXIT", {}).get("TP_BASE", 0.06)),
        sl_base=float(CONFIG.get("EXIT", {}).get("SL_BASE", 0.02)),
        tsl_base=float(CONFIG.get("EXIT", {}).get("TSL_BASE", 0.015)),
        min_hold_time_h=float(CONFIG.get("EXIT", {}).get("MIN_HOLD_TIME_H", 0.083)),
        ai_exit_min_hold_h=float(CONFIG.get("EXIT", {}).get("AI_EXIT_MIN_HOLD_H", 0.167)),
        hold_timeout_h=float(CONFIG.get("EXIT", {}).get("HOLD_TIMEOUT_H", 12)),
        max_hold_h=float(CONFIG.get("EXIT", {}).get("MAX_HOLD_H", 24)),
        vol_scale=bool(CONFIG.get("EXIT", {}).get("VOL_SCALE", True)),
        confidence_scale=bool(CONFIG.get("EXIT", {}).get("CONFIDENCE_SCALE", True)),
        max_positions=int(CONFIG.get("PORTFOLIO", {}).get("MAX_OPEN_POSITIONS", 8)),
        max_exposure_pct=float(CONFIG.get("PORTFOLIO", {}).get("MAX_EXPOSURE_PCT", 85.0)),
    )
    
    # ✅ PRIDĖTA: Apsauga nuo RiskManager klaidų
    try:
        risk = RiskManager(rc, exchange=exchange, dry_run=exchange.dry_run)
    except Exception as e:
        logging.error(f"[MAIN] Klaida inicializuojant RiskManager: {e}")
        logging.info("[MAIN] Naudojamas paprastas rizikos valdymas...")
        # Sukuriam paprastą rizikos valdymą
        class SimpleRiskManager:
            def __init__(self):
                self.summary = {"guard_status": "OK", "pnl_today": 0.0}
            def update_equity(self, equity): pass
            def get_summary(self): return self.summary
            def has_position(self, symbol): 
                from core.paper_account import get_open_positions
                positions = get_open_positions()
                return symbol in positions
        risk = SimpleRiskManager()

    order_executor = OrderExecutor(exchange=exchange, daily_guard=risk)
    
    # ✅ PRIDĖTA: Apsauga nuo ExitManager klaidų
    try:
        exit_manager = ExitManager(risk_cfg=rc, order_executor=order_executor, paper_account=exchange.get_paper_account())
    except Exception as e:
        logging.error(f"[MAIN] Klaida inicializuojant ExitManager: {e}")
        # Sukuriam paprastą exit managerį
        class SimpleExitManager:
            def check_exits(self, prices): return 0
        exit_manager = SimpleExitManager()
    
    sanitizer = PositionSanitizer(check_interval_sec=15)
    
    # ✅ PRIDĖTA: Apsauga nuo AI Performance klaidų
    try:
        ai_perf = get_ai_performance()
        logging.info("[MAIN] ✅ Equity tracker aktyvus (AI Performance)")
        ai_perf.record_equity()
    except Exception as e:
        logging.warning(f"[MAIN] AI Performance neprieinama: {e}")
        ai_perf = None

    # Pradinė būsena
    st0 = exchange.get_paper_account() or {}
    equity_now = float(st0.get("equity", 10000.0))  # ✅ PATAISYTA: naudoti 'equity' vietoj 'equity_now'
    risk.update_equity(equity_now)
    
    try:
        notify(f"✅ [BOT READY] Paleista sėkmingai ({mode_label}, dry_run={exchange.dry_run})")
    except Exception:
        pass

    # AISizer
    if CONFIG.get("SIZER_DEBUG_ENABLED", False):
        from ai.ai_sizer_debug import AISizerDebug as AISizer
    else:
        from ai.ai_sizer import AISizer
    sizer = AISizer(CONFIG)

    # Filtrai
    conf_thresh = float(CONFIG.get("AI_CONFIDENCE_THRESHOLD", 0.7))
    edge_min = float(CONFIG.get("EDGE_MIN_PCT", 0.0015))
    min_per_trade = float(CONFIG.get("MIN_PER_TRADE_USDC", 25))
    tf_enabled = True

    if CONFIG.get("DRY_RUN", True):
        conf_thresh = 0.25
        edge_min = 0.0001
        tf_enabled = False
        logging.info("[MAIN] 🧪 DRY_RUN: sušvelninti filtrai (conf>=0.25, edge>=0.0001, trend=off)")

    iteration = 0
    price_history = {}

    # Periodinis equity įrašymas
    try:
        from core.equity_tracker import start_equity_auto_tracker
        start_equity_auto_tracker(interval_sec=300)
    except Exception as e:
        logging.warning(f"[MAIN] Equity tracker neprieinamas: {e}")

    # ======= PAGRINDINIS CIKLAS =======
    while True:
        try:
            iteration += 1

            # Atnaujinti equity
            st = exchange.get_paper_account() or {}
            equity_now = float(st.get("equity", 0.0))  # ✅ PATAISYTA: naudoti 'equity'
            risk.update_equity(equity_now)

            # Guard status
            rsum = risk.get_summary() or {}
            guard_status = str(rsum.get("guard_status") or "OK").upper()
            if guard_status == "STOP":
                # tikrinam bent EXIT'us
                prices = get_all_prices() or {}
                exit_manager.check_exits(prices)
                time.sleep(2.0)
                continue

            # Kainos
            prices = get_all_prices() or {}
            usdc_symbols = [s for s in prices.keys() if s.endswith("USDC")]
            if not usdc_symbols:
                time.sleep(2)
                continue

            # Price history
            for sym, pi in prices.items():
                p = pi.get("price") if isinstance(pi, dict) else pi
                try:
                    p = float(p)
                except Exception:
                    p = None
                if p:
                    arr = price_history.setdefault(sym, [])
                    arr.append(p)
                    if len(arr) > 200:
                        arr.pop(0)

            # Signalai
            signals = []
            min_liq = float(CONFIG.get("MIN_LIQUIDITY_USDC", 100))
            for sym in usdc_symbols:
                pi = prices.get(sym, {})
                vol = pi.get("quoteVolume") or pi.get("volume_usdc") or 0
                if vol and float(vol) < min_liq:
                    continue
                sigs = get_trade_signals(symbol=sym)
                if sigs:
                    signals.extend(sigs)

            buys = [s for s in signals if str(s.get("direction", "")).upper() == "BUY"]
            sells = [s for s in signals if str(s.get("direction", "")).upper() == "SELL"]

            # Fallback test signal (jei reikia)
            if not buys and (CONFIG.get("DEBUG_FORCE_SIGNALS", True) or CONFIG.get("DRY_RUN", True)):
                import random
                test_sym = random.choice(["BTCUSDC", "ETHUSDC", "SOLUSDC", "BNBUSDC"])
                buys = [{
                    "symbol": test_sym,
                    "direction": "BUY",
                    "confidence": 0.7,
                    "edge": 0.0015,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
                logging.info(f"[AI] 📊 Sugeneruotas testinis signalas {test_sym}")

            # Filtravimas
            valid = []
            for s in buys:
                conf = float(s.get("confidence", 0))
                edge = float(s.get("edge", 0))
                if conf < conf_thresh or edge < edge_min:
                    continue
                sym = s["symbol"]
                trend = get_trend(price_history.get(sym, [])) if tf_enabled else "UP"
                if trend != "UP":
                    continue
                valid.append(s)

            # Pirkimai (vietų skaičiaus ir laisvų lėšų kontrolė per DB)
            if valid:
                import sqlite3
                from core.db_manager import DB_PATH

                state_now = exchange.get_paper_account() or {}
                free_cash = float(state_now.get("free_usdc", 0.0))  # ✅ PATAISYTA: naudoti 'free_usdc'

                try:
                    con = sqlite3.connect(DB_PATH)
                    cur = con.cursor()
                    open_cnt = int(cur.execute("SELECT COUNT(*) FROM positions WHERE state='OPEN' AND qty>0;").fetchone()[0])
                    con.close()
                except Exception:
                    open_cnt = 0
                slots_left = max(0, int(rc.max_positions) - open_cnt)

                valid.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                for sig in valid[:slots_left]:
                    sym = sig["symbol"]
                    price_obj = prices.get(sym, {})
                    mid_price = price_obj.get("price") if isinstance(price_obj, dict) else None
                    if not mid_price:
                        mid_price = exchange.get_price(sym)
                    if not mid_price:
                        continue

                    q_amt = sizer.quote_for_signal(
                        symbol=sym,
                        confidence=float(sig["confidence"]),
                        edge=float(sig["edge"]),
                        price=float(mid_price),
                        free_cash=float(free_cash),
                        equity=float(equity_now),
                        open_positions={},
                        slots_left=slots_left,
                        daily_pnl_pct=float(rsum.get("pnl_today", 0.0)),
                    )

                    if q_amt < min_per_trade or q_amt > free_cash:
                        continue

                    res = order_executor.market_buy(
                        symbol=sym,
                        quote_amount=float(q_amt),
                        expected_edge_pct=float(sig["edge"]),
                        ai_confidence=float(sig["confidence"]),
                    )
                    if res and res.get("ok", False):  # ✅ PATAISYTA: patikrinti ar res nėra None
                        try:
                            notify(f"🟢 BUY {sym} @ {res.get('price', 0):.6f} ({q_amt:.2f} USDC)")
                        except Exception:
                            pass
                        free_cash -= float(q_amt)
                        slots_left -= 1
                        if slots_left <= 0 or free_cash <= min_per_trade:
                            break

            # AUTO EXIT
            auto_exits = exit_manager.check_exits(prices)

            # AI SELL
            for s in sells:
                sym = s.get("symbol")
                if not sym or not risk.has_position(sym):
                    continue
                try:
                    qty = float(order_executor.get_available_qty(sym) or 0.0)
                except Exception:
                    qty = 0.0
                if qty > 0:
                    res = order_executor.market_sell(
                        symbol=sym,
                        base_qty=qty,
                        expected_edge_pct=float(s.get("edge", 0)),
                        ai_confidence=float(s.get("confidence", 0)),
                        allow_partial=True,
                        reason="AI SELL",
                    )
                    if res and res.get("ok", False):  # ✅ PATAISYTA: patikrinti ar res nėra None
                        try:
                            notify(f"🔴 SELL {sym} (AI SELL)")
                        except Exception:
                            pass

            # Periodiškai — equity metrika į AI Performance
            if iteration % 10 == 0 and ai_perf:
                try:
                    ai_perf.record_equity()
                except Exception:
                    pass

            # Sanitizer
            try:
                sanitizer.maybe_run(exchange, risk)
            except Exception:
                pass

            if iteration % 5 == 0:
                logging.info(f"[LOOP] Iter={iteration:04d} | Equity={equity_now:.2f}")

            time.sleep(2.0)

        except Exception as e:
            logging.exception(f"[MAIN_LOOP] Klaida: {e}")
            time.sleep(3.0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        main_loop()
    except Exception as e:
        logging.exception(f"[DEBUG] Klaida pagrindiniame cikle: {e}")
    finally:
        logging.warning("[DEBUG] Pabaiga pasiekta (main_loop baigė darbą)")