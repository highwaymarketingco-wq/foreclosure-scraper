"use strict";

let LISTINGS = [];
let META = {};
let filtered = [];
let sortKey = "_grade";
let sortDir = "desc";  // best grades first
let map = null;
let mapMarkers = null;
let detailMap = null;

// Active dataset: "foreclosure" | "multifamily"
let DATASET = "foreclosure";
// Cache so toggling is instant after first load
const DS_CACHE = { foreclosure: null, multifamily: null };

const $ = (id) => document.getElementById(id);

// Helpers to read calc + grade
const getGrade = (l) => (l.raw && l.raw.grade) || null;
const getCalc = (l) => (l.raw && l.raw.calc) || null;
const gradeOrder = { A: 5, B: 4, C: 3, D: 2, F: 1 };

// ------------- Load data -----------------------------------------------------
async function loadDataset(name) {
  // Already loaded — restore from cache
  if (DS_CACHE[name]) {
    LISTINGS = DS_CACHE[name].listings;
    META = DS_CACHE[name].meta;
    DATASET = name;
    refreshDatasetUI();
    initFilters();
    applyFilters();
    fillStats();
    return;
  }

  try {
    if (name === "multifamily") {
      const r = await fetch(`multifamily.json?t=${Date.now()}`);
      if (!r.ok) throw new Error("multifamily.json missing");
      const data = await r.json();
      LISTINGS = data.listings || [];
      META = {
        run_time: data.run_time,
        total: data.total,
        by_source: data.by_source,
        by_state: data.by_state,
        by_county_top: data.by_county_top,
      };
    } else {
      const [listingsRes, metaRes] = await Promise.all([
        fetch(`listings.json?t=${Date.now()}`),
        fetch(`run_meta.json?t=${Date.now()}`),
      ]);
      if (!listingsRes.ok) throw new Error("listings.json missing");
      LISTINGS = await listingsRes.json();
      META = metaRes.ok ? await metaRes.json() : {};
    }
    DS_CACHE[name] = { listings: LISTINGS, meta: META };
  } catch (e) {
    LISTINGS = [];
    META = {};
    if (name === "foreclosure") {
      document.body.insertAdjacentHTML(
        "afterbegin",
        `<div style="background:#ffd2dc;color:#b22a2a;padding:14px 28px;text-align:center;">
         Could not load listings — first run hasn't finished yet, or network error. Reload in a few minutes.</div>`,
      );
    }
  }
  DATASET = name;
  refreshDatasetUI();
  initFilters();
  applyFilters();
  fillStats();
}

function refreshDatasetUI() {
  const isMF = DATASET === "multifamily";
  const title = $("dataset-title");
  if (title) title.textContent = isMF ? "Multifamily Listings" : "Foreclosure Listings";
  document.querySelectorAll(".ds-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.ds === DATASET);
  });
}

// Pre-fetch counts for both datasets so the toggle pills show real numbers
async function preloadDatasetCounts() {
  try {
    const r = await fetch(`multifamily.json?t=${Date.now()}`);
    if (r.ok) {
      const d = await r.json();
      const el = $("ds-mf-count");
      if (el) el.textContent = d.total || 0;
    }
  } catch (e) { /* silent */ }
  try {
    const r = await fetch(`run_meta.json?t=${Date.now()}`);
    if (r.ok) {
      const d = await r.json();
      const el = $("ds-fc-count");
      if (el) el.textContent = d.total || 0;
    }
  } catch (e) { /* silent */ }
}

async function loadData() {
  await Promise.all([loadDataset("foreclosure"), preloadDatasetCounts()]);
  // Wire toggle buttons
  document.querySelectorAll(".ds-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.ds;
      if (target && target !== DATASET) loadDataset(target);
    });
  });
}

// ------------- Stats ---------------------------------------------------------
function fillStats() {
  $("stat-total").textContent = LISTINGS.length;
  const byGrade = { A: 0, B: 0, C: 0, D: 0, F: 0 };
  let posRoi = 0, withBid = 0;
  LISTINGS.forEach((l) => {
    const g = getGrade(l);
    if (g && g.overall) byGrade[g.overall] = (byGrade[g.overall] || 0) + 1;
    const c = getCalc(l);
    if (c && c.roi_pct != null && c.roi_pct > 0) posRoi += 1;
    if (l.opening_bid) withBid += 1;
  });
  $("stat-a").textContent = byGrade.A;
  $("stat-b").textContent = byGrade.B;
  $("stat-c").textContent = byGrade.C;
  $("stat-positive-roi").textContent = posRoi;
  $("stat-with-bid").textContent = withBid;
  const sources = new Set(LISTINGS.map((l) => l.source).filter(Boolean));
  $("stat-sources").textContent = sources.size;

  $("total-badge").textContent = `${LISTINGS.length} total`;
  $("active-badge").textContent = `${withBid} priced`;
  if (byGrade.A > 0) {
    const a = $("a-grade-badge");
    a.style.display = "inline-block";
    a.textContent = `${byGrade.A} A-grade`;
  }
  $("last-updated").textContent = META.run_time
    ? `Updated ${new Date(META.run_time).toLocaleString()}`
    : "Updated recently";
  $("run-source-count").textContent = String(sources.size);
}

// ------------- Filter init ---------------------------------------------------
function initFilters() {
  // Idempotent: loadDataset() calls this on every (re)load + dataset switch, so
  // strip any previously-appended options (keep the first "All …" default)
  // before repopulating — otherwise counties/sources duplicate on each call.
  const resetSelect = (el) => {
    while (el.options.length > 1) el.remove(1);
  };

  const counties = new Set();
  LISTINGS.forEach((l) => l.county && counties.add(`${l.county}, ${l.state || "?"}`));
  const sel = $("filter-county");
  resetSelect(sel);
  Array.from(counties)
    .sort()
    .forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      sel.appendChild(opt);
    });

  const sources = new Set();
  LISTINGS.forEach((l) => l.source && sources.add(l.source));
  const ssel = $("filter-source");
  resetSelect(ssel);
  Array.from(sources)
    .sort()
    .forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      ssel.appendChild(opt);
    });

  ["search", "filter-state", "filter-county", "filter-type", "filter-contact", "filter-land", "filter-source", "filter-distress", "filter-grade", "filter-window", "filter-roi"].forEach((id) =>
    $(id).addEventListener("input", applyFilters),
  );

  document.querySelectorAll(".view-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      $(`view-${btn.dataset.view}`).classList.add("active");
      if (btn.dataset.view === "map") setTimeout(initMap, 60);
    }),
  );

  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (sortKey === k) sortDir = sortDir === "asc" ? "desc" : "asc";
      else {
        sortKey = k;
        sortDir = "asc";
      }
      document.querySelectorAll("th[data-sort]").forEach((t) => t.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
      applyFilters();
    }),
  );

  // Stage toggle — split the board into workflow tracks (foreclosure timeline vs
  // outbound prospecting vs REO). Counts are total-per-stage (independent of the
  // other filters) so you can see the size of each track at a glance.
  document.querySelectorAll(".stage-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".stage-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      STAGE = btn.dataset.stage || "";
      applyFilters();
    }),
  );
  updateStageCounts();

  $("export-csv").addEventListener("click", exportCsv);
  $("close-detail").addEventListener("click", () => $("detail-panel").classList.add("hidden"));
}

// ------------- Filtering + sorting ------------------------------------------
function getSortValue(l, k) {
  if (k === "_grade") {
    const g = getGrade(l);
    return g ? g.overall_score || gradeOrder[g.overall] || 0 : -1;
  }
  if (k === "_arv") {
    const c = getCalc(l) || {};
    const arv = c.arv_expected || 0;
    // Fabricated/unrated ARVs (proxy values >$2M, LOW confidence, or an
    // ungraded listing) shouldn't float to the top of the ARV sort —
    // they're not real comps. Sink them with a sentinel so genuine,
    // graded ARVs rank above them on the default descending sort.
    const g = getGrade(l);
    const dqf = (l.raw && l.raw.data_quality && Array.isArray(l.raw.data_quality.flags))
      ? l.raw.data_quality.flags : [];
    const unrated = !arv || arv > 2000000 || c.arv_confidence === "LOW"
      || dqf.includes("low_arv_confidence") || dqf.includes("no_sqft")
      || !(g && g.overall);
    return unrated ? -1 : arv;
  }
  if (k === "_rehab") return (getCalc(l) || {}).rehab_expected || 0;
  if (k === "_max_bid") return (getCalc(l) || {}).max_bid_70 || 0;
  if (k === "_roi") return (getCalc(l) || {}).roi_pct;
  if (k === "_distress") return (getDistress(l) || {}).score || 0;
  return l[k];
}

