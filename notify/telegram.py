# ============================================================
# notify/telegram.py — Telegram siuntimas (saugus MarkdownV2)
# Rate-limit + burst-merge + periodinės ataskaitos
# ============================================================

import os
import time
import queue
import threading
import requests
from datetime import datetime, timezone, timedelta

from core.config import CONFIG

# ---- Konfigai ----
notify_cfg = CONFIG.get("NOTIFY", {})
TELEGRAM_ENABLED = bool(notify_cfg.get("TELEGRAM_ENABLED", True))
MUTE_IN_TEST = bool(notify_cfg.get("MUTE_IN_TEST", True))
BOT_PROFILE = str(CONFIG.get("MODE", "TEST")).upper()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", notify_cfg.get("TELEGRAM_TOKEN", ""))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", notify_cfg.get("TELEGRAM_CHAT_ID", ""))

REPORTS_CFG = CONFIG.get("REPORTS", {
    "DAILY_ENABLED": True,
    "WEEKLY_ENABLED": True,
    "DAILY_HHMM": "21:00",
    "WEEKLY_DAY": 6,     # sekmadienis
    "WEEKLY_HHMM": "21:00"
})

# ---- Rate-limit ir merge ----
RL_MAX = 3           # max žinučių per langą
RL_WINDOW_SEC = 10   # langas sekundėmis
MERGE_WINDOW_SEC = 3 # per kiek sekundžių BUY/SELL sugrupuoti

_send_times = []
_merge_buf = queue.Queue()
_merge_thread_started = False


def _escape_md(text: str) -> str:
    # Telegram MarkdownV2: pabėgam specialius
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f"\\{ch}")
    return text


def _rate_limit_ok() -> bool:
    global _send_times
    now = time.time()
    _send_times = [t for t in _send_times if now - t < RL_WINDOW_SEC]
    if len(_send_times) >= RL_MAX:
        return False
    _send_times.append(now)
    return True


def _send_raw(msg: str) -> bool:
    if not TELEGRAM_ENABLED or not notify_cfg.get("ENABLED", True):
        print(f"🚫 [TELEGRAM] Išjungta config'e — {msg[:80]}")
        return False

    if BOT_PROFILE == "TEST" and MUTE_IN_TEST:
        print(f"[TELEGRAM:MUTE(TEST)] {msg}")
        return True

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ [TELEGRAM] Trūksta TOKEN/CHAT_ID — {msg[:80]}")
        return False

    if not _rate_limit_ok():
        # Per didelis srautas — sudedam į merge buferį
        try:
            _merge_buf.put_nowait(("TEXT", msg, time.time()))
        except queue.Full:
            pass
        return False

    safe = _escape_md(msg.strip())
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": safe,
        "parse_mode": "MarkdownV2"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"📨 [TELEGRAM] {msg}")
            return True
        else:
            print(f"⚠️ [TELEGRAM] {r.status_code}: {r.text}")
            return False
    except requests.RequestException as e:
        print(f"❌ [TELEGRAM] Klaida: {e}")
        return False


def send_info(msg: str):
    """Paprasta informacinė žinutė."""
    tag = "[LIVE]" if BOT_PROFILE == "MAINNET" else "[TEST]"
    _send_raw(f"{tag} {msg}")


