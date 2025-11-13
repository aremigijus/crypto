# ============================================================
# core/ws_bridge.py — Binance WS tiltas + REST atsarginis režimas
# Atnaujinta: 2025-11-06 (pilna versija)
#
# Pataisymai:
# - WS endpoint pakeistas iš /stream į /ws (teisingas SUBSCRIBE/UNSUBSCRIBE naudojimui).
# - Išlaikyta adaptuota prenumerata (delta), dinaminis UNIVERSE (jei CONFIG["UNIVERSE"] tuščias),
#   heartbeat + backoff, REST fallback (TOP watchlist), 24h volume, orderbook REST.
#
# API nekeičiama:
#   start_ws_auto(limit=0, testnet=False, refresh_sec=120)
#   is_connected(), get_all_prices(), get_price(), get_orderbook_top(), stop_ws()
# ============================================================

import json
import time
import math
import random
import threading
import traceback
from typing import Dict, Tuple, List, Optional, Set

try:
    import websocket  # websocket-client
except Exception:
    websocket = None

import requests
from core.config import CONFIG

# Jei yra — naudosime dinaminę atranką
try:
    from core.universe_manager import select_universe as _dynamic_select_universe
except Exception:
    _dynamic_select_universe = None

# ------------------------------------------------------------
# Konfigai
# ------------------------------------------------------------
REST_TIMEOUT = 5
ORDERBOOK_DEPTH = 5

WS_PING_MIN_SEC = int(CONFIG.get("WS_PING_MIN_SEC", 3))
WS_PING_MAX_SEC = int(CONFIG.get("WS_PING_MAX_SEC", 5))
WS_PONG_TIMEOUT_SEC = float(CONFIG.get("WS_PONG_TIMEOUT_SEC", 3))
WS_BACKOFF_BASE_SEC = int(CONFIG.get("WS_BACKOFF_BASE_SEC", 1))
WS_BACKOFF_MAX_SEC = int(CONFIG.get("WS_BACKOFF_MAX_SEC", 60))
WS_BACKOFF_RESET_SEC = int(CONFIG.get("WS_BACKOFF_RESET_SEC", 120))

WS_STALE_SECONDS = int(CONFIG.get("REST_FALLBACK_STALE_SEC", 15))
REST_WATCHLIST_TOP = int(CONFIG.get("REST_WATCHLIST_TOP", 10))

# ------------------------------------------------------------
# Binance endpointai
#  - SUBSCRIBE/UNSUBSCRIBE reikia jungtis į /ws
#  - /stream be ?streams grąžina 404 (todėl nenaudojame)
# ------------------------------------------------------------
BINANCE_WS_MAIN = "wss://stream.binance.com:9443/ws"
BINANCE_WS_TEST = "wss://testnet.binance.vision/ws"

BINANCE_REST_MAIN = "https://api.binance.com"
BINANCE_REST_TEST = "https://testnet.binance.vision"

# ------------------------------------------------------------
# Būsenos saugykla (thread-safe)
# ------------------------------------------------------------
class _WSState:
    def __init__(self):
        self.lock = threading.RLock()
        self.connected = False
        self.last_update = 0.0

        # Kainų cache
        # { "BTCUSDC": {"price": mid, "bid": b, "ask": a, "ts": t, "volume_usdc": float} }
        self.price: Dict[str, Dict] = {}

        # Orderbook cache
        self.orderbook: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}

        self.ws: Optional["websocket.WebSocketApp"] = None
        self.stop = False

        # Prenumeratų ir atrankos dalis
        self.universe: List[str] = []      # target (norimas) sąrašas
        self.subscribed: Set[str] = set()  # realiai prenumeruojami

        self.use_testnet = False
        self.refresh_sec_arg = 120  # iš start_ws_auto()
        self.refresh_sec_cfg = max(60, int(CONFIG.get("UNIVERSE_REFRESH_MINUTES", 15)) * 60)
        self._testnet_failed_logged = False

        # Heartbeat/ping-pong
        self.last_pong = 0.0
        self.ping_fail_count = 0
        self.ping_window_start = 0.0

        # Reconnect backoff
        self.backoff_exp = 0
        self.backoff_last_reset = 0.0

STATE = _WSState()

# ------------------------------------------------------------
# REST helperiai
# ------------------------------------------------------------
def _rest_base() -> str:
    return BINANCE_REST_TEST if STATE.use_testnet or CONFIG.get("USE_TESTNET", False) else BINANCE_REST_MAIN

