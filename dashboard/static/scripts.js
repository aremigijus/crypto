// ============================================================
// scripts.js — Safe AI Dashboard v11 (final)
// - Dinaminis kainų formatavimas (be nereikalingų „.000“ uodegų)
// - Tikras „Live duomenys“ indikatorius (aktyvus / tikrinama / sustojęs)
// - Išlaikytas visas v7 funkcionalumas (grafikai, AI, rizika ir t.t.)
// ============================================================

console.log("✅ scripts.js v11 (final loaded)");

// ------------------------------------------------------------
// Universalios pagalbinės funkcijos
// ------------------------------------------------------------
function $(id){ return document.getElementById(id); }
function setText(id,t){ const e=$(id); if(e) e.textContent=t; }
function safeSet(id,val){ const e=$(id); if(e) e.textContent=val; }
function fmt(n,d=2){ const x=Number(n); return Number.isFinite(x)?x.toFixed(d):"0.00"; }
function fmtPct(x,d=2){ const n=Number(x); if(!Number.isFinite(n))return"0.00%"; const s=n>=0?"+":""; return `${s}${n.toFixed(d)}%`; }
function humanDurationFromSec(sec){
  const s=Math.floor(sec||0), m=Math.floor(s/60), h=Math.floor(m/60), d=Math.floor(h/24);
  const mm=String(m%60).padStart(2,"0"), hh=String(h%24).padStart(2,"0");
  if(d>0) return `${d}d ${hh}:${mm}`;
  if(h>0) return `${h}:${mm}`;
  return `${m}m`;
}
async function getJSON(url){
  const r=await fetch(url,{cache:"no-store"});
  if(!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

// ------------------------------------------------------------
// Dinaminis kainų formatavimas (be „.000“ uodegų)
// ------------------------------------------------------------
function priceDecimals(p){
  const v = Math.abs(Number(p)||0);
  if(!Number.isFinite(v) || v===0) return 2;
  if(v < 0.1) return 8;      // labai pigioms (pvz., SHIB)
  if(v < 1)   return 6;      // pigioms
  if(v < 1000)return 4;      // vidutinėms
  return 2;                  // didelėms (BTC ir pan.)
}
function fmtPrice(p){
  const d = priceDecimals(p);
  return Number(p).toFixed(d);
}
function changedEnough(oldVal, newVal){
  const d = priceDecimals(newVal);
  const step = Math.pow(10, -d);
  return Math.abs(Number(newVal) - Number(oldVal)) >= step;
}

// ============================================================
// 🛡️ Rizikos būsena
// ============================================================
// ============================================================
// 🛡️ Rizikos būsena (su spalvomis)
// ============================================================
async function refreshRisk(){
  try{
    const r = await getJSON("/api/risk_summary");
    const dd_day   = r.dd_day_pct ?? r.day_dd_pct ?? 0;
    const dd_week  = r.dd_week_pct ?? r.week_dd_pct ?? 0;
    const dd_month = r.dd_month_pct ?? r.month_dd_pct ?? 0;
    setText("dd_day", fmtPct(dd_day));
    setText("dd_week", fmtPct(dd_week));
    setText("dd_month", fmtPct(dd_month));

    const el = $("risk_status");
    if(el){
      const status = String(r.status || "OK").toUpperCase();
      el.textContent = status;
      el.classList.remove("risk-ok", "risk-stop");
      if(status === "STOP") el.classList.add("risk-stop");
      else el.classList.add("risk-ok");
    }
  }catch(e){ console.warn("risk fail:", e); }
}


// ============================================================
// 💰 Kapitalas ir PnL
// ============================================================
function updatePnL(id,val){
  const el=$(id); if(!el) return;
  const v=Number(val||0);
  el.style.transition="color .3s";
  if(v>0.01){ el.style.color="#24c76f"; el.innerHTML=`+${v.toFixed(2)}% ▲`; }
  else if(v<-0.01){ el.style.color="#ff3b30"; el.innerHTML=`${v.toFixed(2)}% ▼`; }
  else { el.style.color="#ccc"; el.textContent="0.00%"; }
}
async function refreshSummary(){
  try{
    const s=await getJSON("/api/summary");
    safeSet("equity_value", fmt(s.equity)+" USDC");
    safeSet("free_value", fmt(s.free_usdc)+" USDC");
    safeSet("used_value", fmt(s.used_usdc)+" USDC");
    updatePnL("day_pnl", s.day_pnl_pct);
    updatePnL("total_pnl", s.total_pnl_pct);
  }catch(e){ console.warn("summary fail:", e); }
}

// ============================================================
// 🕒 Runtime indikatorius (uptime tikeris)
// ============================================================
const _runtimeState={ baseUptimeSec:0, fetchedAtMs:0, startedAt:"-", mode:"TEST", timer:null };
function _fmtUptime(secTotal){
  const s=Math.max(0, Number(secTotal)|0), d=Math.floor(s/86400),
        h=Math.floor((s%86400)/3600), m=Math.floor((s%3600)/60), ss=Math.floor(s%60);
  if(d>0) return `${d}d ${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(ss).padStart(2,"0")}`;
  return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(ss).padStart(2,"0")}`;
}
function _renderRuntimeDom(uptimeSec, startedAt, mode){
  setText("runtime", _fmtUptime(uptimeSec));
  if(startedAt && startedAt!="-"){
    try{
      const localStarted=new Date(startedAt.endsWith("Z")?startedAt:(startedAt+"Z")).toLocaleString("lt-LT",{hour12:false});
      setText("started_at", localStarted);
    }catch(_){}
  }
  const modeEl=$("bot-mode"), modeText=$("bot-mode-text");
  if(modeEl && modeText){
    const m=(mode||"TEST").toUpperCase();
    if(m==="LIVE"||m==="MAINNET"){ modeEl.classList.add("live"); modeText.textContent="LIVE režimas"; }
    else{ modeEl.classList.remove("live"); modeText.textContent="TEST režimas"; }
  }
  const nowClock=$("now_clock"); if(nowClock){ nowClock.textContent=new Date().toLocaleTimeString("lt-LT",{hour12:false}); }
}
function _startRuntimeTicker(){
  if(_runtimeState.timer) return;
  _runtimeState.timer=setInterval(()=>{
    const delta=Math.floor((Date.now()-_runtimeState.fetchedAtMs)/1000);
    const sec=_runtimeState.baseUptimeSec+delta;
    _renderRuntimeDom(sec,_runtimeState.startedAt,_runtimeState.mode);
  },1000);
}
async function refreshRuntime(){
  try{
    const r=await getJSON("/api/runtime");
    _runtimeState.baseUptimeSec=Math.max(0, Number(r.uptime||0));
    _runtimeState.fetchedAtMs=Date.now();
    _runtimeState.startedAt=r.started_at||"-";
    _runtimeState.mode=(r.mode||"TEST").toUpperCase();
    _renderRuntimeDom(_runtimeState.baseUptimeSec,_runtimeState.startedAt,_runtimeState.mode);
    _startRuntimeTicker();
  }catch(e){ console.warn("runtime fail:", e); }
}

// ============================================================
// 🧠 AI santrauka + Sizer
// ============================================================
async function refreshAISummary(){
  try{
    const a=await getJSON("/api/ai_summary");
    safeSet("ai_accuracy", fmtPct(a.accuracy_pct));
    safeSet("ai_avg", fmtPct(a.avg_pnl_pct));
    safeSet("ai_signals", a.active_signals);
  }catch(e){ console.warn("ai_summary fail:", e); }
}
function updateProgressBar(id, pct){
  const el=$(id); if(!el) return;
  const v=Math.min(100, Math.max(0, Number(pct||0)));
  el.style.width=v.toFixed(2)+"%";
  if(v>=80) el.style.background="#ff3b30";
  else if(v>=50) el.style.background="#ffb84d";
  else el.style.background="#24c76f";
}
async function refreshAISizer(){
  try{
    const a=await getJSON("/api/ai_sizer");
    safeSet("min_trade_usdc", fmt(a.min_trade_usdc));
    safeSet("max_trade_usdc", fmt(a.max_trade_usdc));
    safeSet("boost_avg", fmt(a.boost_avg));
    safeSet("vol_avg", fmt(a.vol_avg));
    safeSet("sizer_max_positions", a.max_positions);
    safeSet("sizer_open_positions", a.open_positions);
    safeSet("sizer_portfolio_usage", fmt(a.portfolio_usage_pct)+"%");
    safeSet("risk_max_positions", a.max_positions);
    safeSet("risk_open_positions", a.open_positions);
    safeSet("risk_portfolio_usage", fmt(a.portfolio_usage_pct)+"%");
    updateProgressBar("portfolio_bar", a.portfolio_usage_pct);
    updateProgressBar("sizer_portfolio_bar", a.portfolio_usage_pct);
  }catch(e){ console.warn("ai_sizer fail:", e); }
}

// ============================================================
// 📈 Grafikai (Chart.js)
// ============================================================
const charts={};
function makeLineChart(id,labels,data,labelText){
  const c=$(id); if(!c) return;
  if(charts[id]) charts[id].destroy();
  charts[id]=new Chart(c,{
    type:"line",
    data:{labels, datasets:[{label:labelText, data, borderColor:"#24c76f", tension:.15, borderWidth:2, pointRadius:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:"#aaa"},grid:{color:"rgba(255,255,255,0.05)"}},
              y:{ticks:{color:"#aaa"},grid:{color:"rgba(255,255,255,0.05)"}}}}
  });
}
async function refreshCharts(){
  try{
    const p=await getJSON("/api/ai_performance");
    const L=p.labels||[], eq=p.equity_pct||[], ai=p.ai_perf_pct||eq;
    if($("equityChart")) makeLineChart("equityChart", L, eq, "Equity %");
    if($("aiPerfChart")) makeLineChart("aiPerfChart", L, ai, "AI Performance %");
    if($("equityPctChart")) makeLineChart("equityPctChart", L, eq, "Equity % nuo starto");
  }catch(e){ console.error("charts fail:", e); }
}

// ============================================================
// 🧾 Atidarytos pozicijos — struktūra (statinė dalis)
// ============================================================
let lastSymbols=[];
async function refreshOpenPositions(){
  const body=$("open_positions_body");
  if(!body) return;
  try{
    const d=await getJSON("/api/open_positions");
    const rows=d.positions||[];
    const newSymbols=rows.map(p=>String(p.symbol||"").replace(/USDC$/i,""));
    const hasChanged=JSON.stringify(newSymbols)!==JSON.stringify(lastSymbols);
    if(!hasChanged) return;
    lastSymbols=newSymbols;

    body.innerHTML=rows.map(p=>{
      const symbol=String(p.symbol||"").replace(/USDC$/i,"");
      const pnlPct=Number(p.pnl_pct||0);
      const pnlUsd=Number(p.pnl_usdc||0);
      const colorClass=pnlPct>0?"pnl-pos":pnlPct<0?"pnl-neg":"pnl-neutral";
      return `
        <tr>
          <td>${symbol}</td>
          <td>${fmt(p.qty,4)}</td>
          <td>${fmtPrice(p.entry_price)}</td>
          <td class="live-price">${fmtPrice(p.current_price ?? p.entry_price)}</td>
          <td class="${colorClass}">${pnlPct.toFixed(2)}%</td>
          <td class="${colorClass}">${pnlUsd.toFixed(2)}</td>
          <td>${fmt(p.confidence||0,2)}</td>
          <td>${humanDurationFromSec(p.held_for_sec)}</td>
        </tr>`;
    }).join("");
  }catch(e){ console.error("open_positions fail:", e); }
}

// ============================================================
// 🟢🔴 „Live duomenys“ indikatorius
// - id="live-indicator" (taškas) – prideda klases: live-ok / live-warn / live-bad
// - id="live-indicator-text" (tekstas) – rodo būseną
// ============================================================
let _lastLiveUpdateMs = 0;
function _setLiveState(state){
  const dot = $("live-indicator");
  const txt = $("live-indicator-text");
  const set = (t, clsOk, clsWarn, clsBad)=>{
    if(!dot && !txt) return;
    if(dot){
      dot.classList.remove("live-ok","live-warn","live-bad");
      if(clsOk) dot.classList.add(clsOk);
      if(clsWarn) dot.classList.add(clsWarn);
      if(clsBad) dot.classList.add(clsBad);
    }
    if(txt) txt.textContent = t;
  };
  if(state==="ok")   set("Duomenys aktyvūs", "live-ok");
  if(state==="wait") set("tikrinama...", null, "live-warn");
  if(state==="bad")  set("srautas sustojęs", null, null, "live-bad");
}
_setLiveState("wait");
setInterval(()=>{
  const age = Date.now() - _lastLiveUpdateMs;
  if(_lastLiveUpdateMs===0){ _setLiveState("wait"); return; }
  if(age > 15000) _setLiveState("bad");
  else _setLiveState("ok");
}, 3000);

// ============================================================
// 🔄 Gyvi duomenys — DABARTINĖ + PELNAS % + USDC
// ============================================================
async function refreshLiveData(){
  try{
    const json=await getJSON("/api/live_positions");
    if(!json || !json.success || !json.data) return;

    _lastLiveUpdateMs = Date.now(); // pažymime, kad srautas gyvas

    const updates=json.data;
    const rows=document.querySelectorAll("#open_positions_body tr");

    for(const row of rows){
      const cellSymbol=row.cells[0]?.textContent?.trim();
      if(!cellSymbol) continue;

      const matchKey=Object.keys(updates).find(
        s=>s.toUpperCase()===cellSymbol.toUpperCase()|| s.replace(/USDC$/i,"")===cellSymbol
      );
      if(!matchKey) continue;

      const info=updates[matchKey];
      const currCell=row.cells[3];
      const pnlPctCell=row.cells[4];
      const pnlUsdCell=row.cells[5];

      // --- DABARTINĖ KAINA (dinamiškai formatuojama) ---
      const oldText = currCell.textContent || "0";
      const oldP = Number(oldText.replace(",", "."));
      const newP = Number(info.price || 0);

      if(Number.isFinite(newP) && newP>0 && (oldP===0 || changedEnough(oldP, newP))){
        currCell.textContent = fmtPrice(newP);
        currCell.classList.remove("up","down");
        if(oldP && newP>oldP) currCell.classList.add("up");
        else if(oldP && newP<oldP) currCell.classList.add("down");
        setTimeout(()=>currCell.classList.remove("up","down"),800);
      }

      // --- PELNAS % ---
      const pnlPct=Number(info.pnl_pct||0);
      pnlPctCell.textContent=`${pnlPct>=0?"+":""}${pnlPct.toFixed(2)}%`;
      pnlPctCell.classList.remove("pnl-pos","pnl-neg","pnl-neutral");
      if(pnlPct>0) pnlPctCell.classList.add("pnl-pos");
      else if(pnlPct<0) pnlPctCell.classList.add("pnl-neg");
      else pnlPctCell.classList.add("pnl-neutral");

      // --- PELNAS USDC ---
      const pnlUsd=Number(info.pnl_usdc||0);
      pnlUsdCell.textContent=pnlUsd.toFixed(2);
      pnlUsdCell.classList.remove("pnl-pos","pnl-neg","pnl-neutral");
      if(pnlUsd>0) pnlUsdCell.classList.add("pnl-pos");
      else if(pnlUsd<0) pnlUsdCell.classList.add("pnl-neg");
      else pnlUsdCell.classList.add("pnl-neutral");
    }
  }catch(e){
    console.warn("refreshLiveData fail:",e);
  }
}

// ============================================================
// 🌈 Spalvų CSS klasės (užtikrintai pridėtos)
// ============================================================
const style = document.createElement("style");
style.textContent = `
  .pnl-pos { color: #24c76f !important; font-weight: 600; }
  .pnl-neg { color: #ff3b30 !important; font-weight: 600; }
  .pnl-neutral { color: #ccc !important; }

  .up { background-color: rgba(36,199,111,0.15); transition: background-color 0.3s; }
  .down { background-color: rgba(255,59,48,0.15); transition: background-color 0.3s; }

  /* Live indikatorius (taškas kairėje viršuje) */
  #live-indicator { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:8px; vertical-align:middle; }
  .live-ok { background:#24c76f; box-shadow:0 0 8px rgba(36,199,111,.7); }
  .live-warn { background:#ffb84d; box-shadow:0 0 8px rgba(255,184,77,.7); }
  .live-bad { background:#ff3b30; box-shadow:0 0 8px rgba(255,59,48,.7); }
`;
document.head.appendChild(style);

// ============================================================
// 🔁 Bendras atnaujinimų planuotojas (be struktūros perpiešimo kas 2s)
// ============================================================
async function refreshAllLight(){
  await Promise.allSettled([
    refreshSummary(),
    refreshRisk(),
    refreshAISummary(),
    refreshAISizer(),
    refreshCharts(),
    refreshRuntime()
  ]);
}

// ============================================================
// 🧹 Pilnas atstatymas + boto perkrovimas (valdymo skydelio mygtukui)
// ============================================================
async function fullResetAndRestart(){
  const statusEl=$("reset-status");
  if(!confirm("⚠️ Ar tikrai nori visiškai išvalyti sistemą ir paleisti botą iš naujo?")) return;
  if(statusEl) statusEl.textContent="🧹 Vykdomas sistemos valymas...";
  try{
    const resetRes=await fetch("/api/full_reset",{method:"POST"}); const reset=await resetRes.json();
    if(!reset.success){ if(statusEl) statusEl.textContent="❌ Klaida valant: "+(reset.error||"Nežinoma"); return; }
    if(statusEl) statusEl.textContent="✅ Failai išvalyti. Perkraunamas botas...";
    const restartRes=await fetch("/api/restart_bot",{method:"POST"}); const re=await restartRes.json();
    if(re.success){ if(statusEl) statusEl.textContent="✅ Botas sėkmingai paleistas iš naujo."; setTimeout(()=>location.reload(),5000); }
    else{ if(statusEl) statusEl.textContent="❌ Nepavyko paleisti boto iš naujo."; }
  }catch(err){ if(statusEl) statusEl.textContent="❌ Klaida: "+err.message; }
}

// ============================================================
// ⏱️ Laikrodis (jei naudojamas atskirai)
// ============================================================
(function tickClock(){
  const el=$("clock"); if(!el) return;
  setInterval(()=>{ el.textContent=new Date().toLocaleTimeString("lt-LT",{hour12:false}); },1000);
})();

// ============================================================
// ⚙️ Funkcijos
// ============================================================

async function loadConfig() {
  const resp = await fetch("/config");
  const cfg = await resp.json();

  document.querySelectorAll("[data-key]").forEach(el => {
    const key = el.dataset.key;
    const parts = key.split(".");
    let val = cfg;
    for (const p of parts) {
      if (val && typeof val === "object") val = val[p];
    }
    if (val !== undefined) el.value = val;
  });
}

async function saveConfigValue(key, value) {
  const payload = {};
  const parts = key.split(".");
  let ref = payload;
  parts.forEach((p, i) => {
    if (i === parts.length - 1) {
      ref[p] = value;
    } else {
      ref[p] = {};
      ref = ref[p];
    }
  });

  const resp = await fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (resp.ok) showToast("✅ Išsaugota");
  else showToast("❌ Klaida", true);
}

function showToast(message, isError = false) {
  const el = document.getElementById("toast");
  if (!el) {
    console.warn("⚠️ Toast elementas nerastas, pranešimas:", message);
    return;
  }
  el.textContent = message;
  el.style.background = isError ? "#a00" : "#0a0";
  el.style.opacity = "1";
  setTimeout(() => (el.style.opacity = "0"), 3500);
}

async function triggerFullReset() {
  if (!confirm("⚠️ Ar tikrai atstatyti sistemą ir paleisti botą iš naujo?")) return;
  showToast("🔄 Vykdomas sistemos atstatymas...", false);
  try {
    const res = await fetch("/api/reset_and_restart", { method: "POST" });
    const data = await res.json();

    if (data.success) {
      showToast("✅ Sistema atstatyta. Vykdomas boto paleidimas...");
      // Automatinis puslapio perkrovimas po 2 s, kai Flask jau gyvas
      setTimeout(() => {
        window.location.reload();
      }, 2000);
    } else {
      showToast("❌ Klaida: " + (data.error || "Nežinoma"), true);
    }
  } catch (err) {
    console.error("Full reset klaida:", err);
    showToast("❌ Nepavyko susisiekti su serveriu (gal Flask persikrauna?)", true);
  }
}


async function triggerFullReset() {
  if (!confirm("⚠️ Ar tikrai atstatyti sistemą ir paleisti botą iš naujo?")) return;
  const res = await fetch("/api/reset_and_restart", { method: "POST" });
  const data = await res.json();
  if (data.success) showToast("✅ Sistema atstatyta ir botas paleistas iš naujo");
  else showToast("❌ Klaida: " + (data.error || "Nežinoma"), true);
}


async function restartBot() {
  if (!confirm("Perkrauti botą?")) return;
  await fetch("/api/restart_bot", { method: "POST" });
  showToast("♻️ Botas perkraunamas");
}

// ============================================================
// 🧾 Sandorių istorijos puslapis (trades.html) su filtru ir paieška
// ============================================================
async function refreshTrades(){
  try{
    const data = await getJSON("/api/trade_activity");
    const trades = data.trades || [];
    const winRate = Number(data.win_rate || 0);
    const avgHold = Number(data.avg_hold_sec || 0);

    // --- Nustatome filtrus ---
    const filterType = (document.getElementById("tradeFilter")?.value || "ALL").toUpperCase();
    const searchText = (document.getElementById("tradeSearch")?.value || "").trim().toLowerCase();

    // --- Filtravimas pagal įvykį ir paiešką ---
    const filtered = trades.filter(t=>{
      const ev = String(t.event || "").toUpperCase();
      const sym = String(t.symbol || "").toLowerCase();
      const reason = String(t.reason || "").toLowerCase();
      const matchEvent = (filterType === "ALL" || ev === filterType);
      const matchSearch = (!searchText || sym.includes(searchText) || reason.includes(searchText));
      return matchEvent && matchSearch;
    });

    // === Santrauka viršuje ===
    setText("sum-win-rate", winRate.toFixed(1) + "%");
    setText("sum-held", humanDurationFromSec(avgHold));

    const sells = filtered.filter(t => String(t.event).toUpperCase() === "SELL");
    const pnlSum = sells.reduce((a,t)=>a+(t.pnl_pct||0),0);
    const pnlAvg = sells.length ? pnlSum / sells.length : 0;

    setText("sum-day-pnl", pnlAvg.toFixed(2) + "%");
    setText("sum-trades", sells.length);
    const usdcSum = sells.reduce((a,t)=>a+(t.usd_value||0),0);
    setText("sum-day-usdc", usdcSum.toFixed(2));

    // === Lentelė ===
    const body = document.querySelector("#tbl-trades tbody");
    if(!body) return;
    if(!filtered.length){
      body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:#888;">Nėra įrašų</td></tr>`;
      return;
    }

    body.innerHTML = filtered.reverse().map(t=>{
      const dt = t.ts ? new Date(t.ts) : null;
      const date = dt ? dt.toLocaleDateString("lt-LT") : "-";
      const time = dt ? dt.toLocaleTimeString("lt-LT",{hour12:false}) : "-";
      const ev = String(t.event||"").toUpperCase();
      const coin = String(t.symbol||"").replace(/USDC$/,"");
      const color = ev==="SELL" ? (t.pnl_pct>0?"pnl-pos":t.pnl_pct<0?"pnl-neg":"pnl-neutral") : "";
      return `
        <tr>
          <td>${date}</td>
          <td>${time}</td>
          <td>${ev}</td>
          <td>${coin}</td>
          <td>${fmt(t.qty,4)}</td>
          <td>${fmtPrice(t.price)}</td>
          <td class="${color}">${t.pnl_pct ? t.pnl_pct.toFixed(2)+"%" : "-"}</td>
          <td>${t.hold_time_str || humanDurationFromSec(t.hold_sec||0)}</td>
        </tr>`;
    }).join("");

    // --- Atnaujinimo laikas ---
    const upd = document.getElementById("log-update");
    if(upd) upd.textContent = "Atnaujinta: " + new Date().toLocaleTimeString("lt-LT",{hour12:false});

  }catch(e){
    console.error("refreshTrades fail:", e);
  }
}

// 🔁 Filtrų įvykiai (kai pasirenkamas arba įvedamas tekstas)
const filterSel = document.getElementById("tradeFilter");
const searchInput = document.getElementById("tradeSearch");
if(filterSel) filterSel.addEventListener("change", refreshTrades);
if(searchInput) searchInput.addEventListener("input", () => {
  clearTimeout(window._searchTimer);
  window._searchTimer = setTimeout(refreshTrades, 400);
});

// ============================================================
// 📊 7 dienų vidutinis dienos PnL grafikas (trades.html)
// ============================================================
async function refreshTradePnlChart(){
  try{
    const data = await getJSON("/api/trade_activity");
    const trades = data.trades || [];
    if(!trades.length) return;

    // Grupavimas pagal dienas
    const daily = {};
    for(const t of trades){
      const ev = String(t.event||"").toUpperCase();
      if(ev !== "SELL") continue;
      const ts = t.ts ? new Date(t.ts) : null;
      if(!ts) continue;
      const dayKey = ts.toISOString().slice(0,10);
      if(!daily[dayKey]) daily[dayKey] = [];
      daily[dayKey].push(t.pnl_pct || 0);
    }

    // Vidurkiai pagal dieną
    const days = Object.keys(daily).sort().slice(-7);
    const labels = days.map(d => d.slice(5)); // rodom tik MM-DD
    const avgPnL = days.map(d => {
      const vals = daily[d];
      return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : 0;
    });

    // Kurti arba atnaujinti grafiką
    const ctx = document.getElementById("tradePnlChart");
    if(!ctx) return;

    if(window._tradePnlChart){ window._tradePnlChart.destroy(); }
    window._tradePnlChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "Vidutinis dienos PnL (%)",
          data: avgPnL,
          backgroundColor: avgPnL.map(v=>v>=0?"rgba(36,199,111,0.6)":"rgba(255,59,48,0.6)")
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ctx.parsed.y.toFixed(2)+"%"
            }
          }
        },
        scales: {
          x: { ticks:{ color:"#aaa" }, grid:{ color:"rgba(255,255,255,0.05)" } },
          y: { ticks:{ color:"#aaa" }, grid:{ color:"rgba(255,255,255,0.05)" } }
        }
      }
    });

  }catch(e){
    console.error("refreshTradePnlChart fail:", e);
  }
}

