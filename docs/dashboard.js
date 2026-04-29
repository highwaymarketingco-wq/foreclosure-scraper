"use strict";

let LISTINGS = [];
let META = {};
let filtered = [];
let sortKey = "sale_date";
let sortDir = "asc";
let map = null;
let mapMarkers = null;
let detailMap = null;

const $ = (id) => document.getElementById(id);

// ------------- Load data -----------------------------------------------------
async function loadData() {
  try {
    const [listingsRes, metaRes] = await Promise.all([
      fetch(`listings.json?t=${Date.now()}`),
      fetch(`run_meta.json?t=${Date.now()}`),
    ]);
    if (!listingsRes.ok) throw new Error("listings.json missing");
    LISTINGS = await listingsRes.json();
    META = metaRes.ok ? await metaRes.json() : {};
  } catch (e) {
    LISTINGS = [];
    META = {};
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<div style="background:#ffd2dc;color:#b22a2a;padding:14px 28px;text-align:center;">
       Could not load listings — first run hasn't finished yet, or network error. Reload in a few minutes.</div>`,
    );
  }
  initFilters();
  applyFilters();
  fillStats();
}

// ------------- Stats ---------------------------------------------------------
function fillStats() {
  $("stat-total").textContent = LISTINGS.length;
  $("stat-sc").textContent = LISTINGS.filter((l) => l.state === "SC").length;
  $("stat-nc").textContent = LISTINGS.filter((l) => l.state === "NC").length;
  $("stat-with-bid").textContent = LISTINGS.filter((l) => l.opening_bid).length;
  $("stat-with-photos").textContent = LISTINGS.filter((l) => l.year_built || l.bedrooms || l.living_sqft).length;
  const sources = new Set(LISTINGS.map((l) => l.source).filter(Boolean));
  $("stat-sources").textContent = sources.size;
  $("total-badge").textContent = `${LISTINGS.length} total`;
  $("active-badge").textContent = `${LISTINGS.filter((l) => l.sale_date).length} with sale dates`;
  $("last-updated").textContent = META.run_time
    ? `Updated ${new Date(META.run_time).toLocaleString()}`
    : "Updated recently";
  $("run-source-count").textContent = String(sources.size);
}

// ------------- Filter init ---------------------------------------------------
function initFilters() {
  const counties = new Set();
  LISTINGS.forEach((l) => l.county && counties.add(`${l.county}, ${l.state || "?"}`));
  const sel = $("filter-county");
  Array.from(counties)
    .sort()
    .forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      sel.appendChild(opt);
    });

  ["search", "filter-state", "filter-county", "filter-type", "filter-window"].forEach((id) =>
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

  $("export-csv").addEventListener("click", exportCsv);
  $("close-detail").addEventListener("click", () => $("detail-panel").classList.add("hidden"));
}

// ------------- Filtering + sorting ------------------------------------------
function applyFilters() {
  const q = $("search").value.toLowerCase();
  const st = $("filter-state").value;
  const co = $("filter-county").value;
  const ty = $("filter-type").value;
  const win = parseInt($("filter-window").value);
  const now = Date.now();
  const wmax = win ? now + win * 86400000 : 0;

  filtered = LISTINGS.filter((l) => {
    if (st && l.state !== st) return false;
    if (co && `${l.county || ""}, ${l.state || "?"}` !== co) return false;
    if (ty && l.listing_type !== ty) return false;
    if (win && l.sale_date) {
      const d = Date.parse(l.sale_date);
      if (isNaN(d) || d < now || d > wmax) return false;
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

  filtered.sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey];
    if (av == null) av = sortDir === "asc" ? "￿" : "";
    if (bv == null) bv = sortDir === "asc" ? "￿" : "";
    if (typeof av === "string") av = av.toLowerCase();
    if (typeof bv === "string") bv = bv.toLowerCase();
    if (av < bv) return sortDir === "asc" ? -1 : 1;
    if (av > bv) return sortDir === "asc" ? 1 : -1;
    return 0;
  });

  renderTable();
  renderCards();
  $("result-count").textContent = `${filtered.length} of ${LISTINGS.length} listings`;
}

// ------------- Table render --------------------------------------------------
function fmtMoney(v) { return v ? "$" + Math.round(v).toLocaleString() : ""; }
function fmtNum(v) { return v == null ? "" : v; }
function fmtDate(v) {
  if (!v) return "";
  const d = new Date(v);
  return isNaN(d) ? v : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
}
function fmtType(t) {
  const cls = t || "unknown";
  const label = (t || "unknown").replace(/_/g, " ");
  return `<span class="type-pill type-${cls}">${label}</span>`;
}

