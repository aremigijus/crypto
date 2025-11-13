# 🧭 COMPAT_MATRIX_AUTO.md — Safe AI Dashboard v6 (auto-generated)

**Sugeneruota:** 2025-11-12 22:06:04
**Projekto kelias:** C:\crypto\dashboard

Šis failas automatiškai sugeneruotas iš Flask API endpoint’ų dokumentacijos.
Naudojama CI/testavimo tikslams, kad būtų užtikrintas API ↔ JS ↔ HTML suderinamumas.

---

## Endpoint’ų sąrašas

| Endpoint | Aprašymas | Grąžina JSON laukus |
|-----------|------------|----------------------|
| `/api/summary` | Bendri KPI rodikliai | equity<br>free_usdc<br>used_usdc<br>day_pnl_pct<br>total_pnl_pct<br>mode<br>runtime_hms |
| `/api/open_positions` | Atidarytos pozicijos | positions[].symbol<br>positions[].qty<br>positions[].entry_price<br>positions[].current_price<br>positions[].pnl_pct<br>positions[].pnl_usdc<br>positions[].confidence<br>positions[].held_for_sec |
| `/api/risk_summary` | Rizikos santrauka | day_dd_pct<br>week_dd_pct<br>month_dd_pct<br>status<br>limits.max_positions<br>limits.max_exposure_pct |
| `/api/ai_summary` | AI veikimo santrauka | accuracy_pct<br>avg_pnl_pct<br>active_signals |
| `/api/ai_sizer` | AI dydžių/boost suvestinė | min_trade_usdc<br>max_trade_usdc<br>boost_avg<br>vol_avg<br>max_positions<br>open_positions<br>portfolio_usage_pct |
| `/api/ai_performance` | Grafikų duomenys | labels[]<br>equity_pct[]<br>ai_perf_pct[] |
| `/api/trade_activity` | Prekybos žurnalas | trades[].ts<br>trades[].event<br>trades[].symbol<br>trades[].pnl_pct<br>trades[].hold_sec<br>trades[].reason<br>avg_hold_sec<br>win_rate |
| `/api/runtime` | Boto veikimo laikas | uptime_hms<br>mode<br>ws_connected |

---
**Sukurta automatiškai iš app.py** 🚀
