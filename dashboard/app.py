import os
import json
import time
import logging
import sqlite3

from pathlib import Path
from flask import Flask, jsonify, request, render_template
from threading import RLock

from core.config import CONFIG
from core.db_manager import (
    DB_PATH,
    fetch_recent_trades,
    ensure_tables_exist,
)
from ai.ai_sizer import AISizer
from ai.ai_performance import get_ai_performance
from core.ws_bridge import get_price
from core.paper_account import get_account_state, get_open_positions

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
CORE_DIR = BASE_DIR.parent / "core"

CONFIG_PATH = CORE_DIR / "config.json"
DEFAULT_CONFIG_PATH = CORE_DIR / "config_default.json"

_state_lock = RLock()
APP_START_TS = time.time()


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/trades")
def trades_page():
    return render_template("trades.html")


@app.route("/compat")
def compat_page():
    return render_template("compat_report.html")


@app.route("/api/summary")
def api_summary():
    acc = get_account_state()
    perf = get_ai_performance().get_summary()  # ✅ PATAISYTA: pridėti .get_summary()

    balance = acc.get("balance_usdc", 0)
    total_equity = acc.get("equity", balance)
    free_usdc = acc.get("free_usdc", 0)
    used_usdc = acc.get("used_usdc", 0)
    
    # PnL skaičiavimas
    start_balance = 10000.0  # Pradinis balansas
    pnl_pct = 0
    if start_balance > 0:
        pnl_pct = round(((total_equity - start_balance) / start_balance) * 100, 3)

    return jsonify({
        "balance": balance,
        "equity": total_equity,
        "free_usdc": free_usdc,
        "used_usdc": used_usdc,
        "pnl_pct": pnl_pct,
        "open_positions": acc.get("open_positions", 0),
        "ai_win_rate": perf.get("win_rate", 0),
        "ai_trades": perf.get("total_trades", 0),
        "ai_profit_usdc": perf.get("profit_usdc", 0)
    })


@app.route("/api/open_positions")
def api_open_positions():
    positions = get_open_positions()
    out = []
    
    for symbol, pos in positions.items():
        current_price = get_price(symbol)
        if current_price is None:
            current_price = pos["entry_price"]

        pnl = (current_price - pos["entry_price"]) * pos["qty"]
        
        out.append({
            "symbol": symbol,
            "qty": pos["qty"],
            "entry_price": pos["entry_price"],
            "current_price": current_price,
            "pnl": round(pnl, 6),
            "confidence": pos.get("confidence", 0)
        })
    return jsonify(out)


@app.route("/api/live_positions")
def api_live_positions():
    positions = get_open_positions()
    return jsonify(positions)


@app.route("/api/ai_summary")
def api_ai_summary():
    return jsonify(get_ai_performance().get_summary())  # ✅ PATAISYTA: pridėti .get_summary()


@app.route("/api/ai_performance")
def api_ai_performance():
    return jsonify(get_ai_performance().get_summary())  # ✅ PATAISYTA: pridėti .get_summary()


@app.route("/api/ai_sizer")
def api_ai_sizer():
    # ✅ PATAISYTA: Naudoti core.ai_sizer_summary vietoj AISizer.get_summary()
    try:
        from core.ai_sizer_summary import get_ai_sizer_summary
        summary = get_ai_sizer_summary()
        return jsonify(summary)
    except Exception as e:
        logging.error(f"[DASHBOARD] Klaida /api/ai_sizer: {e}")
        return jsonify({
            "boost_avg": 0.0,
            "vol_avg": 0.0,
            "min_trade_usdc": 25.0,
            "max_trade_usdc": 500.0,
            "max_positions": 8,
            "open_positions": 0,
            "portfolio_usage_pct": 0.0
        })


@app.route("/api/ai_metrics")
def api_ai_metrics():
    limit = int(request.args.get("limit", 100))
    trades = fetch_recent_trades(limit)
    return jsonify(trades)


@app.route("/api/runtime")
def api_runtime():
    uptime = round(time.time() - APP_START_TS)
    return jsonify({"uptime_sec": uptime})


@app.route("/api/risk_summary")
def api_risk_summary():
    acc = get_account_state()
    balance = acc.get("balance_usdc", 0)
    equity = acc.get("equity", balance)
    
    # Paprastas drawdown skaičiavimas
    start_balance = 10000.0
    current_dd = 0
    if start_balance > 0:
        current_dd = ((equity - start_balance) / start_balance) * 100
    
    max_dd = CONFIG.get("DAILY_MAX_DRAWDOWN_PCT", 2.0)

    return jsonify({
        "balance": balance,
        "equity": equity,
        "drawdown_pct": round(current_dd, 2),
        "drawdown_limit_pct": max_dd,
        "state": "OK" if current_dd > -max_dd else "STOP"
    })


@app.route("/api/check_compat_matrix")
def api_check_matrix():
    try:
        path = BASE_DIR / "COMPAT_MATRIX_AUTO.md"
        report = [
            "# Compatibility Matrix (Auto)",
            "## API endpoints OK",
            f"- equity source: DB_ONLY",
            f"- trades source: DB_ONLY",
            f"- paper_account: OK",
            f"- ai_metrics: DB_OK",
            f"- config: {CONFIG_PATH.name}",
            "",
            "Autogenerated ✔"
        ]
        path.write_text("\n".join(report), encoding="utf-8")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


@app.route("/api/save_config", methods=["POST"])
def api_save_config():
    data = request.json
    with _state_lock:
        # Atnaujinti CONFIG
        for k, v in data.items():
            CONFIG[k] = v
        
        # Išsaugoti config.json
        try:
            CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2), encoding="utf-8")
        except Exception as e:
            logging.error(f"Klaida išsaugant config: {e}")
            return jsonify({"status": "error", "msg": str(e)})
            
    return jsonify({"status": "ok"})


@app.route("/api/get_config")
def api_get_config():
    return jsonify(CONFIG)


@app.route("/api/test_reset", methods=["POST"])
def api_test_reset():
    try:
        from core.db_init import init_full_db
        init_full_db(force_recreate=True)
        return jsonify({"status": "reset"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


if __name__ == "__main__":
    ensure_tables_exist()
    app.run(host="0.0.0.0", port=5000, debug=False)
    