function renderTable() {
  const tb = $("listings-tbody");
  tb.innerHTML = filtered
    .slice(0, 600)
    .map(
      (l, i) => `
    <tr data-id="${i}">
      <td>${fmtDate(l.sale_date)}</td>
      <td>${l.state || ""}</td>
      <td>${l.county || ""}</td>
      <td>${l.street_address || ""}</td>
      <td>${l.city || ""}</td>
      <td>${fmtType(l.listing_type)}</td>
      <td class="num">${fmtMoney(l.opening_bid)}</td>
      <td class="num">${fmtMoney(l.market_value)}</td>
      <td class="num">${fmtMoney(l.tax_value)}</td>
      <td class="num">${fmtNum(l.bedrooms)}</td>
      <td class="num">${fmtNum(l.bathrooms)}</td>
      <td class="num">${l.living_sqft ? Math.round(l.living_sqft).toLocaleString() : ""}</td>
      <td class="num">${l.year_built || ""}</td>
      <td>${l.case_number || ""}</td>
      <td>${(l.source || "").replace(/^[a-z_]+\./, "")}</td>
    </tr>`,
    )
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
      const photo =
        l.raw && l.raw.zillow && l.raw.zillow.photo
          ? `<div class="card-img" style="background-image:url('${l.raw.zillow.photo}')"></div>`
          : `<div class="card-img no-photo">🏠</div>`;
      const meta = [];
      if (l.bedrooms) meta.push(`${l.bedrooms} bd`);
      if (l.bathrooms) meta.push(`${l.bathrooms} ba`);
      if (l.living_sqft) meta.push(`${Math.round(l.living_sqft).toLocaleString()} sqft`);
      if (l.year_built) meta.push(`${l.year_built}`);
      if (l.acreage) meta.push(`${l.acreage} ac`);
      return `
      <div class="card" data-id="${i}">
        ${photo}
        <div class="card-body">
          <div class="card-addr">${l.street_address || "(address pending)"}</div>
          <div class="card-loc">${l.city || ""}${l.city ? ", " : ""}${l.county || "?"} County, ${l.state || ""}</div>
          <div class="card-meta">
            ${fmtType(l.listing_type)}
            ${l.opening_bid ? `<span>${fmtMoney(l.opening_bid)}</span>` : ""}
            ${l.sale_date ? `<span>${fmtDate(l.sale_date)}</span>` : ""}
            ${meta.length ? `<span>${meta.join(" · ")}</span>` : ""}
          </div>
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
      attribution: '© OpenStreetMap',
      maxZoom: 19,
    }).addTo(map);
  } else {
    map.invalidateSize();
  }
  if (mapMarkers) map.removeLayer(mapMarkers);
  mapMarkers = L.layerGroup();
  filtered.forEach((l, i) => {
    if (!l.latitude || !l.longitude) return;
    const m = L.marker([l.latitude, l.longitude]);
    m.bindTooltip(`${l.street_address || ""}<br>${fmtMoney(l.opening_bid) || "(no bid)"}<br>${fmtDate(l.sale_date) || ""}`);
    m.on("click", () => openDetail(l));
    mapMarkers.addLayer(m);
  });
  mapMarkers.addTo(map);
}

// ------------- Detail panel ---------------------------------------------------
function openDetail(l) {
  if (!l) return;
  $("d-title").textContent = `${l.listing_type ? l.listing_type.replace(/_/g, " ") : "Listing"} — ${l.county || ""} County`;
  $("d-address").textContent = [l.street_address, l.city, l.state, l.zip_code].filter(Boolean).join(", ");

  const fields = [
    ["Sale Date", fmtDate(l.sale_date)],
    ["Sale Time", l.sale_time || ""],
    ["Sale Location", l.sale_location || ""],
    ["Opening Bid", fmtMoney(l.opening_bid)],
    ["Judgment", fmtMoney(l.judgment_amount)],
    ["Zestimate", fmtMoney(l.market_value)],
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

  // Photos (Zillow)
  const photos = (l.raw && l.raw.zillow && l.raw.zillow.photos) || [];
  $("d-photos").innerHTML = photos.length
    ? photos.slice(0, 6).map((p) => `<img src="${p}" loading="lazy">`).join("")
    : "";

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

  $("d-source-url").href = l.source_url || "#";
  $("d-source-url").textContent = l.source_url || "(no link)";

  // Flags
  const flags = (l.raw && l.raw.flags) || [];
  if (flags.length) {
    $("d-flags-section").style.display = "block";
    $("d-flags").innerHTML = flags
      .map((f) => {
        const cls =
          /vacant|fire|tear|condemned|hoarder|gutted|foundation/.test(f) ? "neg" :
          /renovated|updated|move-in|turnkey|new /.test(f) ? "pos" : "";
        return `<span class="flag-pill ${cls}">${f}</span>`;
      })
      .join("");
  } else {
    $("d-flags-section").style.display = "none";
  }

  // Court
  const court = [
    ["Case Number", l.case_number],
    ["Plaintiff", l.plaintiff],
    ["Defendant", l.defendant],
    ["Trustee", l.trustee],
  ].filter(([_, v]) => v);
  if (court.length) {
    $("d-court-section").style.display = "block";
    $("d-court").innerHTML = court.map(([k, v]) => `<div><strong>${k}:</strong> ${v}</div>`).join("");
  } else {
    $("d-court-section").style.display = "none";
  }

  // GIS / county records
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

  $("detail-panel").classList.remove("hidden");
}

// ------------- CSV export -----------------------------------------------------
function exportCsv() {
  const cols = ["sale_date","state","county","street_address","city","zip_code","listing_type","opening_bid","market_value","tax_value","bedrooms","bathrooms","living_sqft","year_built","acreage","zoning","case_number","plaintiff","defendant","trustee","source","source_url"];
  const rows = [cols.join(",")];
  filtered.forEach((l) => {
    rows.push(cols.map((c) => {
      let v = l[c];
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