def send_trade_event(side: str, symbol: str, qty: float, price: float,
                     ai_confidence: float | None = None, edge: float | None = None,
                     profit_pct: float | None = None, reason: str | None = None):
    """BUY/SELL įvykis su „burst merge“ palaikymu."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    tag = "[LIVE]" if BOT_PROFILE == "MAINNET" else "[TEST]"

    side = side.upper()
    if side == "BUY":
        body = f"🟢 *BUY* {symbol} — qty {qty:.6f} @ {price:.6f}"
        if ai_confidence is not None:
            body += f" | conf {ai_confidence:.3f}"
        if edge is not None:
            body += f" | edge {edge:.4f}"
    else:
        body = f"🔴 *SELL* {symbol} — qty {qty:.6f} @ {price:.6f}"
        if profit_pct is not None:
            body += f" | P&L {profit_pct:+.2f}%"
        if reason:
            body += f" | {reason}"

    txt = f"{tag} {body}\n🕒 {ts}"

    # Uždėti į merge buferį (BUY/SELL grupavimui)
    try:
        _merge_buf.put_nowait(("TRADE", txt, time.time()))
    except queue.Full:
        # jei buferis pilnas — siųsti tiesiogiai
        _send_raw(txt)


def _merge_worker():
    """Surenka TRADE įvykius per MERGE_WINDOW_SEC ir siunčia vieną suvestinę."""
    bucket = []  # (txt, t)
    last_flush = 0.0

    while True:
        try:
            item = _merge_buf.get(timeout=0.5)
        except queue.Empty:
            item = None

        now = time.time()

        if item:
            kind, txt, t = item
            if kind == "TEXT":
                # paprasta tekstinė žinutė — siųsti nedelsiant
                _send_raw(txt)
            else:
                bucket.append((txt, t))

        # Flush, jei seniausias > MERGE_WINDOW_SEC
        if bucket:
            oldest = bucket[0][1]
            if now - oldest >= MERGE_WINDOW_SEC:
                lines = [b[0] for b in bucket]
                if len(lines) == 1:
                    _send_raw(lines[0])
                else:
                    # sugrupuota suvestinė
                    tag = "[LIVE]" if BOT_PROFILE == "MAINNET" else "[TEST]"
                    joined = "\n".join(lines)
                    header = f"{tag} *Atidaryti įvykiai* ({len(lines)}):"
                    _send_raw(f"{header}\n{joined}")
                bucket.clear()
                last_flush = now

        # saugiklis — jei nieko nevyko, bet senas likutis
        if bucket and (now - last_flush) >= (MERGE_WINDOW_SEC * 2):
            lines = [b[0] for b in bucket]
            for ln in lines:
                _send_raw(ln)
            bucket.clear()
            last_flush = now


def _ensure_merge_thread():
    global _merge_thread_started
    if _merge_thread_started:
        return
    th = threading.Thread(target=_merge_worker, daemon=True)
    th.start()
    _merge_thread_started = True


# ---------------- Periodinės ataskaitos ----------------

def _should_send_daily(now: datetime) -> bool:
    hhmm = REPORTS_CFG.get("DAILY_HHMM", "21:00")
    h, m = map(int, hhmm.split(":"))
    return REPORTS_CFG.get("DAILY_ENABLED", True) and now.hour == h and now.minute == m


def _should_send_weekly(now: datetime) -> bool:
    # weekday(): Mon=0..Sun=6
    wd = int(REPORTS_CFG.get("WEEKLY_DAY", 6))
    hhmm = REPORTS_CFG.get("WEEKLY_HHMM", "21:00")
    h, m = map(int, hhmm.split(":"))
    return REPORTS_CFG.get("WEEKLY_ENABLED", True) and now.weekday() == wd and now.hour == h and now.minute == m


def _load_equity_history():
    from pathlib import Path
    path = Path("data/equity_history.json")
    if not path.exists():
        return []
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _compose_daily_summary():
    hist = _load_equity_history()
    if not hist:
        return "📊 Dienos suvestinė: nėra duomenų."

    last = hist[-1]
    eq = last.get("equity", 0.0)
    d = last.get("day_pnl_pct", 0.0)
    w = last.get("week_pnl_pct", 0.0)
    m = last.get("month_pnl_pct", 0.0)
    pos = last.get("positions", 0)

    return (
        f"📊 *Dienos suvestinė*\n"
        f"Equity: {eq:.2f} USDC | Pozicijų: {pos}\n"
        f"Diena: {d:+.2f}% | Savaitė: {w:+.2f}% | Mėnuo: {m:+.2f}%"
    )


def _compose_weekly_summary():
    hist = _load_equity_history()
    if not hist:
        return "📊 Savaitės suvestinė: nėra duomenų."

    last = hist[-1]
    eq = last.get("equity", 0.0)
    w = last.get("week_pnl_pct", 0.0)
    m = last.get("month_pnl_pct", 0.0)

    return (
        f"🗓️ *Savaitės suvestinė*\n"
        f"Equity: {eq:.2f} USDC\n"
        f"Savaitė: {w:+.2f}% | Mėnuo: {m:+.2f}%"
    )


def _reports_worker():
    last_sent_min = None
    while True:
        try:
            now = datetime.now(timezone.utc).astimezone()  # lokalus laikas
            key = (now.year, now.month, now.day, now.hour, now.minute)

            # Siunčiam max kartą per minutę
            if key != last_sent_min:
                if _should_send_daily(now):
                    send_info(_compose_daily_summary())
                if _should_send_weekly(now):
                    send_info(_compose_weekly_summary())
                last_sent_min = key

        except Exception as e:
            print(f"[TELEGRAM] Report worker klaida: {e}")

        time.sleep(5)


def start_report_scheduler():
    """Paleidžia burst-merge ir periodinių ataskaitų gijas (jei įjungta)."""
    _ensure_merge_thread()
    if REPORTS_CFG.get("DAILY_ENABLED", True) or REPORTS_CFG.get("WEEKLY_ENABLED", True):
        th = threading.Thread(target=_reports_worker, daemon=True)
        th.start()