// ---- Stage classification: which workflow track a lead is in --------------
// You work these lists differently: foreclosure leads are time-sensitive (act
// before the sale), outbound leads are cold prospects you mail/call. Derived
// client-side from listing_type + sale_date + source — no board field needed.
const STAGE_REO = /hud_homestore|fannie|freddie|homepath|homesteps|hubzu|xome|auction_dot_com|bid4assets|servicelink|gsa_real|usda_rd|treasury_seized|vrm_va|first_citizens|reo\.|foreclosure_dot_com/;
const STAGE_PREFORE = /substitute_trustee|nod_discovery|lis_pendens|rod_acclaim|rod_cott|rod_logan|nc_rod|sc_rod/;
let STAGE = "";

function stageOf(l) {
  const t = (l.listing_type || "").toLowerCase();
  const src = (l.source || "").toLowerCase();
  if (STAGE_REO.test(src) || t === "reo" || t === "auction") return "reo";
  const sd = l.sale_date ? Date.parse(l.sale_date) : NaN;
  const hasSale = !isNaN(sd) && sd >= Date.now() - 14 * 86400000; // sale ~2wk-ago..future
  if (hasSale || t === "foreclosure_sale" || (l.raw && l.raw.upset_bid)) return "foreclosure";
  if (t === "lis_pendens" || t === "bankruptcy" || STAGE_PREFORE.test(src)) return "prefore";
  return "outbound"; // probate/obituary/elderly/divorce/tax-delinquent/vacant/distressed
}

function updateStageCounts() {
  const c = { "": 0, foreclosure: 0, prefore: 0, outbound: 0, reo: 0 };
  LISTINGS.forEach((l) => {
    if (l.raw && l.raw.sold_confirmed) return;
    c[""]++;
    c[stageOf(l)]++;
  });
  document.querySelectorAll(".stage-count").forEach((el) => {
    el.textContent = (c[el.dataset.c] || 0).toLocaleString();
  });
}

