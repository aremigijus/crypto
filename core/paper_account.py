# ============================================================
# core/paper_account.py — Pozicijų valdymas (DB versija)
# ------------------------------------------------------------
# Test režime palaiko pradinį balansą (10 000 USDC)
# Visos būsenos operacijos atliekamos per DB.
# ============================================================

import sqlite3
import logging
from datetime import datetime, timezone
from core.db_manager import DB_PATH, fetch_risk_state, update_risk_state  # Importuojame ir risk_state pagalbininkus
from core.config import CONFIG

START_CAPITAL = 10_000.0  # testinės sąskaitos pradinis kapitalas

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _get_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 📊 Pagrindinės operacijos
# ============================================================

def get_open_positions() -> dict:
    """Grąžina visas atidarytas pozicijas iš DB."""
    con = _get_conn()
    rows = con.execute("SELECT * FROM positions WHERE state='OPEN'").fetchall()
    con.close()
    return {
        r["symbol"]: {
            "entry_price": r["entry_price"],
            "qty": r["qty"],
            "confidence": r["confidence"],
            "opened_at": r["opened_at"]
        }
        for r in rows
    }


def get_equity_from_db() -> float:
    """Grąžina paskutinį įrašą iš equity_history lentelės."""
    try:
        con = _get_conn()
        row = con.execute("SELECT equity FROM equity_history ORDER BY ts DESC LIMIT 1").fetchone()
        con.close()
        return float(row["equity"]) if row else START_CAPITAL
    except Exception:
        return START_CAPITAL


def get_state() -> dict:
    """
    Grąžina dabartinę sąskaitos būseną (balansą, pozicijas) iš DB.
    Ši funkcija pakeičia seną JSON įkėlimo logiką.
    """
    try:
        equity = get_equity_from_db()
        positions = get_open_positions()

        used_usdc = sum(
            pos["qty"] * pos["entry_price"]
            for pos in positions.values()
        )
        free_usdc = equity - used_usdc

        # Skaičiuojame PnL tik dienai (šis duomenys gaunamas iš daily guard)
        # Naudojame risk_state lentelę, kur daily PnL (ar DD) yra saugomas
        risk_state = fetch_risk_state()
        dd_day_pct = float(risk_state.get('dd_day_pct', 0.0))
        
        return {
            "balance_usdc": equity,
            "equity": equity,
            "free_usdc": free_usdc,
            "used_usdc": used_usdc,
            "positions": positions,
            "open_positions": len(positions),
            "daily_pnl_pct": dd_day_pct, # Grąžinama, kad būtų prieinama AISizer
            "timestamp": _now_iso(),
        }
    except Exception as e:
        logging.error(f"[PaperAccount] Klaida gaunant būseną iš DB: {e}")
        return {
            "balance_usdc": START_CAPITAL,
            "equity": START_CAPITAL,
            "free_usdc": START_CAPITAL,
            "used_usdc": 0,
            "positions": {},
            "open_positions": 0,
            "daily_pnl_pct": 0.0,
            "timestamp": _now_iso(),
        }