// ============================================================
// 📊 AI kokybės grafikas (iš /api/ai_metrics)
// ============================================================
// ============================================================
// 📊 AI kokybės grafikas (iš /api/ai_metrics)
// ============================================================
async function refreshAIMetricsChart(){
  try{
    const data = await getJSON("/api/ai_metrics?limit=100");
    const metrics = data.metrics || [];
    if(!metrics.length) return;

    const labels = metrics.map(m => {
      const d = new Date(m.ts);
      return d.toLocaleTimeString("lt-LT",{hour:"2-digit",minute:"2-digit"});
    });
    const conf = metrics.map(m => m.avg_confidence || 0);
    const pnl  = metrics.map(m => m.avg_pnl || 0);
    const win  = metrics.map(m => m.win_rate || 0);

    const ctx = document.getElementById("aiMetricsChart");
    if(!ctx) return;
    if(window._aiMetricsChart) window._aiMetricsChart.destroy();

    // --- Gradientai ---
    const gConf = ctx.getContext("2d").createLinearGradient(0,0,0,200);
    gConf.addColorStop(0,"rgba(0,188,212,0.5)");
    gConf.addColorStop(1,"rgba(0,188,212,0)");
    const gWin = ctx.getContext("2d").createLinearGradient(0,0,0,200);
    gWin.addColorStop(0,"rgba(36,199,111,0.5)");
    gWin.addColorStop(1,"rgba(36,199,111,0)");
    const gPnl = ctx.getContext("2d").createLinearGradient(0,0,0,200);
    gPnl.addColorStop(0,"rgba(255,159,64,0.5)");
    gPnl.addColorStop(1,"rgba(255,159,64,0)");

    window._aiMetricsChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Confidence", data: conf, borderColor: "#00bcd4", backgroundColor: gConf, tension: 0.3 },
          { label: "Win Rate (%)", data: win, borderColor: "#24c76f", backgroundColor: gWin, tension: 0.3 },
          { label: "Avg PnL (%)", data: pnl, borderColor: "#ff9f40", backgroundColor: gPnl, tension: 0.3 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels:{ color:"#ccc" } },
          tooltip: { callbacks:{ label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(3)}` } }
        },
        scales: {
          x: { ticks:{ color:"#aaa" }, grid:{ color:"rgba(255,255,255,0.05)" } },
          y: { ticks:{ color:"#aaa" }, grid:{ color:"rgba(255,255,255,0.05)" } }
        }
      }
    });

    // --- Santrauka virš grafiko ---
    const avg_conf = conf.reduce((a,b)=>a+b,0)/conf.length;
    const avg_win  = win.reduce((a,b)=>a+b,0)/win.length;
    const avg_pnl  = pnl.reduce((a,b)=>a+b,0)/pnl.length;
    setText("sum_conf", avg_conf.toFixed(3));
    setText("sum_win", avg_win.toFixed(2)+"%");
    setText("sum_pnl", avg_pnl.toFixed(2)+"%");

  }catch(e){ console.error("refreshAIMetricsChart fail:", e); }
}

if(document.body.dataset.page === "dashboard"){
  refreshAIMetricsChart();
  setInterval(refreshAIMetricsChart, 30000); // kas 30 s
}


// 🔁 paleidžiam automatinį atnaujinimą
if(document.body.dataset.page === "dashboard"){
  refreshAIMetricsChart();
  setInterval(refreshAIMetricsChart, 30000); // kas 30 s
}


// Įjungiam atnaujinimą tik trades.html puslapyje
if(document.body.dataset.page === "trades"){
  refreshTradePnlChart();
  setInterval(refreshTradePnlChart, 30000);
}

// ============================================================
// 🚀 Startas (inicializacija po užkrovimo)
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  // 🔹 Konfigūracijų įkėlimas (tik jei yra /config endpointas)
  if (window.location.pathname.includes("settings")) {
    if (typeof loadConfig === "function") loadConfig();

    // Momentinis išsaugojimas
    document.querySelectorAll("[data-key]").forEach(el => {
      el.addEventListener("change", e => {
        const key = el.dataset.key;
        let val = el.value;

        if (val === "true" || val === "false") {
          val = (val === "true");
        } else if (!isNaN(val) && val.trim() !== "") {
          val = parseFloat(val);
        }

        saveConfigValue(key, val);
      });
    });

    // Išsamūs nustatymai toggle
    const advToggle = document.querySelector(".toggle-advanced");
    const advSection = document.querySelector(".advanced");

    if (advToggle && advSection) {
      advToggle.addEventListener("click", () => {
        advSection.style.display = advSection.style.display === "block" ? "none" : "block";
        advToggle.textContent = advSection.style.display === "block"
          ? "▲ Slėpti išsamius nustatymus"
          : "▼ Išsamūs nustatymai";
      });
    }
  }
  
  // 🔹 Dashboard / Trades puslapio atnaujinimai
  if (typeof refreshSummary === "function") refreshSummary();
  if (typeof refreshRisk === "function") refreshRisk();
  if (typeof refreshAISummary === "function") refreshAISummary();
  if (typeof refreshAISizer === "function") refreshAISizer();
  if (typeof refreshCharts === "function") refreshCharts();
  if (typeof refreshRuntime === "function") refreshRuntime();
  if (typeof refreshOpenPositions === "function") refreshOpenPositions();
  if (typeof refreshLiveData === "function") refreshLiveData();

// 🔹 Jei atidarytas trades.html puslapis — paleidžiam istorijos atnaujinimus
  if (document.body.dataset.page === "trades") {
    refreshTrades();
    refreshTradePnlChart();
    setInterval(refreshTrades, 10000);
    setInterval(refreshTradePnlChart, 30000);
  }

  // 🔁 Periodiniai atnaujinimai
  if (typeof refreshAllLight === "function") setInterval(refreshAllLight, 10000);
  if (typeof refreshAISizer === "function") setInterval(refreshAISizer, 5000);
  if (typeof refreshOpenPositions === "function") setInterval(refreshOpenPositions, 30000);
  if (typeof refreshLiveData === "function") setInterval(refreshLiveData, 2000);
  if (typeof refreshSummary === "function") setInterval(refreshSummary, 10000);
});