function applyFilters() {
  const q = $("search").value.toLowerCase();
  const st = $("filter-state").value;
  const co = $("filter-county").value;
  const ty = $("filter-type").value;
  const land = $("filter-land").value;
  const src = $("filter-source").value;
  const contact = $("filter-contact").value;
  const distress = $("filter-distress").value;
  const minGrade = $("filter-grade").value;
  const minGradeRank = minGrade ? gradeOrder[minGrade] : 0;
  const win = parseInt($("filter-window").value);
  const minRoi = $("filter-roi").value === "" ? null : parseFloat($("filter-roi").value);
  const now = Date.now();
  const wmax = win ? now + win * 86400000 : 0;

  filtered = LISTINGS.filter((l) => {
    // Court-confirmed sales already sold at auction — not opportunities. Hide.
    if (l.raw && l.raw.sold_confirmed) return false;
    if (STAGE && stageOf(l) !== STAGE) return false;
    if (st && l.state !== st) return false;
    if (co && `${l.county || ""}, ${l.state || "?"}` !== co) return false;
    if (ty && l.listing_type !== ty) return false;
    if (src && l.source !== src) return false;
    if (land) {
      // property_kind is unreliable (some houses are mislabeled "land"), so a real
      // structure signal (sqft/year/beds/baths or a known dwelling kind) ALWAYS
      // wins: "Land only" = labeled land AND no structure; "Land + structures" =
      // anything with a structure.
      const pk = (l.property_kind || "").toLowerCase();
      const hasStructure =
        ["single_family", "condo", "mobile", "multi_family", "townhouse", "duplex"].includes(pk) ||
        l.living_sqft > 0 || !!l.year_built || l.bedrooms > 0 || l.bathrooms > 0;
      const isLand = (pk === "land" || pk === "lot" || pk === "vacant") && !hasStructure;
      if (land === "land" && !isLand) return false;
      if (land === "improved" && !hasStructure) return false;
    }
    if (distress) {
      const ds = getDistress(l);
      if (!ds) return false;
      if (distress === "HOT" && ds.tier !== "HOT") return false;
      if (distress === "HOTWARM" && ds.tier === "COLD") return false;
      if (distress === "STACK2" && !(ds.stack >= 2)) return false;
    }
    if (contact) {
      const r = l.raw || {};
      const om = r.owner_mailing || {};
      if (contact === "phone" && !r.owner_phone) return false;
      if (contact === "mailing" && !om.mailing) return false;
      if (contact === "contactable" && !(r.owner_phone || om.mailing)) return false;
      if (contact === "absentee" && !om.absentee) return false;
      if (contact === "out_of_state" && !om.out_of_state) return false;
      if (contact === "mortgage" && !(r.rod && r.rod.has_mortgage)) return false;
      if (contact === "estate_elderly" && !(r.life_events && r.life_events.length)) return false;
      if (contact === "hide_stale" && r.stale_case) return false;
    }
    if (win && l.sale_date) {
      const d = Date.parse(l.sale_date);
      if (isNaN(d) || d < now || d > wmax) return false;
    }
    if (minGradeRank) {
      const g = getGrade(l);
      const r = g && g.overall ? gradeOrder[g.overall] : 0;
      if (r < minGradeRank) return false;
    }
    if (minRoi !== null) {
      const c = getCalc(l);
      const r = c ? c.roi_pct : null;
      if (r == null || r < minRoi) return false;
    }
    if (q) {
      const blob = [
        l.street_address, l.city, l.county, l.state, l.zip_code, l.case_number,
        l.plaintiff, l.defendant, l.trustee, l.source, l.parcel_id,
        (l.raw && l.raw.gis && l.raw.gis.owner) || "",
      ].join(" ").toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });

  // When the operator is filtering by distress, surface hottest-first
  // regardless of the table-header sort (the board reads like a lead queue).
  const effKey = distress ? "_distress" : sortKey;
  const effDir = distress ? "desc" : sortDir;
  filtered.sort((a, b) => {
    let av = getSortValue(a, effKey);
    let bv = getSortValue(b, effKey);
    if (av == null) av = effDir === "asc" ? Infinity : -Infinity;
    if (bv == null) bv = effDir === "asc" ? Infinity : -Infinity;
    if (typeof av === "string") av = av.toLowerCase();
    if (typeof bv === "string") bv = bv.toLowerCase();
    if (av < bv) return effDir === "asc" ? -1 : 1;
    if (av > bv) return effDir === "asc" ? 1 : -1;
    return 0;
  });

  renderTable();
  renderCards();
  // Tier tally over the current filtered set (the operator-board headline).
  let hot = 0, warm = 0;
  filtered.forEach((l) => {
    const t = (getDistress(l) || {}).tier;
    if (t === "HOT") hot++; else if (t === "WARM") warm++;
  });
  const tally = hot || warm ? `  ·  🔥 ${hot} HOT · ${warm} WARM` : "";
  $("result-count").textContent = `${filtered.length} of ${LISTINGS.length} listings${tally}`;
}

// ------------- Format helpers ------------------------------------------------
function fmtMoney(v) { return v ? "$" + Math.round(v).toLocaleString() : ""; }
function fmtNum(v) { return v == null ? "" : v; }
function fmtDate(v) {
  if (!v) return "";
  const d = new Date(v);
  return isNaN(d) ? v : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
}
function fmtPct(v) { return v == null ? "" : `${v.toFixed(1)}%`; }
function fmtType(t) {
  const cls = t || "unknown";
  const label = (t || "unknown").replace(/_/g, " ");
  return `<span class="type-pill type-${cls}">${label}</span>`;
}
function gradeBadge(g) {
  if (!g || !g.overall) return `<span class="grade-badge F" style="opacity:0.4">—</span>`;
  return `<span class="grade-badge ${g.overall}">${g.overall}</span>`;
}
// ------------- Distress (HOT/WARM operator board) ---------------------------
function getDistress(l) { return (l.raw && l.raw.distress_stack) || null; }
const distressLabel = {
  HOT:  { emoji: "🔥", cls: "hot",  txt: "HOT" },
  WARM: { emoji: "🌡", cls: "warm", txt: "WARM" },
};
const catLabel = {
  FINANCIAL: "💰 financial", SALES: "🏷 sale", LEGAL: "⚖ legal",
  LIFE_EVENT: "👤 life-event", PROPERTY: "🏚 property",
};
function distressBadge(ds) {
  if (!ds || !distressLabel[ds.tier]) return "";
  const d = distressLabel[ds.tier];
  const stk = ds.stack >= 2 ? ` ·${ds.stack}×` : "";
  const tip = `${(ds.signals || []).join(", ") || "single signal"} — score ${ds.score}`;
  return `<span class="distress-badge ${d.cls}" title="${tip}">${d.emoji} ${d.txt}${stk}</span>`;
}
function distressChips(ds) {
  if (!ds || !ds.categories || !ds.categories.length || ds.tier === "COLD") return "";
  const chips = ds.categories.map((c) => `<span class="distress-chip">${catLabel[c] || c.toLowerCase()}</span>`).join("");
  const tags = [];
  if (ds.absentee) tags.push(`<span class="distress-chip absentee">absentee</span>`);
  if (ds.out_of_state) tags.push(`<span class="distress-chip absentee">out-of-state</span>`);
  return `<div class="distress-chips">${chips}${tags.join("")}</div>`;
}
function roiCell(roi) {
  if (roi == null) return "";
  const cls = roi > 0 ? "roi-pos" : "roi-neg";
  return `<span class="${cls}">${roi.toFixed(1)}%</span>`;
}

// ------------- Table render --------------------------------------------------
function renderTable() {
  const tb = $("listings-tbody");
  tb.innerHTML = filtered
    .slice(0, 800)
    .map((l, i) => {
      const g = getGrade(l) || {};
      const c = getCalc(l) || {};
      const rowClass = g.overall ? `row-${g.overall}` : "";
      // Bankruptcy listings have no address — show debtor name + chapter so
      // they're identifiable in the table view. Cross-ref hits get a 🏛 prefix.
      const isBkSource = l.source === "national.courtlistener_bankruptcy";
      const cl = isBkSource ? (l.raw && l.raw.courtlistener) || {} : null;
      const bkXref = !isBkSource && l.raw && l.raw.bankruptcy ? l.raw.bankruptcy : null;
      const addrCell = isBkSource
        ? `🏛 ${cl.chapter && cl.chapter !== "?" ? `Ch.${cl.chapter} ` : ""}${(l.defendant || "Bankruptcy filing").slice(0, 60)}`
        : `${bkXref ? "🏛 " : ""}${l.street_address || ""}`;
      const dateCell = isBkSource && cl && cl.date_filed ? cl.date_filed : fmtDate(l.sale_date);
      return `
    <tr class="${rowClass}" data-id="${i}">
      <td>${(() => { const ds = getDistress(l); return ds && distressLabel[ds.tier] ? `<span class="tier-dot ${distressLabel[ds.tier].cls}" title="${ds.tier} · ${(ds.signals || []).join(', ')}"></span>` : ""; })()}${gradeBadge(g)}</td>
      <td>${dateCell}</td>
      <td>${l.state || ""}</td>
      <td>${l.county || ""}</td>
      <td>${addrCell}</td>
      <td>${l.city || ""}</td>
      <td>${fmtType(l.listing_type)}</td>
      <td class="num">${fmtMoney(l.opening_bid)}</td>
      <td class="num">${fmtMoney(c.arv_expected)}</td>
      <td class="num">${fmtMoney(c.rehab_expected)}</td>
      <td class="num">${fmtMoney(c.max_bid_70)}</td>
      <td class="num">${roiCell(c.roi_pct)}</td>
      <td class="num">${fmtNum(l.bedrooms)}</td>
      <td class="num">${fmtNum(l.bathrooms)}</td>
      <td class="num">${l.living_sqft ? Math.round(l.living_sqft).toLocaleString() : ""}</td>
      <td class="num">${l.year_built || ""}</td>
      <td>${l.case_number || ""}</td>
    </tr>`;
    })
    .join("");
  tb.querySelectorAll("tr").forEach((tr) =>
    tr.addEventListener("click", () => openDetail(filtered[parseInt(tr.dataset.id)])),
  );
}

// ------------- Cards render --------------------------------------------------
function renderCards() {
  const grid = $("cards-grid");
  grid.innerHTML = filtered
    .slice(0, 200)
    .map((l, i) => {
      const g = getGrade(l);
      const c = getCalc(l) || {};
      const isBkSource = l.source === "national.courtlistener_bankruptcy";
      const bkXref = !isBkSource && l.raw && l.raw.bankruptcy ? l.raw.bankruptcy : null;
      const cl = isBkSource ? (l.raw && l.raw.courtlistener) || {} : null;
      // Photo: prefer Zillow photo, fall back to OSM static map at the listing's coords
      let photo;
      if (isBkSource) {
        // Bankruptcy listings have no property — use a court-themed placeholder
        photo = `<div class="card-img no-photo" style="background:linear-gradient(135deg,#1a365d,#2c5282);color:#fff;font-size:48px">🏛</div>`;
      } else if (l.raw && l.raw.zillow && l.raw.zillow.photo) {
        photo = `<div class="card-img" style="background-image:url('${l.raw.zillow.photo}')"></div>`;
      } else if (l.latitude && l.longitude) {
        const staticUrl = `https://staticmap.openstreetmap.de/staticmap.php?center=${l.latitude},${l.longitude}&zoom=17&size=400x250&markers=${l.latitude},${l.longitude},red-pushpin`;
        photo = `<div class="card-img" style="background-image:url('${staticUrl}')"></div>`;
      } else {
        photo = `<div class="card-img no-photo">🏠</div>`;
      }
      const meta = [];
      if (l.bedrooms) meta.push(`${l.bedrooms} bd`);
      if (l.bathrooms) meta.push(`${l.bathrooms} ba`);
      if (l.living_sqft) meta.push(`${Math.round(l.living_sqft).toLocaleString()} sqft`);
      if (l.year_built) meta.push(`${l.year_built}`);
      if (l.acreage) meta.push(`${l.acreage} ac`);
      const roi = c.roi_pct;
      const roiCls = roi == null ? "" : roi > 0 ? "roi-pos" : "roi-neg";
      // ARV proxy caveat: when the ARV is LOW-confidence (no real comps / no sqft)
      // mirror the detail panel — append " (proxy)" to the ARV chip and dim the ROI
      // chip so a guessed ARV never reads as a verified value.
      const dqf = (l.raw && l.raw.data_quality && Array.isArray(l.raw.data_quality.flags))
        ? l.raw.data_quality.flags : [];
      const lowArv = c.arv_confidence === "LOW"
        || dqf.includes("low_arv_confidence") || dqf.includes("no_sqft");
      // Bankruptcy listings: show debtor + chapter as the "address"
      const cardAddr = isBkSource
        ? `🏛 ${cl && cl.chapter && cl.chapter !== "?" ? `Ch.${cl.chapter}` : "Bankruptcy"} · ${(l.defendant || "filing").slice(0, 50)}`
        : `${bkXref ? "🏛 " : ""}${l.street_address || "(address pending)"}`;
      const cardLoc = isBkSource
        ? `${cl && cl.court ? cl.court.toUpperCase() : ""} · ${l.state || ""} · Filed ${cl && cl.date_filed || "?"}`
        : `${l.city || ""}${l.city ? ", " : ""}${l.county || "?"} County, ${l.state || ""}`;
      const ds = getDistress(l);
      // High-value signal chips the cards used to hide. Rendered on EVERY card
      // (independent of distress tier) so a COLD lead still surfaces equity,
      // absentee status, and a senior-lien-survives bidding trap.
      const signalChips = [];
      // (1) Equity — mirror the detail panel's value/pct + underwater colouring.
      const eq = (l.raw && l.raw.equity) || null;
      if (eq && eq.value != null) {
        const eqColor = eq.is_underwater ? "var(--danger)" : "var(--success)";
        const eqPct = eq.pct != null ? ` (${Math.round(eq.pct * 100)}%)` : "";
        const eqLabel = eq.is_underwater
          ? `Underwater ${fmtMoney(eq.value)}${eqPct}`
          : `Equity ${fmtMoney(eq.value)}${eqPct}`;
        signalChips.push(`<span class="distress-chip" style="color:${eqColor};border-color:${eqColor}">${eqLabel}</span>`);
      }
      // (2) Absentee / out-of-state — standalone signals, shown on COLD cards too.
      //     distressChips() suppresses these for COLD tier, so emit from here using
      //     the owner_mailing flags (the authoritative absentee source).
      const om = (l.raw && l.raw.owner_mailing) || {};
      if (om.absentee) signalChips.push(`<span class="distress-chip absentee">absentee</span>`);
      if (om.out_of_state) signalChips.push(`<span class="distress-chip absentee">out-of-state</span>`);
      // (4) Title-risk trap — senior lien may survive a junior foreclosure.
      const tr = (l.raw && l.raw.title_risk) || null;
      if (tr && tr.surviving_senior_debt_risk === true) {
        signalChips.push(`<span class="distress-chip" style="color:#fff;background:var(--danger);border-color:var(--danger)" title="Junior-lien foreclosure: a senior lien likely survives the sale. Bidding trap.">⚠ senior lien may survive</span>`);
      }
      const signalChipsHtml = signalChips.length
        ? `<div class="distress-chips">${signalChips.join("")}</div>` : "";
      return `
      <div class="card" data-id="${i}">
        ${g ? `<div class="card-grade-corner">${gradeBadge(g)}</div>` : ""}
        ${ds && distressLabel[ds.tier] ? `<div class="card-distress-corner">${distressBadge(ds)}</div>` : ""}
        ${photo}
        <div class="card-body">
          <div class="card-addr">${cardAddr}</div>
          <div class="card-loc">${cardLoc}</div>
          ${distressChips(ds)}
          ${signalChipsHtml}
          <div class="card-meta">
            ${fmtType(l.listing_type)}
            ${l.opening_bid ? `<span>Bid ${fmtMoney(l.opening_bid)}</span>` : ""}
            ${c.arv_expected ? `<span>ARV ${fmtMoney(c.arv_expected)}${lowArv ? " (proxy)" : ""}</span>` : ""}
            ${(l.raw && l.raw.last_sale && l.raw.last_sale.date) ? `<span title="${l.raw.last_sale.basis === "assessor_value" ? "county assessor market value as of the sale date (sale price not published)" : "last recorded sale"}">Sold ${l.raw.last_sale.date.slice(0, 7)}${l.raw.last_sale.amount ? " · " + fmtMoney(l.raw.last_sale.amount) + (l.raw.last_sale.basis === "assessor_value" ? "*" : "") : ""}</span>` : ""}
            ${l.sale_date ? `<span>${fmtDate(l.sale_date)}</span>` : ""}
            ${meta.length ? `<span>${meta.join(" · ")}</span>` : ""}
          </div>
          ${(l.raw && l.raw.also_seen_in && l.raw.also_seen_in.length) ? `<div class="card-sources" style="font-size:11px;opacity:.7;margin-top:2px">also at: ${l.raw.also_seen_in.map((s) => `<a href="${s.url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${(s.source || "source").split(".").pop()}</a>`).join(", ")}</div>` : ""}
          ${roi != null ? `<div class="card-roi ${roiCls}"${lowArv ? ` style="opacity:.45" title="ROI suppressed — derived from a low-confidence (proxy) ARV"` : ""}>ROI ${roi.toFixed(1)}%${c.cash_on_cash_pct != null ? ` · CoC ${c.cash_on_cash_pct.toFixed(0)}%` : ""}</div>` : ""}
        </div>
      </div>`;
    })
    .join("");
  grid.querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => openDetail(filtered[parseInt(c.dataset.id)])),
  );
}