def _rest_get_bookticker(symbol: str) -> Optional[Dict]:
    try:
        url = f"{_rest_base()}/api/v3/ticker/bookTicker"
        r = requests.get(url, params={"symbol": symbol}, timeout=REST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def _rest_get_depth(symbol: str, limit: int = ORDERBOOK_DEPTH) -> Optional[Dict]:
    try:
        url = f"{_rest_base()}/api/v3/depth"
        r = requests.get(url, params={"symbol": symbol, "limit": limit}, timeout=REST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# ------------------------------------------------------------
# UNIVERSE atranka
# ------------------------------------------------------------
def _prepare_universe(limit: int) -> List[str]:
    """
    Sudaro USDC porų sąrašą:
    - Jei UNIVERSE nurodytas config.json — naudojamas kaip pirminis rinkinys.
    - Jei tuščias arba <5:
        * Jei turime core.universe_manager.select_universe -> naudojam pagal TOP likvidumą/stabilumą.
        * Kitu atveju /exchangeInfo -> visos TRADING poros su BASE_QUOTE.
    - limit riboja kiek porų imti (0 = visos).
    """
    base_quote = (CONFIG.get("BASE_QUOTE", "USDC") or "USDC").upper()
    uni = CONFIG.get("UNIVERSE", []) or []

    if len(uni) < 5:
        if _dynamic_select_universe:
            try:
                print("[WS] 🔍 Dinaminė UNIVERSE atranka (select_universe)...")
                uni = _dynamic_select_universe()
            except Exception as e:
                print(f"[WS] ⚠️ select_universe nepavyko: {e}")
                uni = []
        if not uni:
            try:
                print(f"[WS] 🔍 exchangeInfo užklausa ({base_quote}) ...")
                url = f"{_rest_base()}/api/v3/exchangeInfo"
                r = requests.get(url, timeout=REST_TIMEOUT)
                if r.status_code == 200:
                    symbols = r.json().get("symbols", [])
                    for s in symbols:
                        sym = s.get("symbol", "")
                        if sym.endswith(base_quote) and s.get("status") == "TRADING":
                            uni.append(sym)
                print(f"[WS] ✅ Rasta {len(uni)} aktyvių {base_quote} porų.")
            except Exception as e:
                print(f"[WS] ⚠️ Nepavyko gauti exchangeInfo: {e}")

    uni = [s.upper() for s in uni if isinstance(s, str) and s.upper().endswith(base_quote)]
    if limit and limit > 0:
        return uni[:limit]
    return uni

# ------------------------------------------------------------
# WS prenumeratų valdymas (delta SUB/UNSUB)
# ------------------------------------------------------------
def _send(ws, msg: dict):
    try:
        ws.send(json.dumps(msg))
    except Exception:
        pass

def _subscribe_delta(ws, add_syms: List[str], remove_syms: List[str]):
    if remove_syms:
        _send(ws, {"method": "UNSUBSCRIBE", "params": [f"{s.lower()}@bookTicker" for s in remove_syms], "id": int(time.time()*1000)})
    if add_syms:
        _send(ws, {"method": "SUBSCRIBE", "params": [f"{s.lower()}@bookTicker" for s in add_syms], "id": int(time.time()*1000)+1})

def _refresh_universe_and_delta(ws):
    static_uni = CONFIG.get("UNIVERSE") or []
    if static_uni:
        want = [s.upper() for s in static_uni]
    else:
        want = _prepare_universe(limit=int(CONFIG.get("TOP_USDC_LIMIT", 40) or 40))
    want = [s for s in want if s.endswith((CONFIG.get("BASE_QUOTE", "USDC") or "USDC").upper())]

    with STATE.lock:
        current = set(STATE.subscribed)
        new = set(want)
        add = sorted(list(new - current))
        rem = sorted(list(current - new))
        STATE.universe = want

    if ws is not None and (add or rem):
        _subscribe_delta(ws, add, rem)
        with STATE.lock:
            STATE.subscribed = set(want)

# ------------------------------------------------------------
# WS pranešimų apdorojimas (@bookTicker)
# ------------------------------------------------------------
def _on_open(ws):
    with STATE.lock:
        STATE.connected = True
        STATE.last_update = time.time()
        STATE.last_pong = time.time()
        STATE.ping_fail_count = 0
        STATE.ping_window_start = time.time()

    # Pirmas subscribe visam universui (tuo metu STATE.universe jau paruoštas)
    params = [f"{sym.lower()}@bookTicker" for sym in STATE.universe]
    if params:
        _send(ws, {"method": "SUBSCRIBE", "params": params, "id": int(time.time())})
        with STATE.lock:
            STATE.subscribed = set(STATE.universe)

def _on_message(ws, message: str):
    """Apdoroja gaunamus Binance WS pranešimus."""
    try:
        msg = json.loads(message)

        # --- Palaikomi abu formatai: {s,c} ir {stream,data:{s,c}} ---
        data = None
        if "data" in msg and isinstance(msg["data"], dict):
            data = msg["data"]
        elif "s" in msg and "c" in msg:
            data = msg

        if not data:
            return

        sym = str(data.get("s") or "").upper()
        bid = float(data.get("b") or 0)
        ask = float(data.get("a") or 0)
        ts = float(data.get("T", 0) or time.time() * 1000.0)

        if not sym or bid <= 0 or ask <= 0:
            return

        mid = (bid + ask) / 2.0

        # --- Saugo į STATE ---
        with STATE.lock:
            STATE.price[sym] = {"price": mid, "bid": bid, "ask": ask, "ts": ts}
            STATE.last_update = time.time()

    except Exception as e:
        print(f"[WS] klaida on_message: {e}")
        traceback.print_exc()

def _on_pong(ws, msg):
    with STATE.lock:
        STATE.last_pong = time.time()
        STATE.ping_fail_count = 0

def _on_error(ws, err):
    """Klaidos apdorojimas + testnet->mainnet fallback (jei įjungtas testnet)."""
    try:
        msg = str(err)
        # Jei 404/handshake — jeigu bandėm testnet, perjungiame į mainnet
        if ("404" in msg or "handshake" in msg.lower() or "ConnectionRefused" in msg):
            with STATE.lock:
                if (STATE.use_testnet or CONFIG.get("USE_TESTNET", False)) and not STATE._testnet_failed_logged:
                    print("[WS] ⚠️ Testnet WS neprieinamas. Perjungta į MAINNET kainų srautą.")
                    STATE._testnet_failed_logged = True
                STATE.use_testnet = False
            try:
                ws.close()
            except Exception:
                pass
            time.sleep(2)
            threading.Thread(target=_ws_loop, daemon=True).start()
        else:
            print(f"[WS] Klaida: {msg}")
    except Exception as e:
        print(f"[WS] Klaidos apdorojimo klaida: {e}")

def _on_close(ws, code, reason):
    with STATE.lock:
        STATE.connected = False
    try:
        print(f"[WS] Užsidarė: code={code} reason={reason}")
    except Exception:
        pass

# ------------------------------------------------------------
# Heartbeat gija (ping su adaptacija)
# ------------------------------------------------------------
def _ping_loop():
    while not STATE.stop:
        try:
            ws = None
            with STATE.lock:
                ws = STATE.ws
            if ws is None:
                time.sleep(0.5)
                continue

            # Išsiunčiam ping (žemesnio lygio frame)
            try:
                ws.send_frame(websocket.ABNF.create_frame(opcode=websocket.ABNF.OPCODE_PING, data=""))
            except Exception:
                pass

            sent = time.time()
            time.sleep(WS_PONG_TIMEOUT_SEC)

            with STATE.lock:
                # Jei per timeout neatsinaujino last_pong — fiksuojam fail'ą
                if STATE.last_pong < sent:
                    if STATE.ping_window_start == 0.0:
                        STATE.ping_window_start = time.time()
                    STATE.ping_fail_count += 1

                    # Jei 3 fail'ai < 60 s — mažinam prenumeruojamų simbolių kiekį 25% ir bandome vėl
                    if STATE.ping_fail_count >= 3 and (time.time() - STATE.ping_window_start) < 60:
                        cut = max(1, math.ceil(len(STATE.universe) * 0.25))
                        if cut >= len(STATE.universe) and len(STATE.universe) > 1:
                            cut = len(STATE.universe) - 1
                        new_uni = STATE.universe[:-cut] if cut < len(STATE.universe) else STATE.universe[:max(1, len(STATE.universe)//2)]
                        add = [s for s in new_uni if s not in STATE.subscribed]
                        rem = [s for s in STATE.subscribed if s not in new_uni]
                        _subscribe_delta(ws, add, rem)
                        STATE.universe = list(new_uni)
                        STATE.subscribed = set(new_uni)
                        STATE.ping_fail_count = 0
                        STATE.ping_window_start = time.time()
                else:
                    # Stabilu — resetinam backoff
                    STATE.backoff_exp = 0
                    if (time.time() - STATE.backoff_last_reset) > WS_BACKOFF_RESET_SEC:
                        STATE.backoff_last_reset = time.time()

            # Kitas ping po atsitiktinio intervalo
            time.sleep(random.uniform(WS_PING_MIN_SEC, WS_PING_MAX_SEC))
        except Exception:
            time.sleep(1)

# ------------------------------------------------------------
# Reconnect backoff
# ------------------------------------------------------------
def _reconnect_backoff_sleep():
    exp = STATE.backoff_exp
    delay = min(WS_BACKOFF_MAX_SEC, WS_BACKOFF_BASE_SEC * (2 ** exp))
    delay = max(1, int(delay * random.uniform(0.8, 1.2)))  # jitter
    time.sleep(delay)
    STATE.backoff_exp = min(10, STATE.backoff_exp + 1)

# ------------------------------------------------------------
# WS gija (auto-reconnect)
# ------------------------------------------------------------
def _ws_loop():
    ws_url = BINANCE_WS_TEST if (STATE.use_testnet or CONFIG.get("USE_TESTNET", False)) else BINANCE_WS_MAIN

    # Testnet sveikatos patikra — jei neprieinamas, fallback į mainnet
    if "testnet" in ws_url:
        try:
            r = requests.get(f"{BINANCE_REST_TEST}/api/v3/time", timeout=3)
            if r.status_code != 200:
                print("[WS] ⚠️ Binance TESTNET WS neveikia. Naudojamas MAINNET kainų srautas.")
                ws_url = BINANCE_WS_MAIN
        except Exception:
            print("[WS] ⚠️ Nepavyko prisijungti prie TESTNET WS. Fallback į MAINNET.")
            ws_url = BINANCE_WS_MAIN

    while not STATE.stop:
        try:
            if websocket is None:
                print("[WS] 'websocket-client' biblioteka neįdiegta.")
                time.sleep(5)
                continue
            # --- Sukuriame multi-stream URL pagal esamą UNIVERSE ---
            with STATE.lock:
                streams = [f"{s.lower()}@bookTicker" for s in STATE.universe]
            if streams:
                joined = "/".join(streams)
                ws_url = f"{BINANCE_WS_MAIN.replace('/ws', '/stream')}?streams={joined}"
                print(f"[WS] 🌐 Multi-stream jungtis su {len(streams)} simboliais")
            else:
                print("[WS] ⚠️ UNIVERSE tuščias — WS nebus jungiamas.")
                time.sleep(10)
                continue

            app = websocket.WebSocketApp(
                ws_url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
                on_pong=_on_pong
            )

            with STATE.lock:
                STATE.ws = app
                STATE.subscribed = set()

            # Paleidžiam ping giją
            t_ping = threading.Thread(target=_ping_loop, daemon=True)
            t_ping.start()

            # Paleidžiam WS klientą (be built-in ping_interval — darom savo heartbeat)
            app.run_forever(ping_interval=None, ping_timeout=None)
        except Exception:
            traceback.print_exc()
            _reconnect_backoff_sleep()
        finally:
            with STATE.lock:
                STATE.connected = False
                STATE.ws = None

# ------------------------------------------------------------
# Periodinė priežiūra: REST fallback + periodinis delta refresh + 24h volume
# ------------------------------------------------------------
def _periodic_maintenance():
    last_resub = 0.0
    last_volume_update = 0.0
    while not STATE.stop:
        try:
            now = time.time()

            # REST fallback: tik TOP watchlist (ne visų)
            with STATE.lock:
                last = STATE.last_update
                ws = STATE.ws
                uni_snapshot = list(STATE.universe)

            if (now - last) > WS_STALE_SECONDS:
                watch = uni_snapshot[:max(1, REST_WATCHLIST_TOP)]
                for sym in watch:
                    bt = _rest_get_bookticker(sym)
                    if not bt:
                        continue
                    try:
                        bid = float(bt.get("bidPrice", 0) or 0)
                        ask = float(bt.get("askPrice", 0) or 0)
                        if bid > 0 and ask > 0:
                            mid = (bid + ask) / 2.0
                            with STATE.lock:
                                STATE.price[sym] = {"price": mid, "bid": bid, "ask": ask, "ts": int(now * 1000)}
                                STATE.last_update = now
                    except Exception:
                        pass

            # 24h volume (naudinga dashboard’ui)
            if (now - last_volume_update) > 60:
                try:
                    url = f"{_rest_base()}/api/v3/ticker/24hr"
                    r = requests.get(url, timeout=REST_TIMEOUT)
                    if r.status_code == 200:
                        tickers = r.json()
                        with STATE.lock:
                            for t in tickers:
                                sym = t.get("symbol", "").upper()
                                if sym in STATE.price:
                                    try:
                                        vol_usdc = float(t.get("quoteVolume", 0) or 0)
                                        STATE.price[sym]["volume_usdc"] = vol_usdc
                                    except Exception:
                                        pass
                    last_volume_update = now
                except Exception:
                    traceback.print_exc()

            # Periodinis UNIVERSE refresh + delta subscribe (pagal CONFIG intervalą)
            refresh_every = STATE.refresh_sec_cfg if STATE.refresh_sec_cfg else 900
            if (now - last_resub) > refresh_every:
                _refresh_universe_and_delta(ws)
                last_resub = now

            time.sleep(1)
        except Exception:
            traceback.print_exc()
            time.sleep(1)

# ------------------------------------------------------------
# Vieša API
# ------------------------------------------------------------
def start_ws_auto(limit: int = 0, testnet: bool = False, refresh_sec: int = 120):
    """
    Suderinamumas išsaugotas:
    - limit: paliekam; jei UNIVERSE tuščias — imsim TOP pagal atranką.
    - testnet: jei True — bandome TESTNET, kitaip MAINNET (su automatiniu fallback).
    - refresh_sec: paliekam atgaliniam suderinamumui (UNIVERSE delta refresh valdo CONFIG["UNIVERSE_REFRESH_MINUTES"]).
    """
    with STATE.lock:
        if STATE.ws is not None:
            return
        # Pirminis universas
        STATE.universe = _prepare_universe(limit)
        STATE.subscribed = set()
        STATE.use_testnet = bool(testnet)
        STATE.refresh_sec_arg = int(refresh_sec) if refresh_sec is not None else 120
        STATE.stop = False
        STATE._testnet_failed_logged = False
        STATE.backoff_exp = 0
        STATE.backoff_last_reset = time.time()

    t_ws = threading.Thread(target=_ws_loop, daemon=True)
    t_ws.start()
    t_mt = threading.Thread(target=_periodic_maintenance, daemon=True)
    t_mt.start()

def is_connected() -> bool:
    with STATE.lock:
        return bool(STATE.ws) and (time.time() - STATE.last_update) <= WS_STALE_SECONDS

def get_all_prices() -> Dict[str, Dict]:
    with STATE.lock:
        return {k: dict(v) for k, v in STATE.price.items()}

def get_price(symbol: str) -> Optional[float]:
    symbol = symbol.upper()
    with STATE.lock:
        row = STATE.price.get(symbol)
        if row:
            val = float(row.get("price", 0) or 0)
            return val if val > 0 else None
    bt = _rest_get_bookticker(symbol)
    if not bt:
        return None
    try:
        bid = float(bt.get("bidPrice", 0) or 0)
        ask = float(bt.get("askPrice", 0) or 0)
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            with STATE.lock:
                STATE.price[symbol] = {"price": mid, "bid": bid, "ask": ask, "ts": time.time() * 1000.0}
            return mid
    except Exception:
        pass
    return None

def get_orderbook_top(symbol: str) -> Tuple[float, float, float, List[Tuple[float, float]], List[Tuple[float, float]]]:
    symbol = symbol.upper()
    row = None
    with STATE.lock:
        row = STATE.price.get(symbol)
    if not row:
        bt = _rest_get_bookticker(symbol)
        if bt:
            try:
                bid = float(bt.get("bidPrice", 0) or 0)
                ask = float(bt.get("askPrice", 0) or 0)
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2.0
                    row = {"price": mid, "bid": bid, "ask": ask, "ts": time.time() * 1000.0}
                    with STATE.lock:
                        STATE.price[symbol] = row
            except Exception:
                pass
    if not row:
        return 0.0, 0.0, 0.0, [], []

    bid = float(row.get("bid", 0) or 0)
    ask = float(row.get("ask", 0) or 0)
    mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else float(row.get("price", 0) or 0)

    depth = _rest_get_depth(symbol, ORDERBOOK_DEPTH)
    if depth and isinstance(depth, dict):
        try:
            bids_depth = [(float(px), float(q)) for px, q in (depth.get("bids") or [])[:ORDERBOOK_DEPTH]]
            asks_depth = [(float(px), float(q)) for px, q in (depth.get("asks") or [])[:ORDERBOOK_DEPTH]]
            if not bids_depth and bid > 0:
                bids_depth = [(bid, 10.0)]
            if not asks_depth and ask > 0:
                asks_depth = [(ask, 10.0)]
            return bid, ask, mid, bids_depth, asks_depth
        except Exception:
            pass

    bids_depth = [(bid, 10.0)] if bid > 0 else []
    asks_depth = [(ask, 10.0)] if ask > 0 else []
    return bid, ask, mid, bids_depth, asks_depth

def stop_ws():
    with STATE.lock:
        STATE.stop = True
        ws = STATE.ws
        STATE.ws = None
    try:
        if ws:
            ws.close()
    except Exception:
        pass
