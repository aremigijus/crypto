# 🧭 COMPAT_MATRIX.md — Safe AI Dashboard v6 stable

**Versija:** 2025-11-07  
**Tikslas:** užtikrinti 100 % suderinamumą tarp Flask API ↔ JavaScript ↔ HTML elementų.

---

## 1️⃣ `/api/summary` → `scripts.js: refreshSummary()`

| API laukas      | JS kintamasis / logika       | HTML elementas (ID) | Tipas | Aprašymas                 |
|-----------------|-------------------------------|----------------------|--------|----------------------------|
| equity          | eq → fmt(eq)                  | `#equity_value`      | float  | Bendras kapitalas          |
| free_usdc       | fr                            | `#free_value`        | float  | Laisvos lėšos              |
| used_usdc       | used + (used/eq %)            | `#used_value`        | float  | Investuotos lėšos          |
| day_pnl_pct     | day                           | `#day_pnl_pct`       | %      | Dienos pelnas              |
| total_pnl_pct   | tot                           | `#total_pnl_pct`     | %      | Bendras pelnas             |
| mode            | mode                          | `#bot-mode`          | str    | TEST / MAINNET režimas     |
| runtime_hms     | runtime_hms                   | `#runtime`           | str    | Veikimo trukmė             |

---

## 2️⃣ `/api/open_positions` → `scripts.js: refreshOpenPositions()`

| API laukas      | JS kintamasis     | HTML elementas             | Tipas  | Aprašymas                           |
|-----------------|-------------------|-----------------------------|--------|--------------------------------------|
| positions[]     | rows[]            | `#open_positions_body`      | array  | Atidarytų pozicijų sąrašas          |
| symbol          | p.symbol          | Lentelės stulpelyje         | str    | Pvz. `BTCUSDC`                      |
| qty             | p.qty             | —                           | float  | Kiekis                              |
| entry_price     | p.entry_price     | —                           | float  | Įėjimo kaina                        |
| current_price   | p.current_price   | —                           | float  | Dabartinė kaina                     |
| pnl_pct         | p.pnl_pct         | —                           | %      | Pelnas procentais                   |
| pnl_usdc        | p.pnl_usdc        | —                           | float  | Pelnas USDC                         |
| confidence      | p.confidence      | —                           | float  | AI pasitikėjimo lygis               |
| held_for_sec    | p.held_for_sec    | —                           | sec    | Pozicijos laikymo trukmė sekundėmis |

---

## 3️⃣ `/api/risk_summary` → `scripts.js: refreshRisk()`

| API laukas     | JS kintamasis | HTML elementas (ID) | Tipas | Aprašymas              |
|----------------|---------------|---------------------|--------|-------------------------|
| dd_day_pct     | dd_day        | `#dd_day`           | %      | Dienos DD               |
| dd_week_pct    | dd_week       | `#dd_week`          | %      | Savaitinis DD           |
| dd_month_pct   | dd_month      | `#dd_month`         | %      | Mėnesinis DD            |
| status         | risk_status   | `#risk_status`      | str    | Rizikos būklė (OK/WARN) |

---

## 4️⃣ `/api/ai_summary` → `scripts.js: refreshAISummary()`

| API laukas     | HTML elementas (ID) | Tipas | Aprašymas               |
|----------------|---------------------|--------|--------------------------|
| accuracy_pct   | `#ai_acc`           | %      | AI signalų tikslumas    |
| avg_pnl_pct    | `#ai_avg_pnl`       | %      | Vidutinis pelnas (%)    |
| active_signals | `#ai_active`        | int    | Aktyvių signalų kiekis  |

---

## 5️⃣ `/api/ai_sizer` → `scripts.js: refreshAISizer()`

| API laukas          | HTML elementas (ID)     | Tipas  | Aprašymas                          |
|----------------------|------------------------|--------|------------------------------------|
| min_trade_usdc       | `#min_trade`           | USDC   | Mažiausias sandorio dydis          |
| max_trade_usdc       | `#max_trade`           | USDC   | Didžiausias sandorio dydis         |
| boost_avg            | `#boost_avg`           | float  | AI „boost“ vidurkis                |
| vol_avg              | `#vol_avg`             | float  | Vidutinė volatilumo reikšmė        |
| max_positions        | `#max_positions`       | int    | Maksimalus pozicijų skaičius       |
| open_positions       | `#open_positions_cnt`  | int    | Šiuo metu atidarytos pozicijos     |
| portfolio_usage_pct  | `#portfolio_usage`     | %      | Portfelio panaudojimo procentas    |