// ------------- Map ------------------------------------------------------------
function initMap() {
  if (!map) {
    map = L.map("map").setView([35.0, -82.0], 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 19,
    }).addTo(map);
  } else {
    map.invalidateSize();
  }
  if (mapMarkers) map.removeLayer(mapMarkers);
  mapMarkers = L.layerGroup();
  filtered.forEach((l) => {
    if (!l.latitude || !l.longitude) return;
    const g = getGrade(l) || {};
    const c = getCalc(l) || {};
    const color = g.overall === "A" ? "#1a7f37" : g.overall === "B" ? "#5b8d3a" : g.overall === "C" ? "#b8860b" : g.overall === "D" ? "#b8540c" : "#b22a2a";
    const m = L.circleMarker([l.latitude, l.longitude], {
      radius: 8,
      color: color,
      fillColor: color,
      fillOpacity: 0.7,
      weight: 2,
    });
    m.bindTooltip(
      `<strong>${g.overall || "—"}</strong> · ${l.street_address || ""}<br>` +
      `Bid: ${fmtMoney(l.opening_bid) || "(no bid)"}<br>` +
      `${c.roi_pct != null ? `ROI: ${c.roi_pct.toFixed(1)}%` : ""}`,
    );
    m.on("click", () => openDetail(l));
    mapMarkers.addLayer(m);
  });
  mapMarkers.addTo(map);
}