def update_balance_after_sell(symbol: str, qty: float, entry_price: float, exit_price: float, usdc_gain: float):
    """
    Atnaujina virtualios sąskaitos (Paper Account) balansą po pozicijos uždarymo.
    Tai yra pakaitalas tikrai biržos sąskaitai, skirtas tik Paper Mode.
    Iš esmės, prie turimų grynųjų (free_usdc) pridedamas gautas pelnas/nuostolis (usdc_gain).
    """
    with _get_conn() as con:
        cur = con.cursor()
        
        # Pelnas (arba nuostolis) įrašomas į equity_history lentelę.
        # Nėra tiesioginės "balance" lentelės, todėl atnaujiname grynųjų USDC sumą.
        # Šiuo atveju geriausia tiesiog atnaujinti paskutinį equity_history įrašą
        # arba leisti equity_tracker'iui (kuris kviečia get_state()) teisingai apskaičiuoti
        # sekančios iteracijos metu, jei PaperAccount yra atskirame faile.
        
        # Kadangi naudojama DB:
        # 1. Pelnas jau yra *įskaičiuotas* į equity_history per OrderExecutor/ExitManager logiką,
        #    kuri naudoja get_state(), kad apskaičiuotų equity.
        # 2. Tikrų atidarytų pozicijų (DB positions) nebėra.
        # Mums tereikia užtikrinti, kad ateityje grynųjų pinigų (free_usdc) apskaičiavimas
        # būtų teisingas.

        # Patikriname, ar šis sandoris jau nebuvo uždarytas ExitManager'io
        # (tai yra apsauga, bet OrderExecutor.market_sell ištrina iš positions, o ExitManager.sell tik pažymi CLOSED).
        
        # Kadangi OrderExecutor (žingsnis 1) pašalina poziciją iš 'positions' ir jau žino PnL (usdc_gain),
        # mums reikia atnaujinti grynųjų pinigų (free_usdc) sumą virtualioje sąskaitoje.
        
        # Paprastas būdas tai padaryti: įrašyti naują eilutę į risk_state lentelę
        # arba atnaujinti balance per kitą globalų mechanizmą.
        
        # Pataisymas: atnaujiname virtualų 'balance_usdc' įrašą (panaudojus PaperAccount JSON failą
        # anksčiau. Dabar turime naudoti DB).
        
        # Kadangi sistema veikia per equity_history ir get_state(), paprasčiausias veiksmas yra:
        # Atnaujinti grynųjų pinigų (USDC) balansą.
        
        # Nustatykite grynųjų pinigų atnaujinimo logiką:
        try:
            # 1. Gauname dabartinę grynųjų USDC sumą iš paskutinio equity_history įrašo
            last_equity_row = cur.execute("""
                SELECT equity, free_usdc FROM equity_history ORDER BY ts DESC LIMIT 1
            """).fetchone()

            if last_equity_row:
                old_equity = float(last_equity_row['equity'] or START_CAPITAL)
                old_free_usdc = float(last_equity_row['free_usdc'] or START_CAPITAL)
                
                # Atnaujiname laisvą USDC sumą: pridedame gautą pelną/nuostolį.
                # (Pozicijos dydis * įėjimo kaina) jau yra užimta suma. 
                # Kadangi OrderExecutor apskaičiavo skirtumą (usdc_gain), 
                # dabar grynųjų pinigų suma turėtų būti:
                # senas_free_usdc + (qty * exit_price)
                # BET: OrderExecutor apskaičiuoja PnL (usdc_gain), o likusi dalis jau grįžta
                # per pozicijų ištrynimą.
                
                # Saugiausias būdas: EquityTracker'is kitos iteracijos metu automatiškai apskaičiuos naują būseną.
                # Jei norime akimirksnio atnaujinimo, turime modifikuoti laisvą USDC sumą:

                # Laisvi USDC prieš sandorį: old_free_usdc
                # Uždaromo sandorio vertė (entry): qty * entry_price
                # Uždaromo sandorio vertė (exit): qty * exit_price
                
                # Sandorio vertė grįžta į free_usdc: qty * entry_price
                # Pelnas/nuostolis: usdc_gain
                
                # Pataisyta: Patikslinta, kad grąžintų visą sumą + PnL.
                usdc_return = qty * exit_price # Bendra gauta suma (įskaitant pradinį kapitalą)
                
                new_free_usdc = old_free_usdc + usdc_return - (qty * entry_price) # grąžintas kapitalas + pelnas
                
                # Šis atnaujinimas yra sudėtingas DB-pagrindu veikiančioje sistemoje.
                # Paprasčiau: leisti EquityTracker'iui apskaičiuoti per get_state(). 
                # Jums reikėtų tik atnaujinti `paper_account.json` failą per `PaperAccount` modulį,
                # jei `PaperAccount` palaiko balanso valdymą.
                
                # Kadangi PaperAccount.py neturi tiesioginės funkcijos atnaujinti free_usdc (tik grąžina būseną),
                # bet OrderExecutor dabar tiesiogiai pašalino poziciją iš DB,
                # tai reiškia, kad get_state() (iš core/paper_account.py) jau grąžins 
                # didesnį 'free_usdc' ir mažesnį 'used_usdc', o equity bus teisingas kitos iteracijos metu.
                
                # Kviečiame 'update_paper_account_file' (jei naudojamas JSON failas)
                PaperAccount.update_state_on_trade(
                    symbol=symbol,
                    action="SELL",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=usdc_gain / (qty * entry_price) * 100 if entry_price > 0 else 0,
                    pnl_usd=usdc_gain,
                    confidence=0.0, # Nenaudojame confidence sell metu
                    hold_time_h=0.0, # Laikas bus apskaičiuotas ExitManager
                    market_state="paper"
                )
                
                # Dėmesio: jei yra atnaujintas `ai/ai_learning.py` ir `update_state_on_trade`
                # rašo į `paper_account.json`, tada toliau esantis kodas užtikrins, 
                # kad equity_tracker atnaujintų DB.
                logging.info(f"[PaperAccount] Atnaujintas Paper Account (JSON) po SELL {symbol}")
            else:
                logging.warning("[PaperAccount] Nepavyko rasti paskutinio equity įrašo. Balansas nebuvo atnaujintas.")

        except Exception as e:
            logging.error(f"[PaperAccount] Klaida atnaujinant Paper Account: {e}")
            pass
        
