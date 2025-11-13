# ============================================================
# trade_events.py — Prekybos įvykių pranešimai (uždarytos pozicijos)
# ------------------------------------------------------------
# Atnaujinta: 2025-11-02
# ✅ Skirta siųsti Telegram pranešimus apie pozicijų uždarymą
# ✅ Rodomas pelnas % ir USDC + bendras balansas
# ✅ Automatinis 💰 / 🔻 simbolis pagal pelningumą
# ✅ Test režimu (BOT_PROFILE=TEST) tik loguoja į konsolę
# ============================================================

from notify.notifier import notify


def notify_trade_close(symbol: str, profit_pct: float, profit_usdc: float, balance: float):
    """
    Siunčia pranešimą, kai uždaroma pozicija (TP / SL / TSL / manual).
    Parametrai:
      - symbol: pvz. 'BTCUSDC'
      - profit_pct: pelnas % (teigiamas arba neigiamas)
      - profit_usdc: pelnas USDC
      - balance: dabartinis balansas po uždarymo
    """
    try:
        # Apsauga nuo blogų duomenų
        if symbol is None or profit_pct is None or profit_usdc is None or balance is None:
            print("⚠️ [TRADE_NOTIFY] Trūksta parametrų – pranešimas nesiųstas.")
            return False

        # Parenkam ikoną pagal pelną
        icon = "💰" if profit_pct >= 0 else "🔻"

        # Formatuojam skaičius
        pct = f"{profit_pct:+.2f}%"
        usd = f"({profit_usdc:+.2f} USDC)"
        bal = f"{balance:,.2f}".replace(",", " ")  # ne kableliai, kad būtų aiškiau

        # Sukuriam pranešimą
        msg = f"{icon} [SELL] {symbol} {pct} {usd}\n💼 Balansas: {bal} USDC"

        # Siunčiam
        return notify(msg)

    except Exception as e:
        print(f"❌ [TRADE_NOTIFY] Klaida generuojant pranešimą: {e}")
        return False