// ------------- Detail panel ---------------------------------------------------
function openDetail(l) {
  if (!l) return;
  const g = getGrade(l);
  const c = getCalc(l);

  $("d-title").textContent = `${l.listing_type ? l.listing_type.replace(/_/g, " ") : "Listing"} — ${l.county || ""} County`;
  $("d-address").textContent = [l.street_address, l.city, l.state, l.zip_code].filter(Boolean).join(", ");

  // Grade block
  if (g && g.overall) {
    $("d-grade-block").innerHTML = `
      <div class="grade-circle ${g.overall}">${g.overall}</div>
      <div class="grade-sub">
        <div class="grade-sub-item"><span class="gs-letter">${g.financial}</span><span class="gs-label">Fin</span></div>
        <div class="grade-sub-item"><span class="gs-letter">${g.property}</span><span class="gs-label">Prop</span></div>
        <div class="grade-sub-item"><span class="gs-letter">${g.location}</span><span class="gs-label">Loc</span></div>
        <div class="grade-sub-item"><span class="gs-letter">${g.risk}</span><span class="gs-label">Risk</span></div>
      </div>`;
    $("d-grade-section").style.display = "block";
    $("d-grade-rationale").innerHTML = (g.rationale || []).map((r, i) => {
      const labels = ["Financial", "Property", "Location", "Risk"];
      return `<div class="rationale-row"><span class="icon">•</span><span><strong>${labels[i] || "Note"}:</strong> ${r}</span></div>`;
    }).join("");
  } else {
    $("d-grade-block").innerHTML = "";
    $("d-grade-section").style.display = "none";
  }

  // Investor calculator
  if (c) {
    const rows = [];
    if (c.arv_expected) {
      rows.push(`
        <div class="calc-row">
          <div class="lbl">Est. ARV</div>
          <div>
            <div class="val big">${fmtMoney(c.arv_expected)}</div>
            <div class="calc-range">range: <b>${fmtMoney(c.arv_low)}</b> – <b>${fmtMoney(c.arv_high)}</b></div>
          </div>
        </div>`);
    }
    if (c.rehab_expected != null) {
      rows.push(`
        <div class="calc-row">
          <div class="lbl">Est. Rehab</div>
          <div>
            <div class="val">${fmtMoney(c.rehab_expected)}</div>
            <div class="calc-range">tier: <b>${c.rehab_tier || "—"}</b> · range: <b>${fmtMoney(c.rehab_low)}</b> – <b>${fmtMoney(c.rehab_high)}</b></div>
          </div>
        </div>`);
    }
    if (l.opening_bid) {
      rows.push(`<div class="calc-row"><div class="lbl">Opening Bid</div><div class="val big">${fmtMoney(l.opening_bid)}</div></div>`);
    }
    if (c.max_bid_70 != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Max Bid (70% rule)</div><div class="val big">${fmtMoney(c.max_bid_70)}</div></div>`);
    }
    if (c.wholesale_mao != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Wholesale MAO</div><div class="val">${fmtMoney(c.wholesale_mao)}${c.wholesale_spread != null ? ` <span class="muted">(spread ${fmtMoney(c.wholesale_spread)})</span>` : ""}</div></div>`);
    }
    if (c.bid_to_arv_pct != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Bid / ARV</div><div class="val">${c.bid_to_arv_pct.toFixed(1)}%</div></div>`);
    }
    if (c.total_investment != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Total Investment</div><div class="val">${fmtMoney(c.total_investment)}</div></div>`);
    }
    if (c.estimated_profit != null) {
      const cls = c.estimated_profit > 0 ? "pos" : "neg";
      rows.push(`<div class="calc-row"><div class="lbl">Est. Profit</div><div class="val big ${cls}">${fmtMoney(c.estimated_profit)}</div></div>`);
    }
    if (c.roi_pct != null) {
      const cls = c.roi_pct > 0 ? "pos" : "neg";
      rows.push(`<div class="calc-row"><div class="lbl">ROI</div><div class="val big ${cls}">${c.roi_pct.toFixed(1)}%</div></div>`);
    }
    if (c.cash_on_cash_pct != null) {
      const cls = c.cash_on_cash_pct > 0 ? "pos" : "neg";
      rows.push(`<div class="calc-row"><div class="lbl">Cash-on-Cash</div><div class="val ${cls}">${c.cash_on_cash_pct.toFixed(1)}%</div></div>`);
    }
    const _eq = (l.raw && l.raw.equity) || null;
    if (_eq && _eq.value != null) {
      const ec = _eq.is_underwater ? "neg" : ((_eq.pct || 0) >= 0.4 ? "pos" : "");
      rows.push(`<div class="calc-row"><div class="lbl">Owner Equity</div><div class="val big ${ec}">${fmtMoney(_eq.value)} <span class="muted">(${Math.round((_eq.pct || 0) * 100)}%)</span></div></div>`);
      rows.push(`<div class="calc-row"><div class="lbl">Est. Payoff</div><div class="val">${fmtMoney(_eq.payoff_estimate)} <span class="muted">${String(_eq.payoff_source || "").replace(/_/g, " ")} · ${_eq.confidence || ""}</span></div></div>`);
      if (_eq.senior_liens) rows.push(`<div class="calc-row"><div class="lbl">Senior Liens</div><div class="val neg">${fmtMoney(_eq.senior_liens)}</div></div>`);
    }
    const _mv = (l.raw && l.raw.market_velocity) || null;
    if (_mv && _mv.moi != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Market (months of inventory)</div><div class="val">${_mv.moi} mo → ${_mv.holding_months_est}-mo hold</div></div>`);
    }
    rows.push(`<div class="calc-row"><div class="lbl">Confidence</div><div class="val"><span class="confidence-pill confidence-${c.confidence || "LOW"}">${c.confidence || "LOW"}</span></div></div>`);
    if (c.notes && c.notes.length) {
      rows.push(`<div class="calc-notes">${c.notes.map((n) => "• " + n).join("<br>")}</div>`);
    }
    $("d-calc").innerHTML = rows.join("");
  } else {
    $("d-calc").innerHTML = "<em>Calculator data not available — listing missing key fields.</em>";
  }

  // Property details
  const fields = [
    ["Sale Date", fmtDate(l.sale_date)],
    ["Sale Time", l.sale_time || ""],
    ["Sale Location", l.sale_location || ""],
    ["Tax Value", fmtMoney(l.tax_value)],
    ["Parcel ID", l.parcel_id || ""],
    ["Year Built", l.year_built || ""],
    ["Beds", l.bedrooms || ""],
    ["Baths", l.bathrooms || ""],
    ["Living SqFt", l.living_sqft ? Math.round(l.living_sqft).toLocaleString() : ""],
    ["Acreage", l.acreage || ""],
    ["Zoning", l.zoning || ""],
    ["Property Kind", l.property_kind || ""],
    ["Auction Status", l.auction_status || ""],
  ].filter(([_, v]) => v);
  $("d-grid").innerHTML = fields.map(([k, v]) => `<div class="lbl">${k}</div><div class="val">${v}</div>`).join("");

  // Photos
  const photos = (l.raw && l.raw.zillow && l.raw.zillow.photos) || [];
  $("d-photos").innerHTML = photos.length ? photos.slice(0, 6).map((p) => `<img src="${p}" loading="lazy">`).join("") : "";

  // ----- Vision condition report -----
  const vision = (l.raw && l.raw.vision) || null;
  if (vision && (vision.condition_tier || vision.vision_summary)) {
    $("d-vision-section").style.display = "block";
    const obs = vision.observations || {};
    const reds = (vision.red_flags || []).filter(Boolean);
    const goods = (vision.positive_signs || []).filter(Boolean);
    const condSrc = (l.raw && l.raw.condition_source) || "";
    const psfRange = (vision.rehab_psf_low && vision.rehab_psf_high)
      ? `Vision rehab estimate: <strong>$${vision.rehab_psf_low}-$${vision.rehab_psf_high}/sqft</strong>` : "";

    const obsRows = Object.entries(obs).filter(([_, v]) => v && String(v).trim()).map(([k, v]) =>
      `<div class="vision-row"><strong>${k.replace(/_/g, ' ')}:</strong> ${v}</div>`
    ).join("");

    $("d-vision").innerHTML = `
      <div class="vision-summary"><strong>${vision.vision_summary || ""}</strong></div>
      ${condSrc ? `<div class="vision-meta">Source: ${condSrc} (${vision.confidence || "—"} confidence)</div>` : ""}
      ${psfRange ? `<div class="vision-meta">${psfRange}</div>` : ""}
      ${reds.length ? `<div class="vision-flags red">⚠ ${reds.map(r => `<span>${r}</span>`).join(" · ")}</div>` : ""}
      ${goods.length ? `<div class="vision-flags green">✓ ${goods.map(g => `<span>${g}</span>`).join(" · ")}</div>` : ""}
      ${obsRows ? `<div class="vision-obs">${obsRows}</div>` : ""}
    `;
  } else {
    $("d-vision-section").style.display = "none";
  }

  // Mini map
  if (l.latitude && l.longitude) {
    setTimeout(() => {
      if (detailMap) detailMap.remove();
      detailMap = L.map("d-map").setView([l.latitude, l.longitude], 15);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(detailMap);
      L.marker([l.latitude, l.longitude]).addTo(detailMap);
    }, 50);
    $("d-map").style.display = "block";
  } else {
    $("d-map").style.display = "none";
  }

  // Honest source link: a real per-record page is clickable as-is; a search-only portal or a
  // synthetic placeholder is shown as "Search <portal>" so it never reads as a direct record.
  const _lk = (l.raw && l.raw.link_kind) || "record";
  if (_lk === "search") {
    const _su = (l.raw && l.raw.search_url) || l.source_url || "#";
    $("d-source-url").href = _su;
    $("d-source-url").textContent = "🔍 Search " + _su.replace(/^https?:\/\//, "").split("/")[0]
      + " for this name (no direct record link)";
  } else {
    $("d-source-url").href = l.source_url || "#";
    $("d-source-url").textContent = l.source_url || "(no link)";
  }
  // Court geo-snap that was stripped -> mark the property as unverified, not a vetted lead.
  // Idempotent: renderDetail re-runs on every open, so drop any prior badge first.
  const _prev = $("d-source-url").nextElementSibling;
  if (_prev && _prev.classList && _prev.classList.contains("unverified-badge")) _prev.remove();
  if (l.raw && l.raw.owner_mismatch) {
    $("d-source-url").insertAdjacentHTML("afterend",
      '<div class="unverified-badge" style="color:#c0392b;font-size:12px;margin-top:3px">&#9888; '
      + 'name-only court record &mdash; no verified property (a wrong geo-match was removed)</div>');
  }

  // Sold Comps (HomeHarvest comp finder)
  const comps = (l.raw && l.raw.comps) || [];
  if (comps.length) {
    $("d-comps-section").style.display = "block";
    const compHeader = (l.raw && l.raw.comp_median_ppsf)
      ? `<div class="comp-summary">Median: <strong>$${Number(l.raw.comp_median_ppsf).toFixed(0)}/sqft</strong></div>`
      : "";
    $("d-comps").innerHTML = compHeader + `
      <table class="comps-table">
        <thead><tr><th>Address</th><th>Sold</th><th>Date</th><th>SqFt</th><th>Bd/Ba</th><th>$/SqFt</th></tr></thead>
        <tbody>
        ${comps.map(c => `
          <tr>
            <td>${c.url ? `<a href="${c.url}" target="_blank">${c.address || "—"}</a>` : (c.address || "—")}</td>
            <td>${c.sold_price ? `$${Number(c.sold_price).toLocaleString()}` : "—"}</td>
            <td>${c.sold_date ? c.sold_date.slice(0,10) : "—"}</td>
            <td>${c.sqft ? Number(c.sqft).toLocaleString() : "—"}</td>
            <td>${c.beds ?? "—"}/${c.baths ?? "—"}</td>
            <td>${c.price_per_sqft ? `$${Number(c.price_per_sqft).toFixed(0)}` : "—"}</td>
          </tr>
        `).join("")}
        </tbody>
      </table>`;
  } else {
    $("d-comps-section").style.display = "none";
  }

  // Foreclosure-sold comps — recently-finished foreclosure sales in
  // the same county, like-for-like by property kind / beds / sqft.
  // Internal max-bid signal; rendered as nested data on the popout
  // (these are NEVER shown as their own listings on the main grid).
  const fcComps = (l.raw && l.raw.foreclosure_sold_comps) || [];
  const fcSummary = (l.raw && l.raw.foreclosure_sold_comp_summary) || null;
  if (fcComps.length) {
    $("d-fc-comps-section").style.display = "block";
    const summaryParts = [];
    if (fcSummary) {
      if (fcSummary.median_sold_price) {
        summaryParts.push(`Median sold: <strong>$${Number(fcSummary.median_sold_price).toLocaleString()}</strong>`);
      }
      if (fcSummary.median_price_per_sqft) {
        summaryParts.push(`<strong>$${Number(fcSummary.median_price_per_sqft).toFixed(0)}/sqft</strong>`);
      }
      if (fcSummary.range_low && fcSummary.range_high) {
        summaryParts.push(`Range: $${Number(fcSummary.range_low).toLocaleString()}–$${Number(fcSummary.range_high).toLocaleString()}`);
      }
      summaryParts.push(`<span class="muted">${fcComps.length} comp${fcComps.length === 1 ? '' : 's'} from past ${fcSummary.lookback_days}d in ${fcSummary.county}</span>`);
    }
    const header = summaryParts.length
      ? `<div class="comp-summary">${summaryParts.join(' · ')}</div>`
      : "";
    $("d-fc-comps").innerHTML = header + `
      <table class="comps-table">
        <thead><tr><th>Address</th><th>Sold</th><th>Date</th><th>SqFt</th><th>Bd/Ba</th><th>Condition</th><th>Photo</th></tr></thead>
        <tbody>
        ${fcComps.map(c => `
          <tr>
            <td>${c.source_url ? `<a href="${c.source_url}" target="_blank" rel="noopener">${c.address || "—"}</a>` : (c.address || "—")}</td>
            <td>${c.sold_price ? `$${Number(c.sold_price).toLocaleString()}${c.actual_sold_price_known ? '' : '*'}` : "—"}</td>
            <td>${c.sold_date ? c.sold_date.slice(0,10) : "—"}</td>
            <td>${c.living_sqft ? Number(c.living_sqft).toLocaleString() : "—"}</td>
            <td>${c.beds ?? "—"}/${c.baths ?? "—"}</td>
            <td>${c.condition_tier ? `${c.condition_tier}${c.vision_confidence ? ' (' + c.vision_confidence + ')' : ''}` : "—"}</td>
            <td>${c.primary_photo_url ? `<a href="${c.primary_photo_url}" target="_blank" rel="noopener">📷${c.photo_count > 1 ? ' ×' + c.photo_count : ''}</a>` : "—"}</td>
          </tr>
        `).join("")}
        </tbody>
      </table>
      <div class="muted" style="font-size:0.85em;margin-top:0.5em">
        * = opening bid / judgment amount used (actual hammer price not surfaced by source).
        Comps matched by county + property kind + beds±1 + sqft±40% within last ${fcSummary?.lookback_days || 180}d.
      </div>`;
  } else {
    $("d-fc-comps-section").style.display = "none";
  }

  // Rent Comps
  const rents = (l.raw && l.raw.rent_comps) || [];
  if (rents.length) {
    $("d-rent-section").style.display = "block";
    const est = l.raw && l.raw.estimated_monthly_rent;
    const header = est
      ? `<div class="comp-summary">Estimated rent: <strong>$${Number(est).toLocaleString()}/mo</strong></div>`
      : "";
    $("d-rent").innerHTML = header + `
      <table class="comps-table">
        <thead><tr><th>Address</th><th>Rent</th><th>SqFt</th><th>Bd/Ba</th><th>$/SqFt</th></tr></thead>
        <tbody>
        ${rents.map(r => `
          <tr>
            <td>${r.url ? `<a href="${r.url}" target="_blank">${r.address || "—"}</a>` : (r.address || "—")}</td>
            <td>${r.rent_per_month ? `$${Number(r.rent_per_month).toLocaleString()}` : "—"}</td>
            <td>${r.sqft ? Number(r.sqft).toLocaleString() : "—"}</td>
            <td>${r.beds ?? "—"}/${r.baths ?? "—"}</td>
            <td>${r.rent_per_sqft ? `$${Number(r.rent_per_sqft).toFixed(2)}` : "—"}</td>
          </tr>
        `).join("")}
        </tbody>
      </table>`;
  } else {
    $("d-rent-section").style.display = "none";
  }

  // Court
  const raw = l.raw || {};
  const fmtUsd = (n) => "$" + Math.round(n).toLocaleString();
  const court = [
    ["Case Number", l.case_number],
    ["Plaintiff", l.plaintiff],
    ["Defendant", l.defendant],
    ["Trustee", l.trustee],
    ["Judgment", l.judgment_amount ? fmtUsd(l.judgment_amount) : null],
    ["Balance due", raw.court_balance_due
      ? `${fmtUsd(raw.court_balance_due)}${raw.court_balance_due_as_of ? " (as of " + raw.court_balance_due_as_of + ")" : ""}`
      : null],
    ["Sale status", raw.court_sale_status
      ? raw.court_sale_status.replace(/_/g, " ") + (raw.sold_confirmed ? " — SOLD" : "")
      : null],
  ].filter(([_, v]) => v);
  const docs = raw.court_documents || [];
  if (court.length || docs.length) {
    $("d-court-section").style.display = "block";
    let html = court.map(([k, v]) => `<div><strong>${k}:</strong> ${v}</div>`).join("");
    if (docs.length) {
      html += `<div style="margin-top:8px"><strong>Court documents:</strong><ul style="margin:4px 0 0;padding-left:18px">` +
        docs.map((d) => `<li>${d.type}${d.date ? " — " + d.date : ""}</li>`).join("") + `</ul></div>`;
    }
    if (raw.court_record_url) {
      html += `<div style="margin-top:6px"><a href="${raw.court_record_url}" target="_blank" rel="noopener">Open court record →</a></div>`;
    }
    $("d-court").innerHTML = html;
  } else {
    $("d-court-section").style.display = "none";
  }

  // GIS
  const gis = (l.raw && l.raw.gis) || null;
  if (gis) {
    $("d-gis-section").style.display = "block";
    const rows = [];
    if (gis.owner) rows.push(`<div><strong>Owner:</strong> ${gis.owner}</div>`);
    if (gis.mailing) rows.push(`<div><strong>Mailing:</strong> ${gis.mailing}</div>`);
    if (gis.last_sale) {
      const ls = gis.last_sale;
      const parts = [];
      if (ls.date) parts.push(ls.date);
      if (ls.amount) parts.push(fmtMoney(ls.amount));
      if (ls.book && ls.page) parts.push(`Book ${ls.book}/Page ${ls.page}`);
      if (parts.length) rows.push(`<div><strong>Last sale:</strong> ${parts.join(" · ")}</div>`);
    }
    $("d-gis").innerHTML = rows.join("");
  } else {
    $("d-gis-section").style.display = "none";
  }

  // Location (Census)
  const loc = (l.raw && l.raw.location) || null;
  if (loc && (loc.median_household_income || loc.median_home_value)) {
    $("d-location-section").style.display = "block";
    const rows = [];
    if (loc.median_household_income) rows.push(`<div><strong>Median HH Income:</strong> ${fmtMoney(loc.median_household_income)}</div>`);
    if (loc.median_home_value) rows.push(`<div><strong>Median Home Value (ZIP):</strong> ${fmtMoney(loc.median_home_value)}</div>`);
    if (loc.owner_occupied_pct != null) rows.push(`<div><strong>Owner-occupied:</strong> ${loc.owner_occupied_pct.toFixed(1)}%</div>`);
    if (loc.unemployment_pct != null) rows.push(`<div><strong>Unemployment:</strong> ${loc.unemployment_pct.toFixed(1)}%</div>`);
    $("d-location").innerHTML = rows.join("");
  } else {
    $("d-location-section").style.display = "none";
  }

  // ----- Quick badges (TOP of detail panel, no scroll) -----
  // Condition tier + flags + flood + critical signals all visible immediately
  const flags = (l.raw && l.raw.flags) || [];
  const condTier = (l.raw && l.raw.condition_tier) || null;
  const flood = (l.raw && l.raw.flood) || {};
  const calc = (l.raw && l.raw.calc) || {};
  const grade = (l.raw && l.raw.grade) || {};

  const condLabel = {
    "move_in_ready": { label: "Move-in ready", cls: "pos" },
    "cosmetic":      { label: "Cosmetic work", cls: "warn-light" },
    "major":         { label: "Major rehab",   cls: "warn" },
    "gut":           { label: "Gut / tear-down", cls: "neg" },
  };

  const badges = [];

  // Deal status FIRST — actionable investor verdict
  const dealStatusMap = {
    "GREAT":     { label: "GREAT deal", cls: "pos" },
    "OK":        { label: "OK at list",  cls: "warn-light" },
    "NEGOTIATE": { label: "NEGOTIATE",   cls: "warn" },
    "PASS":      { label: "PASS",        cls: "neg" },
  };
  if (calc.deal_status && dealStatusMap[calc.deal_status]) {
    const s = dealStatusMap[calc.deal_status];
    badges.push(`<span class="qbadge ${s.cls}" title="${calc.deal_message || ''}">${s.label}</span>`);
  }
  if (calc.haircut_needed && calc.haircut_needed > 0) {
    badges.push(`<span class="qbadge warn">Haircut needed: $${Number(calc.haircut_needed).toLocaleString()}</span>`);
  }

  // Condition tier — most-important property signal
  if (condTier && condLabel[condTier]) {
    const c = condLabel[condTier];
    badges.push(`<span class="qbadge ${c.cls}">${c.label}</span>`);
  }

  // 2026-06-19 HONESTY: surface data-quality caveats the pipeline computes but
  // the UI used to hide — so a placeholder address / proxy ARV never looks like
  // a verified value. Driven by raw.data_quality.flags.
  const dq = (l.raw && l.raw.data_quality) || {};
  const dqf = Array.isArray(dq.flags) ? dq.flags : [];
  if (dqf.includes("synthetic_address")) {
    badges.push(`<span class="qbadge neg" title="${dq.summary || 'Placeholder address (case #/parcel ID), not a verified situs'}">⚠ placeholder address</span>`);
  } else if (dqf.includes("approximate_address")) {
    badges.push(`<span class="qbadge warn" title="${dq.summary || 'Approximate address'}">📍 approx address</span>`);
  }

  // ARV / max bid / ROI summary chips
  if (calc.arv_expected) {
    const lowArv = calc.arv_confidence === "LOW" || dqf.includes("low_arv_confidence") || dqf.includes("no_sqft");
    badges.push(`<span class="qbadge info" title="${(calc.notes && calc.notes[0]) || ''}">ARV ~$${Number(calc.arv_expected).toLocaleString()}${lowArv ? " (proxy)" : ""}</span>`);
  }
  if (calc.max_bid_70) {
    badges.push(`<span class="qbadge info">Max bid (70%) $${Number(calc.max_bid_70).toLocaleString()}</span>`);
  }
  if (calc.roi_pct != null) {
    const cls = calc.roi_pct > 25 ? "pos" : calc.roi_pct > 10 ? "warn-light" : "neg";
    badges.push(`<span class="qbadge ${cls}">ROI ${calc.roi_pct.toFixed(0)}%</span>`);
  }

  // Flood
  if (flood.in_sfha) {
    badges.push(`<span class="qbadge neg">⚠ Flood zone ${flood.zone || "AE"}</span>`);
  }

  // NC Upset bid window — sale already happened in last 10 days but no
  // confirmation yet. Anyone can submit a 5%+ upset bid until window closes.
  // Computed: NC + sale_date in last 10 days.
  if (l.state === "NC" && l.sale_date) {
    const sd = Date.parse(l.sale_date);
    const now = Date.now();
    const tenDaysAgo = now - 10 * 86400000;
    if (!isNaN(sd) && sd > tenDaysAgo && sd <= now) {
      const daysLeft = Math.max(0, 10 - Math.floor((now - sd) / 86400000));
      badges.push(`<span class="qbadge warn" title="NC 10-day upset bid window. Anyone can submit a 5%+ higher bid at the courthouse until the deadline.">⏱ Upset bid period (${daysLeft}d left)</span>`);
    }
  }

  // Bankruptcy cross-reference — HIGH-PRIORITY signal: defendant on this
  // foreclosure also has a recent NC/SC bankruptcy filing. Ch.13 = trying to
  // stop the sale via automatic stay. Ch.7 = liquidation, property gets sold.
  const bk = (l.raw && l.raw.bankruptcy) || null;
  if (bk) {
    const ch = bk.chapter && bk.chapter !== "?" ? `Ch.${bk.chapter} ` : "";
    const dt = bk.date_filed ? ` ${bk.date_filed}` : "";
    const cls = bk.chapter === "13" ? "neg" : bk.chapter === "7" ? "warn" : "warn-light";
    const tip = `${(bk.case_name || '').replace(/"/g, '')} | ${(bk.docket_number || '').replace(/"/g, '')} | ${(bk.court || '').toUpperCase()}`;
    badges.push(`<span class="qbadge ${cls}" title="${tip}">🏛 ${ch}BANKRUPTCY${dt}</span>`);
  }

  // Bankruptcy source listing (discovery — debtor name only, no address)
  if (l.source === "national.courtlistener_bankruptcy") {
    const cl = (l.raw && l.raw.courtlistener) || {};
    const ch = cl.chapter && cl.chapter !== "?" ? `Ch.${cl.chapter} ` : "";
    const cls = cl.chapter === "13" ? "neg" : cl.chapter === "7" ? "warn" : "warn-light";
    badges.push(`<span class="qbadge ${cls}">🏛 ${ch}Bankruptcy filing</span>`);
  }

  // Property flags as colored chips
  flags.forEach((f) => {
    const cls =
      /vacant|fire|tear|condemned|hoarder|gutted|foundation|structural|negative_equity/.test(f) ? "neg" :
      /renovated|updated|move-in|turnkey|new |high_equity/.test(f) ? "pos" : "warn-light";
    badges.push(`<span class="qbadge ${cls}">${f.replace(/_/g, " ")}</span>`);
  });

  $("d-quick-badges").innerHTML = badges.join("");

  // Keep the bottom flags section in sync (legacy — for users who scroll)
  if (flags.length) {
    $("d-flags-section").style.display = "block";
    $("d-flags").innerHTML = flags
      .map((f) => {
        const cls =
          /vacant|fire|tear|condemned|hoarder|gutted|foundation|structural|negative_equity/.test(f) ? "neg" :
          /renovated|updated|move-in|turnkey|new |high_equity/.test(f) ? "pos" : "";
        return `<span class="flag-pill ${cls}">${f.replace(/_/g, " ")}</span>`;
      })
      .join("");
  } else {
    $("d-flags-section").style.display = "none";
  }

  // -------- Extended sections: surface collected-but-previously-hidden data --
  const E = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const kv = (rows) => rows.filter((r) => r[1] != null && r[1] !== "" && r[1] !== false)
    .map(([k, v]) => `<div class="lbl">${E(k)}</div><div class="val">${E(v === true ? "Yes" : v)}</div>`).join("");
  const setSec = (sec, id, rows) => {
    const html = kv(rows);
    if (html) { $(id).innerHTML = `<div class="detail-grid">${html}</div>`; $(sec).style.display = "block"; }
    else { $(sec).style.display = "none"; }
  };
  const flat = (o) => Object.entries(o || {})
    .filter(([k, v]) => v != null && v !== "" && typeof v !== "object")
    .map(([k, v]) => [k.replace(/_/g, " "), v === true ? "Yes" : v]);

  // Owner & Contact (mailing addr + absentee + any free/paid skip-trace)
  const _om = (l.raw && l.raw.owner_mailing) || {};
  const _st = (l.raw && l.raw.skip_trace) || {};
  setSec("d-contact-section", "d-contact", [
    ["Owner", _om.owner], ["Mailing address", _om.mailing],
    ["Absentee owner", _om.absentee], ["Out of state", _om.out_of_state],
    ["Phone", _st.phone], ["Email", _st.email],
  ]);

  // Distress Stack — full breakdown (only the tier badge was shown before)
  const _ds = getDistress(l);
  if (_ds && (_ds.score != null || (_ds.signals || []).length)) {
    const sigs = (_ds.signals || []).map((s) => Array.isArray(s)
      ? `<span class="qbadge warn-light">${E(String(s[0]).replace(/_/g, " "))} +${E(s[2])}</span>` : "").join(" ");
    $("d-distress").innerHTML =
      `<div class="detail-grid">${kv([["Tier", _ds.tier], ["Score", _ds.score], ["Categories stacked", _ds.stack], ["Equity band", _ds.equity_band], ["Absentee", _ds.absentee]])}</div>` +
      (sigs ? `<div style="margin-top:8px">${sigs}</div>` : "");
    $("d-distress-section").style.display = "block";
  } else { $("d-distress-section").style.display = "none"; }

  // Risk & Environment (flood / FEMA repetitive loss / EPA / crime / code enf)
  let _risk = [];
  const _fl = (l.raw && l.raw.flood) || {};
  if (_fl.zone) _risk.push(["Flood zone", _fl.zone + (_fl.in_sfha ? " (in SFHA)" : "")]);
  if (l.raw && l.raw.fema_repetitive_loss) _risk = _risk.concat(flat(l.raw.fema_repetitive_loss));
  if (l.raw && l.raw.epa) _risk = _risk.concat(flat(l.raw.epa));
  if (l.raw && l.raw.crime) _risk = _risk.concat(flat(l.raw.crime));
  if (l.raw && l.raw.code_enforcement) _risk = _risk.concat(flat(l.raw.code_enforcement));
  setSec("d-risk-section", "d-risk", _risk);

  // Deeds, Liens & Life Events (relationship deed / CAMA / liens / permits / …)
  let _deeds = [];
  const _rs = (l.raw && l.raw.relationship_signal) || null;
  if (_rs) _deeds.push([(_rs.kind || "life event") + " signal", _rs.keyword || "Yes"]);
  if (l.raw && l.raw.cama) _deeds = _deeds.concat(flat(l.raw.cama));
  const _up = (l.raw && l.raw.upset_bid) || null;
  if (_up) _deeds.push(["Upset-bid window", (_up.in_window ? "OPEN" : "closed") + (_up.days_remaining != null ? ` (${_up.days_remaining}d left)` : "")]);
  if (l.raw && l.raw.sc_tax_delinquent) _deeds.push(["SC tax delinquent", "Yes"]);
  if (l.raw && l.raw.incarceration) _deeds.push(["Owner incarcerated (name match)", "Yes"]);
  if (l.raw && l.raw.sos_status) _deeds = _deeds.concat(flat(l.raw.sos_status));
  if (l.foreclosure_process) _deeds.push(["Foreclosure process", String(l.foreclosure_process).replace(/_/g, " ")]);
  if (l.redemption_deadline) _deeds.push(["SC redemption deadline", fmtDate(l.redemption_deadline)]);
  // Joined lien stack (state tax liens etc.) — raw['liens'], distinct from the
  // ROD lien_priority engine below.
  const _liensStack = (l.raw && l.raw.liens);
  if (Array.isArray(_liensStack) && _liensStack.length) {
    _liensStack.forEach((x) => _deeds.push([
      (x.type ? String(x.type).replace(/_/g, " ") : "lien") + (x.super_priority ? " (super-priority)" : ""),
      fmtMoney(x.amount),
    ]));
  }
  const _liens = (l.raw && l.raw.lien_priority);
  if (Array.isArray(_liens) && _liens.length) _deeds.push(["Liens on record", _liens.length]);
  const _rod = (l.raw && l.raw.rod_docs);
  if (Array.isArray(_rod) && _rod.length) _deeds.push(["ROD documents", _rod.length]);
  const _perm = (l.raw && l.raw.building_permits);
  if (Array.isArray(_perm) && _perm.length) _deeds.push(["Building permits", _perm.length]);
  else if (_perm && typeof _perm === "object") _deeds = _deeds.concat(flat(_perm));
  setSec("d-deeds-section", "d-deeds", _deeds);

  $("detail-panel").classList.remove("hidden");
}

// ------------- CSV export -----------------------------------------------------
function exportCsv() {
  const cols = [
    // Contact-forward: this export should drive mail-merge + CRM in one shot.
    "grade_overall", "distress_tier", "distress_score", "contactable",
    "owner_name", "owner_mailing", "mail_state", "absentee", "out_of_state",
    "owner_phone", "phone_source", "phone_needs_dnc",
    "rod_mortgage", "rod_adverse", "equity_band", "senior_debt_risk",
    "sale_date", "days_to_auction", "stale_case", "geo_quality",
    "state", "county", "street_address", "city", "zip_code", "listing_type",
    "opening_bid", "arv_expected", "rehab_expected", "max_bid_70", "roi_pct", "cash_on_cash_pct",
    "bedrooms", "bathrooms", "living_sqft", "year_built", "acreage", "zoning",
    "case_number", "plaintiff", "defendant", "trustee", "source", "source_url",
    // 2026-06-19: data-quality caveats so the export never presents a placeholder
    // address or proxy ARV as a verified value (the "nothing made up" rule).
    "address_quality", "arv_confidence", "data_quality_note",
    "truepeoplesearch_url",
  ];
  const rows = [cols.join(",")];
  filtered.forEach((l) => {
    const g = getGrade(l) || {};
    const c = getCalc(l) || {};
    const r = l.raw || {};
    const dq = r.data_quality || {};
    const dqf = Array.isArray(dq.flags) ? dq.flags : [];
    const om = r.owner_mailing || {};
    const op = r.owner_phone || {};
    const ds = r.distress_stack || {};
    const rod = r.rod || {};
    const dta = l.sale_date ? Math.round((new Date(l.sale_date) - new Date()) / 86400000) : "";
    const tps = l.owner_name
      ? `https://www.truepeoplesearch.com/results?name=${encodeURIComponent(l.owner_name)}&citystatezip=${encodeURIComponent(((l.city || "") + " " + (l.state || "")).trim())}`
      : "";
    const row = {
      grade_overall: g.overall, grade_financial: g.financial, grade_property: g.property,
      grade_location: g.location, grade_risk: g.risk,
      arv_expected: c.arv_expected, rehab_expected: c.rehab_expected,
      max_bid_70: c.max_bid_70, roi_pct: c.roi_pct, cash_on_cash_pct: c.cash_on_cash_pct,
      // contact + signal block
      distress_tier: ds.tier || "", distress_score: ds.score != null ? ds.score : "",
      contactable: ds.contactable ? "yes" : "",
      owner_name: l.owner_name || "", owner_mailing: om.mailing || "", mail_state: om.mail_state || "",
      absentee: om.absentee ? "yes" : "", out_of_state: om.out_of_state ? "yes" : "",
      owner_phone: op.phone || "", phone_source: op.source || "",
      phone_needs_dnc: op.needs_dnc_scrub ? "yes" : "",
      rod_mortgage: rod.has_mortgage ? "yes" : "", rod_adverse: rod.has_adverse_lien ? "yes" : "",
      equity_band: ds.equity_band || "", senior_debt_risk: ds.surviving_senior_debt_risk ? "yes" : "",
      days_to_auction: dta, stale_case: r.stale_case ? "yes" : "",
      geo_quality: r.geo_imprecise || "verified",
      truepeoplesearch_url: tps,
      address_quality: dqf.includes("synthetic_address") ? "placeholder"
                       : dqf.includes("approximate_address") ? "approximate" : "verified",
      arv_confidence: c.arv_confidence || "",
      data_quality_note: dq.summary || "",
      ...l,
    };
    rows.push(cols.map((k) => {
      let v = row[k];
      if (v == null) v = "";
      v = String(v).replace(/"/g, '""');
      return /[",\n]/.test(v) ? `"${v}"` : v;
    }).join(","));
  });
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `foreclosure-listings-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

// ------------- Boot ----------------------------------------------------------
loadData();