def clear_closed_positions(older_than_days: int = 30):
    """Pašalina CLOSED pozicijas, senesnes nei N dienų, kad išvalytų DB."""
    try:
        con = _get_conn()
        cur = con.cursor()
        threshold_iso = (datetime.now(timezone.utc) - timezone.timedelta(days=older_than_days)).isoformat()
        
        cur.execute("DELETE FROM positions WHERE state='CLOSED' AND closed_at < ?", (threshold_iso,))
        count = cur.rowcount
        con.commit()
        con.close()
        if count > 0:
             logging.info(f"[PaperAccount] 🧹 Išvalytos senos CLOSED pozicijos (> {older_than_days} d.) - {count} įrašai.")
    except Exception as e:
        logging.error(f"[PaperAccount] Klaida valant senas pozicijas: {e}")


# ============================================================
# 🔍 Diagnostika
# ============================================================

def debug_dump():
    """Išspausdina visas pozicijas iš DB."""
    con = _get_conn()
    rows = con.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
    con.close()
    print("=== Pozicijos DB ===")
    for r in rows:
        print(dict(r))
    print("====================")

def get_account_state():
    """
    Grąžina dabartinę virtualios (paper) sąskaitos būseną — balansą, equity ir pozicijas iš DB.
    Šalina priklausomybę nuo paper_account.json.
    """
    try:
        # 1. Pasiimame atidarytas pozicijas
        positions = get_open_positions()

        # 2. Pasiimame paskutinį equity įrašą
        con = _get_conn()
        row = con.execute("""
            SELECT ts, equity, free_usdc, used_usdc
            FROM equity_history
            ORDER BY ts DESC
            LIMIT 1
        """).fetchone()
        con.close()

        if row:
            return {
                "balance_usdc": float(row["free_usdc"]), # Laisvi pinigai
                "positions": positions,
                "equity": float(row["equity"]),
                "free_usdc": float(row["free_usdc"]),
                "used_usdc": float(row["used_usdc"]),
                "timestamp": row["ts"]
            }
        else:
            # Jei DB tuščia, grąžiname pradinę būseną
            logging.warning("[PaperAccount] Nepavyko gauti būsenos iš DB. Grąžinama pradinė būsena.")
            now = datetime.now(timezone.utc).isoformat()
            return {
                "balance_usdc": START_CAPITAL,
                "positions": {},
                "equity": START_CAPITAL,
                "free_usdc": START_CAPITAL,
                "used_usdc": 0.0,
                "timestamp": now
            }

    except Exception as e:
        logging.exception(f"[PaperAccount] Klaida skaitant būseną iš DB: {e}")
        now = datetime.now(timezone.utc).isoformat()
        return {
            "balance_usdc": START_CAPITAL,
            "positions": {},
            "equity": START_CAPITAL,
            "free_usdc": START_CAPITAL,
            "used_usdc": 0.0,
            "timestamp": now
        }