---

## 6️⃣ `/api/ai_performance` → `scripts.js: refreshCharts()`

| API laukas     | JS kintamasis | Naudojamas grafike  | Aprašymas                |
|----------------|----------------|----------------------|---------------------------|
| labels[]       | labels         | x ašis               | Laiko žymos              |
| equity_pct[]   | equityPct      | equityChart          | Equity % nuo starto      |
| ai_perf_pct[]  | aiPct          | aiPerfChart          | AI Performance %          |

---

## 7️⃣ `/api/trade_activity` → `scripts.js: refreshTradeActivity()`

| API laukas     | JS kintamasis | HTML elementas (ID)   | Tipas | Aprašymas                     |
|----------------|---------------|------------------------|--------|--------------------------------|
| trades[]       | allTrades[]   | `#tbl-trades tbody`    | array | Sandorių sąrašas (BUY/SELL)   |
| avg_hold_sec   | —             | `#sum-held`            | sec   | Vidutinė laikymo trukmė       |
| win_rate       | —             | `#sum-win-rate`        | %     | Laimėtų sandorių procentas     |

---

## 8️⃣ `/api/runtime` → `scripts.js: refreshRuntime()`

| API laukas | HTML elementas (ID) | Tipas | Aprašymas              |
|-------------|--------------------|--------|-------------------------|
| uptime      | `#runtime`         | str    | Boto veikimo trukmė     |
| since       | `#runtime-since`   | str    | Pradžios laikas (ISO)   |

---

## 🧮 9️⃣ Duomenų atnaujinimo dažniai ir priklausomybės

| Kategorija | Endpoint | JS funkcija | Atnaujinimo intervalas | Priklauso nuo kitų | Paskirtis |
|-------------|-----------|-------------|-------------------------|--------------------|------------|
| Pagrindinė santrauka | `/api/summary` | `refreshSummary()` | kas 5 s | — | Pagrindiniai PnL ir kapitalo rodikliai |
| Rizika | `/api/risk_summary` | `refreshRisk()` | kas 5 s | `/api/summary` (PnL) | Dienos / savaitės / mėnesio DD |
| AI santrauka | `/api/ai_summary` | `refreshAISummary()` | kas 5 s | `/api/ai_sizer` | Signalų tikslumas ir aktyvumas |
| AI dydžiai | `/api/ai_sizer` | `refreshAISizer()` | kas 5 s | — | AI portfelio ir boost metrika |
| Pozicijos | `/api/open_positions` | `refreshOpenPositions()` | kas 5 s | `/api/summary` | Rodo aktyvias pozicijas ir PnL |
| Grafikai | `/api/ai_performance` | `refreshCharts()` | kas 10 s | `/api/summary`, `/api/ai_summary` | Atvaizduoja equity ir AI performance kreives |
| Prekybos istorija | `/api/trade_activity` | `refreshTradeActivity()` | kas 15 s | `/api/open_positions` | Pirkimų/pardavimų žurnalas |
| Boto veikimo laikas | `/api/runtime` | `refreshRuntime()` | kas 60 s | — | Rodo uptime ir starto laiką |

---

## 🧩 Bendros pastabos

| Tema | Aprašymas |
|------|------------|
| **Laikymo trukmė** | Visi laikai (`held_for_sec`, `hold_sec`) pateikiami sekundėmis; JS formatuoja per `humanDurationFromSec()`. |
| **Coin rodymas** | `trades.html` pašalina `USDC` priesagą – rodo tik bazinę valiutą (pvz. `BTC`). |
| **Grafikų apsauga** | Jei `ai_performance.json` ar `equity_history.json` tušti, backend sugeneruoja testinius duomenis, kad Chart.js neišmestų klaidos. |
| **Testavimas** | `/api/check_compat_matrix` ir `/compat_report` tikrina struktūrą naudodami `COMPAT_MATRIX_AUTO.md`. |
| **CI ataskaita** | Jei testas = 8/8 OK → sistema laikoma 100 % sinchronizuota. |

---

**Suderinta:** 2025-11-07  
**Versija:** Safe AI Dashboard v6 stable  
**Autorius:** CRYPTO BOT Dev Team 🚀
