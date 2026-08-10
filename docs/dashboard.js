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

// ---------------------------------------------------------------------------
// LEAN — the one switch every mobile-only behaviour in this file hangs off.
//
// 2026-08-10: the board was killing the WebContent process on two iPhones on
// every single launch ("a problem repeatedly occurred"). Measured live: one
// page load cost 521 MB of JS heap (23 MB gz -> a 258.9 MB UTF-16 string -> a
// further ~241 MB object graph, all three alive at once). Desktop Chrome's
// ceiling here is 2,144 MB so it survives; an iPhone tab gets a few hundred MB.
//
// Everything guarded by LEAN is therefore a *memory* decision, not a styling
// one. Desktop keeps every marker, every tooltip, all 800 rows and the full
// record — if a change is visible at 1440px, it is a bug.
//
// Latched ONCE at boot, deliberately: re-evaluating a media query would flip
// the profile on a rotation, halfway through a session, with a half-projected
// board already in memory. `?lean=1` / `?lean=0` force it for debugging.
//
// The second clause exists because iOS Safari's per-site "Request Desktop
// Website" reports a ~980px viewport and persists into a home-screen webclip —
// the width test alone would hand the FULL path back to the exact phone this
// is meant to save. It requires a coarse pointer AND a physically small screen,
// so a touchscreen laptop (min screen dimension >= 1024) can never trip it.
const _QS = (() => { try { return new URLSearchParams(location.search); } catch (e) { return new URLSearchParams(""); } })();
const LEAN = (() => {
  const forced = _QS.get("lean");
  if (forced === "1") return true;
  if (forced === "0") return false;
  // 720px, matching the CSS breakpoint exactly. It was 820, which opened a
  // 721-820px band where a half-width desktop window got DESKTOP css with the
  // MOBILE data profile: a full 17-column table capped at 50 rows, no mobile
  // sort control (it is display:none above 720), and a detail panel telling a
  // desktop user to open it on a desktop. The two thresholds must not diverge.
  const narrow = typeof matchMedia === "function" && matchMedia("(max-width:720px)").matches;
  const handheld = (navigator.maxTouchPoints || 0) > 0 && typeof screen === "object" && screen
    && Math.min(screen.width || 9999, screen.height || 9999) < 820;
  return narrow || handheld;
})();
// Escape hatch: a broken streaming deploy is recoverable from Safari's URL bar
// without waiting on a Pages rebuild + the 10-minute cache TTL.
const NOSTREAM = _QS.get("nostream") === "1";

// ------------- Load data -----------------------------------------------------
// Fetch JSON, preferring a gzipped copy (~16x smaller). Robust to both GitHub
// Pages behaviours: if the .gz is served as raw gzip we inflate it via
// DecompressionStream; if the server already inflated it (Content-Encoding: gzip)
// we parse the bytes directly. Any failure falls back to the plain .json.
//
// The BOARD no longer comes through here — see loadBoardStreaming(). This is
// still the path for listings_detail.json (desktop only) and it stays exactly
// as it was, because it works and desktop is not what is broken.
async function fetchJsonMaybeGz(base, bust) {
  const q = bust ? `?t=${bust}` : "";
  try {
    const r = await fetch(`${base}.gz${q}`);
    if (r.ok) {
      const buf = new Uint8Array(await r.arrayBuffer());
      const isGzip = buf.length > 1 && buf[0] === 0x1f && buf[1] === 0x8b;
      if (isGzip) {
        if (typeof DecompressionStream === "undefined") throw new Error("no DecompressionStream");
        const stream = new Response(buf).body.pipeThrough(new DecompressionStream("gzip"));
        return JSON.parse(await new Response(stream).text());
      }
      return JSON.parse(new TextDecoder().decode(buf)); // server already inflated
    }
  } catch (e) { /* fall through to plain .json */ }
  const r2 = await fetch(`${base}${q}`);
  if (!r2.ok) throw new Error(`${base} missing`);
  return await r2.json();
}

// ===========================================================================
// STREAMING BOARD LOADER — the fix for the iPhone crash loop.
//
// The old path was one `JSON.parse(await new Response(stream).text())` over
// listings.json.gz. That materialises the ENTIRE document three times over:
// the 23 MB gz buffer, a 258.9 MB inflated UTF-16 string, and a ~241 MB parsed
// object graph, all alive simultaneously. 521 MB for one page load, 9.1 s on a
// fast wired desktop. iOS jetsams the WebContent process well below that, which
// is why both phones showed "a problem repeatedly occurred" on every launch.
//
// So we never hold the whole document. We stream the response, scan for
// top-level array-element boundaries, JSON.parse ONE record at a time, project
// it down to the fields this file actually reads, push the projection, and drop
// the consumed prefix off the buffer. Peak resident becomes one chunk + one
// ~7 KB record + the projected graph.
//
// The same code path reads the future slim payload: the projector is
// idempotent (an allowlist applied to an already-allowlisted record is a no-op)
// so listings_slim.json.gz is a pure speedup, never a dependency.
// ===========================================================================

// ---- BEGIN PORTABLE -------------------------------------------------------
// Pure data logic between these markers: no DOM, no fetch, no module globals
// beyond what is defined here. The Node harness at
// scratchpad/b/harness.mjs slices this exact region out of this file and runs
// it against the real docs/listings.json.gz, so the code under test IS the code
// that ships. Do not reference document / window / LEAN inside it.

/** Fresh state for the top-level-array boundary scanner. */
function boardScanState() {
  return { buf: "", pos: 0, started: false, ended: false, elemStart: -1, depth: 0, inStr: false, esc: false };
}

/**
 * Feed one text chunk to the scanner; `onElement(text)` fires once per complete
 * top-level array element.
 *
 * Hand-written because JSON.parse has no incremental mode — asking it for the
 * whole array is precisely what allocated the 258.9 MB string. It tracks three
 * things, and getting any one of them wrong silently corrupts a single record
 * somewhere in 38,500 with no error anywhere:
 *   - in-string state, because `}` and `]` are ordinary characters inside a
 *     JSON string and this board is full of legal descriptions like "LOT 3 [PH 2]";
 *   - backslash escapes, so `\"` does not close the string;
 *   - escaped backslashes, so a value ending in `\\` DOES close it.
 * \uXXXX needs no special case: the escape flag eats the `u` and the four hex
 * digits are ordinary characters. Astral-plane characters (U+1F4CA appears
 * 1,712 times in the real board) arrive as surrogate pairs, both code units
 * >= 0xD800, so they can never collide with an ASCII structural character.
 * Covered by scratchpad/b/test_scanner.mjs, including a fixture re-split at
 * every byte position.
 */
function boardScanChunk(st, chunk, onElement) {
  if (st.ended) return;
  if (chunk) st.buf += chunk;
  const s = st.buf;
  const n = s.length;
  let i = st.pos;
  while (i < n) {
    const c = s.charCodeAt(i);
    if (st.elemStart < 0) {
      // Between elements: whitespace, the opening `[`, `,` separators, `]` end.
      if (c === 32 || c === 9 || c === 10 || c === 13) { i++; continue; }
      if (!st.started) {
        if (c !== 91 /* [ */) throw new Error("board payload is not a JSON array");
        st.started = true; i++; continue;
      }
      if (c === 44 /* , */) { i++; continue; }
      if (c === 93 /* ] */) { st.ended = true; i++; break; }
      st.elemStart = i; st.depth = 0; st.inStr = false; st.esc = false;
      continue;                                   // re-read this char as content
    }
    if (st.esc) { st.esc = false; i++; continue; }
    if (st.inStr) {
      if (c === 92 /* \ */) st.esc = true;
      else if (c === 34 /* " */) st.inStr = false;
      i++; continue;
    }
    if (c === 34 /* " */) { st.inStr = true; i++; continue; }
    // A bare scalar element (number / true / null) ends at the separator, which
    // we must NOT consume — the between-elements branch above owns `,` and `]`.
    // This test has to come before the bracket handling or `[1]` would take the
    // depth-- path and never emit.
    if (st.depth === 0 && (c === 44 || c === 93)) {
      onElement(s.slice(st.elemStart, i)); st.elemStart = -1; continue;
    }
    if (c === 123 /* { */ || c === 91 /* [ */) { st.depth++; i++; continue; }
    if (c === 125 /* } */ || c === 93 /* ] */) {
      st.depth--; i++;
      if (st.depth === 0) { onElement(s.slice(st.elemStart, i)); st.elemStart = -1; }
      continue;
    }
    i++;
  }
  // Compact. This is the line that keeps peak memory flat: the buffer never
  // holds more than one partial record plus the tail of the current chunk.
  if (st.ended) { st.buf = ""; st.pos = 0; st.elemStart = -1; return; }
  if (st.elemStart > 0) {
    st.buf = s.slice(st.elemStart);
    st.pos = i - st.elemStart;
    st.elemStart = 0;
  } else if (st.elemStart === 0) {
    st.pos = i;
  } else {
    st.buf = i > 0 ? s.slice(i) : s;
    st.pos = 0;
  }
}

// --- The LEAN field allowlist ----------------------------------------------
// Top-level scalars: derived mechanically from every `l.<field>` read in this
// file plus the `l[k]` sort fallback (th[data-sort]) and the `l[f]` deadline
// fields — NOT hand-picked. The board carries 43 top-level keys. The 9 with no
// reader anywhere (legal_description, lot_size_sqft, land_use, assessed_value,
// market_value, living_sqft_estimated, first_seen, last_seen) plus
// `description` (replaced by the two precomputed values below) do not ship.
const _LEAN_TOP = [
  "source", "source_url", "listing_type", "property_kind",
  "street_address", "city", "state", "zip_code", "county", "parcel_id",
  "latitude", "longitude",
  "sale_date", "sale_time", "sale_location", "upset_bid_deadline", "redemption_deadline",
  "opening_bid", "judgment_amount", "tax_value", "auction_status", "foreclosure_process",
  "bedrooms", "bathrooms", "living_sqft", "year_built", "acreage", "zoning",
  "case_number", "plaintiff", "defendant", "trustee", "owner_name",
];
// Per-block sub-key allowlist. A block that exists in the source is ALWAYS
// emitted, even when none of its sub-keys survive, because several call sites
// test the block for existence rather than reading it (raw.upset_bid at :349,
// raw.bankruptcy at :632).
const _LEAN_RAW = {
  // grade and calc are kept WHOLE ("*"), not sub-allowlisted.
  //
  // They were sub-allowlisted, and both drifted immediately. The grade badge row
  // (:1781-1784) reads financial/property/location/risk unguarded and rendered a
  // literal "undefined undefined undefined undefined" on every phone. The
  // confidence pill (:1857) reads `confidence` — the list carried only
  // `arv_confidence` — so it defaulted, and every listing on every phone claimed
  // "CONFIDENCE: LOW". Both caught in verification 2026-08-10.
  //
  // A fabricated number on a board people bid money off is worse than a missing
  // one, and a hand-maintained sub-list of a block that gains keys every time
  // the valuation code changes will drift again. Measured cost of keeping both
  // blocks whole: ~6 MB against a 185 MB heap. Not a trade worth making.
  grade: "*",
  calc: "*",
  // data_quality.summary is 5.7 MB of prose and reads like an obvious LEAN cut.
  // It stays: it is the CSV's `data_quality_note` column, and the export must be
  // byte-identical on every device.
  data_quality: ["flags", "summary"],
  distress_stack: ["tier", "score", "stack", "signals", "categories", "absentee",
                   "out_of_state", "contactable", "equity_band", "surviving_senior_debt_risk"],
  signal_stack: ["count"],
  strategy_fit: ["tags"],
  owner_mailing: ["mailing", "mail_state", "absentee", "out_of_state"],
  owner_phone: ["phone", "source", "needs_dnc_scrub"],
  sos_agent: ["sosid", "best_contact_name", "best_contact_address"],
  rod: ["has_mortgage", "has_adverse_lien"],
  equity: ["value", "pct", "is_underwater"],
  title_risk: ["surviving_senior_debt_risk"],
  corroboration: ["court_confirmed", "label", "tier", "multi_source"],
  helene: ["worst_placard", "worst_damage_pct", "damaged_buildings"],
  bankruptcy: ["chapter", "date_filed", "case_name", "docket_number", "court"],
  courtlistener: ["chapter", "date_filed", "court"],
  last_sale: ["date", "amount", "basis"],
  zillow: ["photo"],
  gis: ["owner"],
  lrcpwa: ["absentee", "mail_state"],
  tax_owed: ["balance"],
  upset_bid: ["in_window", "days_remaining"],
};
const _LEAN_RAW_KEYS = Object.keys(_LEAN_RAW);
const _LEAN_RAW_SCALARS = [
  "intent_score", "intent_band", "multifamily_class",
  "stale_case", "geo_imprecise", "sold_confirmed", "kw_vacant", "acres",
];
const _ACRE_KEYS = ["acreage", "acres", "calculatedAcres", "deededAcres"];

/** Single implementation of the 12-way acreage probe (also used by _acresOf). */
function _acresProbe(raw) {
  const r = raw || {};
  for (const s of [r.lrcpwa, r.gis, r]) {
    if (s) for (const k of _ACRE_KEYS) { const v = parseFloat(s[k]); if (!isNaN(v)) return v; }
  }
  return null;
}

/** `raw.life_events` is an array in the fat board and an int in the slim one. */
function _lifeEventCount(le) {
  if (le == null) return 0;
  if (typeof le === "number") return le;
  return le.length || 0;
}

/**
 * Project one record onto what this file actually reads.
 *
 * FULL (lean=false) is the IDENTITY — no projection at all. That is deliberate
 * and it is not laziness: renderEverything() (:814) is a reflective sweep over
 * Object.keys(raw), and the real board carries 107 distinct raw keys against an
 * allowlist of ~25. Any named allowlist applied to desktop would silently gut
 * the "Everything We Found" panel, which exists precisely so that adding a
 * source can never again mean adding data nobody can see. Desktop therefore
 * gets byte-for-byte what it got before this change.
 *
 * LEAN drops what a phone cannot afford, and precomputes the two things that
 * were derived from `description` BEFORE discarding it, so mobile classifies
 * leads identically to desktop rather than merely looking similar.
 */
function projectRecord(rec, lean) {
  if (!lean || !rec || typeof rec !== "object" || Array.isArray(rec)) return rec;
  const out = {};
  for (let i = 0; i < _LEAN_TOP.length; i++) {
    const k = _LEAN_TOP[i];
    if (k in rec) out[k] = rec[k];
  }

  const desc = typeof rec.description === "string" ? rec.description : "";
  // kw_vacant replaces the description probe in _catOf() (:737), which decides
  // land vs residential and therefore which buyers match. Without this, mobile
  // would produce different buyer matches than desktop for the same lead.
  if (rec.kw_vacant != null) {
    out.kw_vacant = !!rec.kw_vacant;
  } else {
    const d = desc.toLowerCase();
    out.kw_vacant = d.includes("vacant lot") || d.includes("vacant land") || d.includes("vacant parcel");
  }

  const raw = rec.raw;
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
    if ("raw" in rec) out.raw = raw;
    return out;
  }
  const r = {};
  for (let i = 0; i < _LEAN_RAW_KEYS.length; i++) {
    const k = _LEAN_RAW_KEYS[i];
    const src = raw[k];
    if (src == null) continue;
    if (typeof src !== "object" || Array.isArray(src)) { r[k] = src; continue; } // shape drift: keep verbatim
    const subs = _LEAN_RAW[k];
    // "*" keeps the block whole. Used for blocks whose sub-keys are read in too
    // many places to track by hand — see the drift incident noted at _LEAN_RAW.
    if (subs === "*") { r[k] = src; continue; }
    const o = {};
    for (let j = 0; j < subs.length; j++) { const sk = subs[j]; if (sk in src) o[sk] = src[sk]; }
    r[k] = o;
  }
  for (let i = 0; i < _LEAN_RAW_SCALARS.length; i++) {
    const k = _LEAN_RAW_SCALARS[i];
    if (k in raw) r[k] = raw[k];
  }
  if (Array.isArray(raw.also_seen_in)) {
    r.also_seen_in = raw.also_seen_in.map((s) =>
      (s && typeof s === "object" && !Array.isArray(s)) ? { url: s.url, source: s.source } : s);
  }
  if ("life_events" in raw) r.life_events = _lifeEventCount(raw.life_events);
  // lrcpwa.mail_state is the flattened form of lrcpwa.mailing.state, which the
  // out-of-state chip (:992) reads. Flatten it here: today's board carries only
  // the nested key, so without this the chip silently vanished on mobile for
  // 270 of the 3,062 leads that carry an lrcpwa block. Caught by the harness.
  if (r.lrcpwa && r.lrcpwa.mail_state === undefined) {
    const lm = raw.lrcpwa && raw.lrcpwa.mailing;
    if (lm && typeof lm === "object" && lm.state != null) r.lrcpwa.mail_state = lm.state;
  }
  if (r.acres === undefined) {
    const a = _acresProbe(raw);
    if (a !== null) r.acres = a;
  }
  // heleneInfo() (:576) falls back to a regex over `description` when the dedup
  // meta has no placard. LEAN drops description, so run that fallback here,
  // while it is still in hand. Mirrors :581-586 exactly, including the fact
  // that the description's damage pct wins whenever the placard was missing.
  if (rec.source === "counties_nc.asheville_helene" && desc) {
    const h = r.helene || {};
    if (!h.worst_placard) {
      const m = /Helene damage:\s*([A-Za-z]+)\s+placard/.exec(desc);
      const p = /placard\s*-\s*([0-9]+)%/.exec(desc);
      if (m) h.worst_placard = m[1];
      if (p) h.worst_damage_pct = parseInt(p[1], 10);
      if (m || p) r.helene = h;
    }
  }
  out.raw = r;
  return out;
}
// ---- END PORTABLE ---------------------------------------------------------

// Slim first, fat second. The slim file does not exist yet; the 404 fallback is
// the path that runs today, and one 404 is a fair price for making the future
// payload a drop-in with zero client change.
const BOARD_FILES = ["listings_slim.json.gz", "listings.json.gz"];
// A stream that has produced nothing for this long is not slow, it is stuck.
// Rural Upstate SC / Western NC cellular is the target environment, and on a
// webclip a stalled stream looks exactly like the crash we are fixing.
const BOARD_STALL_MS = 60000;

/** One-line status bar, injected the way the error banner at :88 is. */
function boardProgress(msg) {
  let el = $("board-progress");
  if (msg === null) { if (el) el.remove(); return; }
  if (!el) {
    document.body.insertAdjacentHTML("afterbegin",
      '<div id="board-progress" role="status" style="position:fixed;left:0;right:0;top:0;z-index:9999;' +
      'background:#1f6feb;color:#fff;padding:9px 14px;text-align:center;font:600 13px/1.35 ' +
      "system-ui,-apple-system,'Segoe UI',sans-serif\">&nbsp;</div>");
    el = $("board-progress");
  }
  if (el) el.textContent = msg;
}

/**
 * Stream the board, one record at a time. Returns the projected array.
 * `onProgress(count)` is called per chunk; throttle in the callback.
 */
async function loadBoardStreaming(bust, onProgress) {
  const ac = new AbortController();
  const q = `?t=${encodeURIComponent(bust)}`;
  let res = null;
  for (const name of BOARD_FILES) {
    let r = null;
    try { r = await fetch(name + q, { signal: ac.signal }); } catch (e) { r = null; }
    if (r && r.ok && r.body) { res = r; break; }
  }
  if (!res) throw new Error("board payload missing");

  // Peek the first two bytes before deciding to inflate. The code this replaces
  // sniffed the gzip magic (:35) for a reason: this file has been served
  // already-inflated (Content-Encoding: gzip) before, and an unconditional
  // DecompressionStream would then throw on every device, everywhere, at once.
  // Do not delete a defence whose comment names the incident that produced it.
  const reader = res.body.getReader();
  let head = new Uint8Array(0);
  let exhausted = false;
  while (head.length < 2) {
    const r = await reader.read();
    if (r.done) { exhausted = true; break; }
    if (!r.value || !r.value.length) continue;
    const merged = new Uint8Array(head.length + r.value.length);
    merged.set(head); merged.set(r.value, head.length);
    head = merged;
  }
  const isGzip = head.length > 1 && head[0] === 0x1f && head[1] === 0x8b;
  if (isGzip && typeof DecompressionStream === "undefined") throw new Error("NO_DECOMPRESSION");

  let lastByteAt = Date.now();
  const watchdog = setInterval(() => {
    if (Date.now() - lastByteAt > BOARD_STALL_MS) { try { ac.abort(); } catch (e) { /* noop */ } }
  }, 5000);

  try {
    const src = new ReadableStream({
      start(c) { if (head.length) c.enqueue(head); if (exhausted) c.close(); },
      async pull(c) {
        const r = await reader.read();
        lastByteAt = Date.now();
        if (r.done) c.close(); else c.enqueue(r.value);
      },
      cancel(reason) { try { reader.cancel(reason); } catch (e) { /* noop */ } },
    });
    let bytes = src;
    if (isGzip) bytes = bytes.pipeThrough(new DecompressionStream("gzip"));
    const text = bytes.pipeThrough(new TextDecoderStream()).getReader();

    const out = [];
    const st = boardScanState();
    const onElement = (s) => { out.push(projectRecord(JSON.parse(s), LEAN)); };
    for (;;) {
      const r = await text.read();
      if (r.done) break;
      lastByteAt = Date.now();
      boardScanChunk(st, r.value, onElement);
      if (onProgress) onProgress(out.length);
    }
    boardScanChunk(st, "", onElement);   // flush a trailing bare scalar, if any
    // A truncated download would otherwise render a silently partial board —
    // and this board carries sale dates and bid deadlines. Fail loudly instead.
    if (!st.ended) throw new Error("board payload truncated");
    return out;
  } finally {
    clearInterval(watchdog);
  }
}

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
      // run_meta.json first, and its run_time becomes the board's cache key.
      // The old `?t=${Date.now()}` guaranteed a fresh 23 MB download on EVERY
      // launch, even when the board was byte-identical to the copy the phone
      // had five minutes ago. run_time busts the cache exactly when the board
      // actually changes — the convention ensureDetails() already uses for
      // listings_detail.json. run_meta.json itself is 13 KB and stays uncached.
      const metaRes = await fetch(`run_meta.json?t=${Date.now()}`);
      META = metaRes.ok ? await metaRes.json() : {};
      const bust = META.run_time || Date.now();
      const total = Number(META.total) || 0;
      let painted = 0;
      boardProgress("Loading listings…");
      const onProgress = (n) => {
        if (n - painted < 2000) return;          // ~19 repaints, not 38,500
        painted = n;
        boardProgress(total ? `Loading ${n.toLocaleString()} of ${total.toLocaleString()}…`
                            : `Loading ${n.toLocaleString()} listings…`);
      };
      try {
        if (NOSTREAM) throw new Error("NOSTREAM");
        LISTINGS = await loadBoardStreaming(bust, onProgress);
      } catch (streamErr) {
        // A machine with the headroom for the old path should show a board
        // rather than an error if the new one fails. LEAN deliberately does
        // NOT fall back: the old path on a phone IS the crash we are fixing.
        if (LEAN || String(streamErr.message) === "NO_DECOMPRESSION") throw streamErr;
        boardProgress("Loading listings (fallback)…");
        LISTINGS = await fetchJsonMaybeGz("listings.json", bust);
      }
      boardProgress(null);
    }
    DS_CACHE[name] = { listings: LISTINGS, meta: META };
  } catch (e) {
    LISTINGS = [];
    META = {};
    boardProgress(null);
    if (name === "foreclosure") {
      // DecompressionStream is Safari 16.4+. The old fallback here fetched the
      // plain listings.json, which 404s on Pages (it is excluded in
      // docs/_config.yml) — so an old iPhone got a silent empty board. Say the
      // true thing instead.
      const msg = String(e && e.message) === "NO_DECOMPRESSION"
        ? "This board needs iOS 16.4 or newer (or a current desktop browser) to open."
        : "Could not load listings — first run hasn't finished yet, or network error. Reload in a few minutes.";
      document.body.insertAdjacentHTML(
        "afterbegin",
        `<div style="background:#ffd2dc;color:#b22a2a;padding:14px 28px;text-align:center;">${msg}</div>`,
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
  // `.ds-btn[data-ds]`, not `.ds-btn`. index.html gives the six stage buttons
  // BOTH classes, so the bare selector (a) stripped `active` off whichever
  // stage was selected, and (b) made one stage click run both the dataset
  // handler and the stage handler. Scoping to [data-ds] separates them without
  // touching index.html.
  document.querySelectorAll(".ds-btn[data-ds]").forEach(btn => {
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
  await Promise.all([loadDataset("foreclosure"), preloadDatasetCounts(), loadBuyerRegistry()]);
  // Wire toggle buttons (dataset pills only — see refreshDatasetUI)
  document.querySelectorAll(".ds-btn[data-ds]").forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.ds;
      document.querySelectorAll(".ds-btn[data-ds]").forEach((b) => b.classList.toggle("active", b === btn));
      if (target === "_buyers") { enterBuyersMode(); return; }
      if (BUYERS_MODE) exitBuyersMode();
      if (target && target !== DATASET) loadDataset(target);
    });
  });
}

async function loadBuyerRegistry() {
  try {
    const r = await fetch(`land_buyers.json?t=${Date.now()}`);
    if (r.ok) { BUYER_REGISTRY = (await r.json()).buyers || []; }
  } catch (e) { BUYER_REGISTRY = []; }
  BUYER_REGISTRY = BUYER_REGISTRY.concat(_EXTRA_BUYERS);
  const c = document.getElementById("ds-buyers-count");
  if (c) c.textContent = BUYER_REGISTRY.length;
}

// ------------- Stats ---------------------------------------------------------
function fillStats() {
  $("stat-total").textContent = LISTINGS.length;
  const byGrade = { A: 0, B: 0, C: 0, D: 0, F: 0 };
  let posRoi = 0, withBid = 0;
  // One pass. The source Set used to be a separate `.map().filter()` here,
  // which allocated two throwaway 38,500-element arrays on every dataset load.
  const sources = new Set();
  LISTINGS.forEach((l) => {
    const g = getGrade(l);
    if (g && g.overall) byGrade[g.overall] = (byGrade[g.overall] || 0) + 1;
    const c = getCalc(l);
    if (c && c.roi_pct != null && c.roi_pct > 0) posRoi += 1;
    if (l.opening_bid) withBid += 1;
    if (l.source) sources.add(l.source);
  });
  $("stat-a").textContent = byGrade.A;
  $("stat-b").textContent = byGrade.B;
  $("stat-c").textContent = byGrade.C;
  $("stat-positive-roi").textContent = posRoi;
  $("stat-with-bid").textContent = withBid;
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
// Every control except #search. #search is bound separately, debounced.
const FILTER_IDS = ["filter-state", "filter-county", "filter-type", "filter-contact",
  "filter-land", "filter-strategy", "filter-arv", "filter-source", "filter-distress",
  "filter-signals", "filter-intent", "filter-grade", "filter-window", "filter-roi"];
// The listener half of initFilters() must run EXACTLY once. It used to run on
// every call, and initFilters() is called from both loadDataset() branches, so
// after k dataset-pill clicks every keystroke ran applyFilters k+1 times and
// one click on Export CSV built and downloaded the ~19 MB file k+1 times. The
// author caught the same class of bug for the <option> lists (resetSelect,
// below) and missed it for the listeners.
let _WIRED = false;
// Captured at wiring time so #filter-active-count can say how many controls are
// off their default, whatever the markup's defaults happen to be.
const _FILTER_DEFAULTS = {};

function initFilters() {
  // Idempotent: loadDataset() calls this on every (re)load + dataset switch, so
  // strip any previously-appended options (keep the first "All …" default)
  // before repopulating — otherwise counties/sources duplicate on each call.
  const resetSelect = (el) => {
    while (el.options.length > 1) el.remove(1);
  };

  // One pass for both sets; this used to walk LISTINGS twice.
  const counties = new Set();
  const sources = new Set();
  LISTINGS.forEach((l) => {
    if (l.county) counties.add(`${l.county}, ${l.state || "?"}`);
    if (l.source) sources.add(l.source);
  });
  const fill = (el, values) => {
    resetSelect(el);
    Array.from(values).sort().forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      el.appendChild(opt);
    });
  };
  fill($("filter-county"), counties);
  fill($("filter-source"), sources);

  // updateStageCounts() stays OUTSIDE the wiring guard: the counts are derived
  // from LISTINGS, so they must refresh on every dataset switch.
  updateStageCounts();
  if (_WIRED) { updateFilterCount(); return; }
  _WIRED = true;

  FILTER_IDS.forEach((id) => {
    const el = $(id);
    if (!el) return;
    _FILTER_DEFAULTS[id] = el.value;
    el.addEventListener("input", applyFilters);
  });
  // #search is NOT in that list. It fires an `input` event per character, and
  // applyFilters rebuilds a 12-element array + join + toLowerCase for all
  // 38,497 records — ~115,000 allocations per keystroke, on the main thread,
  // while the user is typing. 250 ms of debounce removes the GC storm without
  // changing a single result.
  //
  // Phones only. Desktop already absorbed this fine (the memoised _blob does the
  // real work) and debouncing it there cost instant type-ahead for everyone —
  // measured 100 ms after an input event: 57 results before, 1,199 after.
  // Desktop is the thing that currently works; it does not pay for a mobile fix.
  const search = $("search");
  if (search) {
    if (LEAN) {
      let t = null;
      search.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(applyFilters, 250);
      });
    } else {
      search.addEventListener("input", applyFilters);
    }
  }
  // Live-sync the intent slider's numeric readout as it drags.
  const intentSlider = $("filter-intent");
  if (intentSlider) intentSlider.addEventListener("input", () => { $("filter-intent-val").textContent = intentSlider.value; });

  document.querySelectorAll(".view-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      $(`view-${btn.dataset.view}`).classList.add("active");
      if (btn.dataset.view === "map") setTimeout(initMap, 60);
      // Cards are rendered on demand now, the same way the map already was.
      if (btn.dataset.view === "cards") renderCards();
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
      const sm = $("sort-mobile");
      if (sm && sm.value !== k) sm.value = k;
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

  initMobileShell();

  $("export-csv").addEventListener("click", exportCsv);
  $("close-detail").addEventListener("click", () => $("detail-panel").classList.add("hidden"));
  updateFilterCount();
}

// ---- Mobile shell controls (#filter-sheet-toggle, #sort-mobile) -------------
// Both live in index.html and are display:none above 720px. Every lookup is
// guarded: this file must not throw if the markup has not landed yet.
function initMobileShell() {
  const toggle = $("filter-sheet-toggle");
  const filters = document.querySelector(".filters");
  if (toggle && filters) {
    // Start collapsed only where the toggle is actually shown, so the button's
    // aria-expanded="false" and the panel agree. Keyed off C's 720px
    // breakpoint, not LEAN's 820 — between the two the sheet stays open and the
    // toggle stays hidden, which is the deliberate 100px gap.
    if (typeof matchMedia === "function" && matchMedia("(max-width:720px)").matches) {
      filters.classList.add("is-collapsed");
    }
    toggle.addEventListener("click", () => {
      const collapsed = filters.classList.toggle("is-collapsed");
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });
  }
  // The mobile layout hides <thead>, which takes the th[data-sort] click
  // targets with it. Dispatch a click on the matching th so the sort path,
  // including the asc/desc toggle, is reused completely unchanged.
  // Mobile sort was one-way. <thead> is display:none below 720px, so the th
  // click handler that normally toggles direction is unreachable, and re-picking
  // the already-selected option in a native select fires no `change` event. The
  // result: picking ROI gave -99.8% first, and going back to Grade put the
  // UNGRADED records on top with no way to reverse it short of a reload.
  //
  // Two fixes: an explicit direction button, and a sensible default direction
  // per key. The th handler defaults every new key to "asc" (:753), which is
  // right for an address and wrong for every quality/money column.
  const SORT_DESC_FIRST = {
    _grade: 1, _roi: 1, _arv: 1, _max_bid: 1, _rehab: 1,
    opening_bid: 1, living_sqft: 1, year_built: 1, bedrooms: 1, bathrooms: 1,
  };
  const sortSel = $("sort-mobile");
  const sortDirBtn = $("sort-dir");
  const paintDir = () => { if (sortDirBtn) sortDirBtn.textContent = sortDir === "asc" ? "↑" : "↓"; };
  if (sortSel) {
    sortSel.value = sortKey;
    sortSel.addEventListener("change", () => {
      const k = sortSel.value.replace(/"/g, "");
      const th = document.querySelector(`th[data-sort="${k}"]`);
      if (th) th.click();
      // th.click() has just set sortDir="asc" for the newly-picked key. Override
      // it for the columns where "best first" is the only sane opening state.
      if (SORT_DESC_FIRST[k] && sortDir === "asc") { sortDir = "desc"; applyFilters(); }
      paintDir();
    });
  }
  if (sortDirBtn) {
    sortDirBtn.addEventListener("click", () => {
      sortDir = sortDir === "asc" ? "desc" : "asc";
      applyFilters();
      paintDir();
    });
  }
  paintDir();
}

/** "Filters (3)" — how many controls are off their captured default. */
function updateFilterCount() {
  const badge = $("filter-active-count");
  if (!badge) return;
  let n = 0;
  FILTER_IDS.forEach((id) => {
    const el = $(id);
    if (el && id in _FILTER_DEFAULTS && el.value !== _FILTER_DEFAULTS[id]) n += 1;
  });
  badge.textContent = n ? `(${n})` : "";
}

// ------------- Filtering + sorting ------------------------------------------
// Memoised derived values live on the listing itself, but ALWAYS as
// non-enumerable properties. exportCsv used to spread `{...l}` and any future
// serialization would do the same, so an ordinary `l._blob = …` would leak a
// 150-character lowercased blob into the CSV. Non-enumerable makes that
// impossible rather than merely unlikely.
function _memo(l, key, value) {
  Object.defineProperty(l, key, { value, writable: true, enumerable: false, configurable: true });
  return value;
}

function getSortValue(l, k) {
  if (k === "_grade") {
    const g = getGrade(l);
    return g ? g.overall_score || gradeOrder[g.overall] || 0 : -1;
  }
  if (k === "_arv") {
    // Pure function of immutable data, and the sort calls it ~1.17 M times —
    // each call was doing two .includes() scans over data_quality.flags.
    if (l._sv_arv !== undefined) return l._sv_arv;
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
    return _memo(l, "_sv_arv", unrated ? -1 : arv);
  }
  if (k === "_rehab") return (getCalc(l) || {}).rehab_expected || 0;
  if (k === "_max_bid") return (getCalc(l) || {}).max_bid_70 || 0;
  if (k === "_roi") return (getCalc(l) || {}).roi_pct;
  if (k === "_distress") return (getDistress(l) || {}).score || 0;
  if (k === "_intent") return getIntent(l);
  return l[k];
}

// ---- Stage classification: which workflow track a lead is in --------------
// You work these lists differently: foreclosure leads are time-sensitive (act
// before the sale), outbound leads are cold prospects you mail/call. Derived
// client-side from listing_type + sale_date + source — no board field needed.
const STAGE_REO = /hud_homestore|fannie|freddie|homepath|homesteps|hubzu|xome|auction_dot_com|bid4assets|servicelink|gsa_real|usda_rd|treasury_seized|vrm_va|first_citizens|reo\.|foreclosure_dot_com/;
const STAGE_PREFORE = /substitute_trustee|nod_discovery|lis_pendens|rod_acclaim|rod_cott|rod_logan|nc_rod|sc_rod/;
let STAGE = "";

// ---------------------------------------------------------------------------
// DEADLINES.
//
// A lead with a legal clock on it is worth more than a hundred without one: a
// tax sale you find the day after is worth nothing. These dates were already on
// every listing, but they sat as one column among seventeen, so the 141 leads
// with a deadline inside 45 days were invisible among 25,552 rows.
// ---------------------------------------------------------------------------
const DEADLINE_WINDOW_DAYS = 45;
const DEADLINE_FIELDS = [
  ["upset_bid_deadline", "upset bid closes"],
  ["sale_date", "sale"],
  ["redemption_deadline", "redemption ends"],
];

// Short-lived memo. The deadline comparator calls this twice per comparison and
// each call does up to three Date.parse, so a 38 K sort was ~460 K date parses;
// updateStageCounts adds another 115 K on every dataset switch. The result is
// NOT cached for the session — `days` is relative to now, and this board is the
// reason someone drives to a courthouse — so it expires after a minute, which
// is orders of magnitude longer than a sort and orders of magnitude shorter
// than the value changing.
const _DL_TTL_MS = 60000;

/** Soonest un-expired deadline on a listing, or null. */
function deadlineInfo(l) {
  const now = Date.now();
  const m = l._dl;
  if (m && now - m.at < _DL_TTL_MS) return m.v;
  let best = null;
  for (const [f, label] of DEADLINE_FIELDS) {
    const v = l[f];
    if (!v) continue;
    const t = Date.parse(v);
    if (isNaN(t)) continue;
    const days = Math.floor((t - now) / 86400000);
    if (days < 0) continue;                     // already gone
    if (!best || days < best.days) best = { days, label, field: f, ts: t };
  }
  _memo(l, "_dl", { at: now, v: best });
  return best;
}

/** True when the lead cannot be acted on yet — no way to reach the owner. */
function deadlineBlocked(l) {
  return !(l.street_address || "").trim() || !(l.owner_name || "").trim();
}

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
  const c = { "": 0, foreclosure: 0, prefore: 0, outbound: 0, reo: 0, deadline: 0 };
  LISTINGS.forEach((l) => {
    if (l.raw && l.raw.sold_confirmed) return;
    c[""]++;
    c[stageOf(l)]++;
    const d = deadlineInfo(l);
    if (d && d.days <= DEADLINE_WINDOW_DAYS) c.deadline++;
  });
  document.querySelectorAll(".stage-count").forEach((el) => {
    el.textContent = (c[el.dataset.c] || 0).toLocaleString();
  });
}

// The search blob: 12 fields joined + lowercased, for every record, on every
// keystroke. Memoised on FULL. NOT memoised on LEAN — ~150 UTF-16 characters
// × 38,500 is ~12 MB held permanently, and RAM is the exact resource the phone
// runs out of; the 250 ms debounce already removes the per-keystroke cost.
const MEMO_BLOB = !LEAN;
function searchBlob(l) {
  if (l._blob !== undefined) return l._blob;
  const b = [
    l.street_address, l.city, l.county, l.state, l.zip_code, l.case_number,
    l.plaintiff, l.defendant, l.trustee, l.source, l.parcel_id,
    (l.raw && l.raw.gis && l.raw.gis.owner) || "",
  ].join(" ").toLowerCase();
  return MEMO_BLOB ? _memo(l, "_blob", b) : b;
}

// #view-cards has no `active` class at boot and style.css hides it, but
// renderCards() was called unconditionally — so every keystroke built ~5,000
// invisible elements and 200 closures. Gate it the way initMap already was.
function maybeRenderCards() {
  const v = $("view-cards");
  if (v && v.classList.contains("active")) renderCards();
}

function applyFilters() {
  const q = $("search").value.toLowerCase();
  const st = $("filter-state").value;
  const co = $("filter-county").value;
  const ty = $("filter-type").value;
  const land = $("filter-land").value;
  const src = $("filter-source").value;
  const contact = $("filter-contact").value;
  const strategy = ($("filter-strategy") || {}).value || "";
  const arvc = ($("filter-arv") || {}).value || "";
  const distress = $("filter-distress").value;
  const minSignals = $("filter-signals") ? parseInt($("filter-signals").value) || 0 : 0;
  const minIntent = $("filter-intent") ? parseInt($("filter-intent").value) || 0 : 0;
  const minGrade = $("filter-grade").value;
  const minGradeRank = minGrade ? gradeOrder[minGrade] : 0;
  const win = parseInt($("filter-window").value);
  const minRoi = $("filter-roi").value === "" ? null : parseFloat($("filter-roi").value);
  const now = Date.now();
  const wmax = win ? now + win * 86400000 : 0;

  // Tier tally, folded into the filter pass. It used to be a second full pass
  // over `filtered` on every keystroke.
  let hot = 0, warm = 0;
  filtered = LISTINGS.filter((l) => {
    // Court-confirmed sales already sold at auction — not opportunities. Hide.
    if (l.raw && l.raw.sold_confirmed) return false;
    if (STAGE === "deadline") {
      const d = deadlineInfo(l);
      if (!d || d.days > DEADLINE_WINDOW_DAYS) return false;
    } else if (STAGE && stageOf(l) !== STAGE) return false;
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
    // List-stacking: distinct distress signals/sources hitting this property.
    if (minSignals && getSignalCount(l) < minSignals) return false;
    // Intent score (0-100 headline): hide anything below the slider threshold.
    if (minIntent && getIntent(l) < minIntent) return false;
    if (strategy) {
      const sf = (l.raw && l.raw.strategy_fit) || null;
      if (strategy === "_buyers") { if (!buyerCountForListing(l)) return false; }
      else if (!(sf && sf.tags && sf.tags.includes(strategy))) return false;
    }
    if (arvc) {
      const cc = (l.raw && l.raw.calc) || {};
      if (arvc === "comp" && cc.arv_confidence !== "HIGH") return false;
      if (arvc === "noproxy" && (cc.arv_confidence === "LOW" || !cc.arv_expected)) return false;
    }
    if (contact) {
      const r = l.raw || {};
      const om = r.owner_mailing || {};
      const sac = (r.sos_agent && r.sos_agent.best_contact_address) || (r.sos_agent && r.sos_agent.best_contact_name);
      if (contact === "phone" && !r.owner_phone) return false;
      if (contact === "mailing" && !om.mailing) return false;
      if (contact === "contactable" && !(r.owner_phone || om.mailing || sac)) return false;
      if (contact === "sos_entity" && !(r.sos_agent && r.sos_agent.best_contact_name)) return false;
      if (contact === "helene" && l.source !== "counties_nc.asheville_helene") return false;
      if (contact === "helene_severe") { const h = heleneInfo(l); if (!h || h.placard !== "Unsafe") return false; }
      if (contact === "absentee" && !om.absentee) return false;
      if (contact === "out_of_state" && !om.out_of_state) return false;
      if (contact === "mortgage" && !(r.rod && r.rod.has_mortgage)) return false;
      // life_events is an array in the fat board and an int count in the slim
      // one / the LEAN projection — `.length` alone would silently empty this
      // filter on mobile.
      if (contact === "estate_elderly" && !_lifeEventCount(r.life_events)) return false;
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
    if (q && !searchBlob(l).includes(q)) return false;
    const _tier = (getDistress(l) || {}).tier;
    if (_tier === "HOT") hot++; else if (_tier === "WARM") warm++;
    return true;
  });

  // When the operator is filtering by distress / stack / intent, surface
  // hottest-first regardless of the table-header sort (the board reads like a
  // lead queue). Intent is the single headline rank, so it wins when set.
  const rankByIntent = minIntent || minSignals;
  const effKey = rankByIntent ? "_intent" : distress ? "_distress" : sortKey;
  const effDir = (rankByIntent || distress) ? "desc" : sortDir;
  if (STAGE === "deadline") {
    // Soonest clock first; a lead you cannot act on yet sinks below one you can.
    filtered.sort((a, b) => {
      const da = deadlineInfo(a), db = deadlineInfo(b);
      const ba = deadlineBlocked(a) ? 1 : 0, bb = deadlineBlocked(b) ? 1 : 0;
      if (ba !== bb) return ba - bb;
      return (da ? da.ts : Infinity) - (db ? db.ts : Infinity);
    });
    renderTable();
    maybeRenderCards();
    updateFilterCount();
    const blocked = filtered.filter(deadlineBlocked).length;
    const today = filtered.filter((l) => { const d = deadlineInfo(l); return d && d.days === 0; }).length;
    $("result-count").textContent =
      `${filtered.length} with a deadline in ${DEADLINE_WINDOW_DAYS} days` +
      (today ? `  ·  ⏰ ${today} TODAY` : "") +
      (blocked ? `  ·  ${blocked} not actionable yet (no owner or address)` : "");
    return;
  }

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
  maybeRenderCards();
  updateFilterCount();
  // Tier tally over the current filtered set (the operator-board headline),
  // counted during the filter pass above.
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

// ---- Lead signals: list-stacking + intent score (enrichment_lead_signals) ---
function getSignalStack(l) { return (l.raw && l.raw.signal_stack) || null; }
function getSignalCount(l) {
  const ss = getSignalStack(l);
  if (ss && typeof ss.count === "number") return ss.count;
  // Fallback for pre-enricher snapshots: read the distress-stack signal list.
  const ds = getDistress(l);
  return ds && Array.isArray(ds.signals) ? ds.signals.length : 0;
}
function getIntent(l) {
  const v = l.raw && l.raw.intent_score;
  return typeof v === "number" ? v : 0;
}
// "🔥 N signals" chip — mirrors the distress-chip look; tooltip lists them.
function signalStackChip(l) {
  const n = getSignalCount(l);
  if (n < 2) return "";  // only worth surfacing a real STACK
  const ss = getSignalStack(l);
  const list = ss && Array.isArray(ss.signals) ? ss.signals : [];
  const tip = list.map((s) => String(s).replace(/_/g, " ")).join(", ");
  return `<span class="distress-chip signal-stack" title="${n} distinct distress signals: ${tip}">🔥 ${n} signals</span>`;
}
// Small intent-score badge (0-100 headline), colored by band.
function intentBadge(l) {
  const v = getIntent(l);
  if (!v) return "";
  const band = (l.raw && l.raw.intent_band) || (v >= 70 ? "hot" : v >= 45 ? "warm" : v >= 20 ? "cool" : "cold");
  return `<span class="intent-badge intent-${band}" title="Intent score ${v}/100 (${band}) — stacked distress + weighted score + grade">${v}</span>`;
}

// Hurricane-Helene ATC-45 placard info for a lead, from the dedup meta or the
// description ("Helene damage: Unsafe placard - 90%"). Returns null if not Helene.
function heleneInfo(l) {
  if (!l || l.source !== "counties_nc.asheville_helene") return null;
  const meta = (l.raw && l.raw.helene) || {};
  let placard = meta.worst_placard || null, pct = meta.worst_damage_pct || null;
  const buildings = meta.damaged_buildings || 1;
  if (!placard) {
    const m = /Helene damage:\s*([A-Za-z]+)\s+placard/.exec(l.description || "");
    if (m) placard = m[1];
    const p = /placard\s*-\s*([0-9]+)%/.exec(l.description || "");
    if (p) pct = parseInt(p[1], 10);
  }
  if (!placard) return null;
  return { placard, pct, buildings };
}
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
// Desktop keeps 800 rows — 800 × 17 columns ≈ 18,400 elements per render, which
// is fine on a desktop and is not fine on a phone that is already at its heap
// ceiling. There is no virtualisation here, just the cap.
const ROW_CAP = LEAN ? 50 : 800;
let _TBODY_WIRED = false;

function renderTable() {
  const tb = $("listings-tbody");
  // One delegated listener instead of 800 fresh closures on every keystroke.
  if (!_TBODY_WIRED) {
    _TBODY_WIRED = true;
    tb.addEventListener("click", (e) => {
      const tr = e.target && e.target.closest ? e.target.closest("tr") : null;
      if (tr && tr.dataset.id !== undefined) openDetail(filtered[parseInt(tr.dataset.id)]);
    });
  }
  tb.innerHTML = filtered
    .slice(0, ROW_CAP)
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
      let dateCell = isBkSource && cl && cl.date_filed ? cl.date_filed : fmtDate(l.sale_date);
      // In the deadline track the clock IS the point, so it replaces the date.
      if (STAGE === "deadline") {
        const d = deadlineInfo(l);
        if (d) {
          const cls = d.days === 0 ? "dl-today" : d.days <= 7 ? "dl-week" : "dl-soon";
          const txt = d.days === 0 ? "TODAY" : `${d.days}d`;
          dateCell = `<span class="dl-pill ${cls}" title="${d.label} — ${fmtDate(l[d.field])}">${txt}</span>` +
                     `<span class="dl-kind">${d.label}</span>` +
                     (deadlineBlocked(l) ? `<span class="dl-blocked" title="No owner name or street address — cannot act on this yet">⚠</span>` : "");
        }
      }
      return `
    <tr class="${rowClass}" data-id="${i}">
      <td>${(() => { const ds = getDistress(l); return ds && distressLabel[ds.tier] ? `<span class="tier-dot ${distressLabel[ds.tier].cls}" title="${ds.tier} · ${(ds.signals || []).join(', ')}"></span>` : ""; })()}${gradeBadge(g)}${intentBadge(l)}</td>
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
}

// ------------- Cards render --------------------------------------------------
// ---- Strategy-fit pills + buyer-match chip (this session's new intelligence) ----
const STRATEGY_META = {
  LAND_WHOLESALE: { label: "Land wholesale", cls: "strat-land" },
  WHOLESALE: { label: "Wholesale", cls: "strat-whsl" },
  SUBJECT_TO: { label: "Subject-to", cls: "strat-subto" },
  FIX_FLIP: { label: "Fix & flip", cls: "strat-flip" },
  GATOR: { label: "Gator", cls: "strat-gator" },
};
function strategyBuyerChips(l) {
  const chips = [];
  const sf = (l.raw && l.raw.strategy_fit) || null;
  if (sf && sf.tags) {
    sf.tags.forEach((t) => {
      const m = STRATEGY_META[t];
      if (m) chips.push(`<span class="strat-chip ${m.cls}" title="${(sf.reasons && sf.reasons[t]) || t}">${m.label}</span>`);
    });
  }
  const cc = (l.raw && l.raw.calc) || {};
  if (cc.arv_confidence === "HIGH") {
    chips.push(`<span class="strat-chip strat-comp" title="ARV grounded in real sold comps — not a Zestimate/assessed-value proxy">✓ comp-backed ARV</span>`);
  }
  const bt = buyersForListing(l);
  const bcount = Object.values(bt).reduce((n, a) => n + a.length, 0);
  if (bcount) {
    chips.push(`<span class="buyer-chip" title="${bcount} active buyers across ${Object.keys(bt).length} categories — open the Land Buyers tab">🏢 ${bcount} buyers want this</span>`);
  }
  return chips.length ? `<div class="strat-chips">${chips.join("")}</div>` : "";
}

// ============================================================================
// LAND BUYERS view — the 188-buyer registry, matched to listings client-side
// (so the board JSON stays small; buyers are computed on the fly, not stored).
// ============================================================================
let BUYER_REGISTRY = [];
const _WNC = new Set(["Buncombe","Henderson","Rutherford","McDowell","Cleveland","Polk","Gaston","Lincoln","Burke","Transylvania","Mitchell","Madison"]);
const _UPSTATE = new Set(["Greenville","Spartanburg","Anderson","Pickens","Oconee","Cherokee","Union","Laurens"]);
const _I85 = new Set(["Spartanburg","Greenville","Cherokee","Anderson","Gaston"]);
const _LAND_TYPES = new Set(["residential_land_developers","production_homebuilders","regional_local_builders","timber_recreational","solar_utility_land","conservation_trusts","manufactured_housing","econ_dev_municipal"]);
const _MF_TYPES = new Set(["multifamily_developers"]);
const _COMM_TYPES = new Set(["commercial_retail_office","industrial_logistics","self_storage"]);
const BUYER_TYPE_LABEL = {
  production_homebuilders:"Production builders", regional_local_builders:"Regional builders",
  residential_land_developers:"Land developers", multifamily_developers:"Multifamily developers",
  commercial_retail_office:"Commercial developers", industrial_logistics:"Industrial / logistics",
  self_storage:"Self-storage", solar_utility_land:"Solar / utility-scale",
  manufactured_housing:"Manufactured housing", timber_recreational:"Timber / recreational",
  conservation_trusts:"Conservation trusts", econ_dev_municipal:"Economic development",
  land_flippers:"Cash land buyers", house_buyers:"Cash house buyers",
};
// Direct "we buy land / houses" cash outreach lanes (not in the 188 registry; added client-side)
const _EXTRA_BUYERS = [
  {name:"Bubba Land Company", type:"land_flippers", contact:"https://bubba-land.com/", buys:"rural acreage 3+ ac, outside city limits", regions:["wnc","upstate_sc"], min_acres:3, geo:"All 19 WNC + Upstate-SC counties"},
  {name:"Value Land Buyers", type:"land_flippers", contact:"https://www.valuelandbuyers.com/", buys:"raw land + vacant lots, any size", regions:["wnc","upstate_sc"], geo:"All 19 WNC + Upstate-SC counties"},
  {name:"Selling Land Fast", type:"land_flippers", contact:"https://www.sellinglandfast.com/", buys:"rural acreage, raw land, lots, farms", regions:["wnc","upstate_sc"], geo:"All 19 WNC + Upstate-SC counties"},
  {name:"HomeVestors / We Buy Ugly Houses", type:"house_buyers", contact:"https://www.webuyuglyhouses.com/", buys:"cash for houses, blanket coverage", regions:["wnc","upstate_sc"], geo:"Footprint-wide"},
  {name:"Greenville Home Solutions", type:"house_buyers", contact:"https://www.greenvillehomesolutions.com/", buys:"houses + land, Upstate SC", regions:["upstate_sc"], geo:"Greenville/Anderson/Pickens/Oconee/Spartanburg/Laurens"},
];
// Single implementation, shared with the projector (_acresProbe). On the LEAN
// projection raw.lrcpwa/raw.gis carry no acreage keys and the precomputed
// raw.acres is found on the third probe, so the answer is identical.
function _acresOf(l) { return _acresProbe(l.raw); }
function _regionOf(l) { const c = (l.county||"").replace(" County","").trim(); return _WNC.has(c) ? "wnc" : _UPSTATE.has(c) ? "upstate_sc" : null; }
function _catOf(l) {
  const pk = (l.property_kind||"").toLowerCase(), d = (l.description||"").toLowerCase();
  // kw_vacant is the precomputed form of the three description probes below.
  // This is a classification input, not a tooltip: it decides land vs
  // residential, which decides which buyers match. LEAN drops `description`,
  // so without this the phone would silently produce different buyer matches
  // than the desktop for the same lead.
  const kwv = (l.kw_vacant != null || (l.raw && l.raw.kw_vacant != null))
    ? !!(l.kw_vacant != null ? l.kw_vacant : l.raw.kw_vacant)
    : (d.includes("vacant lot") || d.includes("vacant land") || d.includes("vacant parcel"));
  if (["land","lot","vacant","acreage"].some(k=>pk.includes(k)) || kwv) return "land";
  if (pk.includes("multi") || pk.includes("apartment") || (l.raw && l.raw.multifamily_class)) return "multifamily";
  if (["commercial","retail","office","industrial"].some(k=>pk.includes(k))) return "commercial";
  return "residential";
}
function buyersForListing(l) {
  const region = _regionOf(l); if (!region) return {};
  const cat = _catOf(l), county = (l.county||"").replace(" County","").trim(), acres = _acresOf(l);
  let want;
  if (cat === "land") { want = new Set([..._LAND_TYPES, "land_flippers"]); if (_I85.has(county)) want.add("industrial_logistics"); }
  else if (cat === "multifamily") want = _MF_TYPES;
  else if (cat === "commercial") want = _COMM_TYPES;
  else if (cat === "residential") { const t = (l.raw && l.raw.distress_stack || {}).tier; want = (t === "HOT" || t === "WARM") ? new Set(["house_buyers"]) : new Set(); }
  else return {};
  const byType = {};
  BUYER_REGISTRY.forEach((b) => {
    if (!want.has(b.type) || !(b.regions||[]).includes(region)) return;
    if (b.type === "solar_utility_land" && acres != null && acres < 5) return;      // solar wants real acreage
    if (b.min_acres && acres != null && acres < b.min_acres) return;                // Bubba 3-acre floor
    (byType[b.type] = byType[b.type] || []).push(b);
  });
  Object.keys(byType).forEach((t) => { byType[t] = byType[t].slice(0, 4); });
  return byType;
}
function buyerCountForListing(l) { return Object.values(buyersForListing(l)).reduce((n,a)=>n+a.length,0); }

// ---------------------------------------------------------------------------
// "Everything We Found" — completeness backstop.
// The panel above renders ~47 curated blocks, but the pipeline writes ~100 to
// raw. The rest (amount_owed, tenure, life_events, per-county tax detail, ...)
// was collected and then silently dropped on the floor. This renders EVERY raw
// block not already covered, so adding a source can never again mean adding
// data nobody can see.
// ---------------------------------------------------------------------------
const _EV_COVERED = new Set([
  "calc","grade","data_quality","distress_stack","condition_tier","corroboration",
  "link_kind","flood","market_velocity","signal_stack","intent_score","intent_band",
  "gis","zillow","strategy_fit","comp_median_ppsf","owner_mailing","flags","last_sale",
  "geo_imprecise","rod","condition_source","tax_owed","foreclosure_sold_comp_summary",
  "title_risk","equity","owner_phone","stale_case","also_seen_in","relationship_signal",
  "lrcpwa","search_url","estimated_monthly_rent","code_enforcement","courtlistener","epa",
  "skip_trace","upset_bid","bankruptcy","sos_agent","rod_docs","incarceration",
  "owner_mismatch","sc_tax_delinquent","liens","sold_confirmed","fema_repetitive_loss",
  "vision","comps","cama","rent_comps","foreclosure_sold_comps","images","outreach","crm",
]);
// Plumbing, not insight — safe to hide.
const _EV_NOISE = new Set([
  "is_new","link_check","qa_flags","_resolved_deep_enriched","fallback_links",
  "link_may_be_stale","refresh_misses","last_refresh_seen","carryover","pulled_sale",
]);
const _EV_MONEY = /(amount|owed|value|price|bid|balance|tax|debt|rent|cost|due)/i;

function _evLabel(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function _evFmt(k, v) {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number" && _EV_MONEY.test(k) && Math.abs(v) >= 100) {
    return "$" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) {
    if (!v.length) return "";
    return v.map((x) => (x && typeof x === "object" ? _evFmt(k, x) : String(x))).filter(Boolean).join(" · ");
  }
  if (typeof v === "object") {
    const rows = Object.entries(v)
      .filter(([, vv]) => vv !== null && vv !== undefined && vv !== "" && !(Array.isArray(vv) && !vv.length))
      .map(([kk, vv]) => `<span class="ev-sub"><em>${_evLabel(kk)}:</em> ${_evFmt(kk, vv)}</span>`);
    return rows.join(" ");
  }
  const s = String(v);
  return /^https?:\/\//.test(s)
    ? `<a href="${s}" target="_blank" rel="noopener">${s.length > 60 ? s.slice(0, 60) + "…" : s}</a>`
    : s;
}

function renderEverything(l) {
  const raw = (l && l.raw) || {};
  const extra = Object.keys(raw).filter((k) => {
    if (_EV_COVERED.has(k) || _EV_NOISE.has(k)) return false;
    const v = raw[k];
    if (v === null || v === undefined || v === "") return false;
    if (Array.isArray(v) && !v.length) return false;
    if (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length) return false;
    return true;
  }).sort();

  if (!extra.length) { $("d-everything-section").style.display = "none"; return; }
  $("d-everything-section").style.display = "block";
  $("d-everything-count").textContent = `${extra.length} more from ${l.source || "this source"}`;

  // Money/urgency blocks first — those are the ones you act on.
  const hot = extra.filter((k) => _EV_MONEY.test(k) || /delinquent|condemn|divorce|life_event|evict|distress|storm|lien|nod|sold/i.test(k));
  const rest = extra.filter((k) => !hot.includes(k));
  const row = (k) => {
    const body = _evFmt(k, raw[k]);
    return body ? `<div class="ev-row"><div class="ev-key">${_evLabel(k)}</div><div class="ev-val">${body}</div></div>` : "";
  };
  const hotHtml = hot.map(row).join("");
  const restHtml = rest.map(row).join("");
  $("d-everything").innerHTML =
    (hotHtml ? `<div class="ev-hot">${hotHtml}</div>` : "") +
    (restHtml ? `<details class="ev-details"${hotHtml ? "" : " open"}><summary>${rest.length} more detail${rest.length === 1 ? "" : "s"}</summary>${restHtml}</details>` : "");
}

// Precomputed buyer(name) -> matching listing indices, built on first entering the view.
let _BUYER_LISTINGS = null;
function buildBuyerListingIndex() {
  _BUYER_LISTINGS = {};
  LISTINGS.forEach((l, i) => {
    if (l.raw && l.raw.sold_confirmed) return;
    const bt = buyersForListing(l);
    Object.values(bt).flat().forEach((b) => { (_BUYER_LISTINGS[b.name] = _BUYER_LISTINGS[b.name] || []).push(i); });
  });
}

let BUYERS_MODE = false;
function enterBuyersMode() {
  BUYERS_MODE = true;
  ["stats", "filters"].forEach((c) => { const el = document.querySelector("." + c); if (el) el.style.display = "none"; });
  const main = document.querySelector("main"); if (main) main.style.display = "none";
  let bv = document.getElementById("buyers-view");
  bv.classList.remove("hidden");
  if (!_BUYER_LISTINGS) buildBuyerListingIndex();
  renderBuyersView();
}
function exitBuyersMode() {
  BUYERS_MODE = false;
  ["stats", "filters"].forEach((c) => { const el = document.querySelector("." + c); if (el) el.style.display = ""; });
  const main = document.querySelector("main"); if (main) main.style.display = "";
  const bv = document.getElementById("buyers-view"); if (bv) bv.classList.add("hidden");
}
function renderBuyersView(typeFilter) {
  const bv = document.getElementById("buyers-view");
  const byType = {};
  BUYER_REGISTRY.forEach((b) => { (byType[b.type] = byType[b.type] || []).push(b); });
  const types = Object.keys(byType).sort((a,b)=>byType[b].length-byType[a].length);
  const pills = `<div class="buyer-type-pills"><span class="btype-pill ${!typeFilter?'active':''}" data-bt="">All types (${BUYER_REGISTRY.length})</span>` +
    types.map((t)=>`<span class="btype-pill ${typeFilter===t?'active':''}" data-bt="${t}">${BUYER_TYPE_LABEL[t]||t} (${byType[t].length})</span>`).join("") + `</div>`;
  const shown = typeFilter ? { [typeFilter]: byType[typeFilter] } : byType;
  let html = `<div class="buyers-head"><h2>🏢 Land Buyers <span class="muted">— ${BUYER_REGISTRY.length} active buyers · click a buyer to see their criteria + matching parcels</span></h2>${pills}</div><div class="buyer-cards">`;
  Object.keys(shown).forEach((t) => {
    (shown[t]||[]).forEach((b) => {
      const n = (_BUYER_LISTINGS[b.name] || []).length;
      html += `<div class="buyer-card" data-buyer="${encodeURIComponent(b.name)}">
        <div class="bc-type">${BUYER_TYPE_LABEL[t]||t}</div>
        <div class="bc-name">${b.name}</div>
        <div class="bc-geo">${b.geo||""}</div>
        <div class="bc-match">${n} matching parcel${n===1?"":"s"} →</div>
      </div>`;
    });
  });
  html += `</div>`;
  bv.innerHTML = html;
  bv.querySelectorAll(".btype-pill").forEach((p)=>p.addEventListener("click",()=>renderBuyersView(p.dataset.bt||null)));
  bv.querySelectorAll(".buyer-card").forEach((c)=>c.addEventListener("click",()=>openBuyer(decodeURIComponent(c.dataset.buyer))));
}
function openBuyer(name) {
  const b = BUYER_REGISTRY.find((x)=>x.name===name); if (!b) return;
  const idxs = _BUYER_LISTINGS[name] || [];
  const bv = document.getElementById("buyers-view");
  let html = `<div class="buyers-head"><button class="buyer-back">← All buyers</button>
    <h2>${b.name}</h2><div class="bc-type">${BUYER_TYPE_LABEL[b.type]||b.type}</div>
    <div class="buyer-crit"><div><strong>Wants:</strong> ${b.buys||"—"}</div>
      <div><strong>Where:</strong> ${b.geo||"—"}</div>
      <div><strong>Contact:</strong> ${b.contact ? (/^https?:/.test(b.contact) ? `<a href="${b.contact}" target="_blank" rel="noopener">${b.contact} ↗</a>` : b.contact) : "—"}</div></div>
    <h3 style="margin-top:14px">${idxs.length} matching parcel${idxs.length===1?"":"s"} on the board</h3></div>
    <div class="buyer-match-grid">`;
  idxs.slice(0, 300).forEach((i) => {
    const l = LISTINGS[i];
    const addr = [l.street_address, l.city].filter(Boolean).join(", ") || `${l.county} County parcel ${l.parcel_id||""}`;
    const g = getGrade(l);
    const owed = l.raw && l.raw.tax_owed && l.raw.tax_owed.balance;
    html += `<div class="bm-card" data-li="${i}">
      <div class="bm-addr">${addr}</div>
      <div class="bm-meta">${l.county} ${l.state}${g&&g.overall?` · ${g.overall}`:""}${owed?` · $${Math.round(owed).toLocaleString()} owed`:""}${l.owner_name?` · ${l.owner_name}`:""}</div>
    </div>`;
  });
  html += `</div>`;
  bv.innerHTML = html;
  bv.querySelector(".buyer-back").addEventListener("click", ()=>renderBuyersView());
  bv.querySelectorAll(".bm-card").forEach((c)=>c.addEventListener("click",()=>openDetail(LISTINGS[parseInt(c.dataset.li)])));
}

let _CARDS_WIRED = false;
function renderCards() {
  const grid = $("cards-grid");
  if (!_CARDS_WIRED) {
    _CARDS_WIRED = true;
    grid.addEventListener("click", (e) => {
      const card = e.target && e.target.closest ? e.target.closest(".card") : null;
      if (card && card.dataset.id !== undefined) openDetail(filtered[parseInt(card.dataset.id)]);
    });
  }
  grid.innerHTML = filtered
    .slice(0, LEAN ? 40 : 200)
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
      // (0) List-stacking — "🔥 N signals" when 2+ distinct distress signals hit
      //     this property (enrichment_lead_signals). The single loudest lead tell.
      const sscChip = signalStackChip(l);
      if (sscChip) signalChips.push(sscChip);
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
      const lrc = (l.raw && l.raw.lrcpwa) || {};
      // lrcpwa.mail_state is the flattened form of lrcpwa.mailing.state. Today's
      // board carries only the nested one (verified: 0 of 3,062 lrcpwa blocks
      // have mail_state), so reading the flat key first is a no-op on desktop
      // and is what the LEAN projection and the future slim payload emit.
      const lrcState = lrc.mail_state || (lrc.mailing && lrc.mailing.state) || "";
      if (om.absentee || lrc.absentee) signalChips.push(`<span class="distress-chip absentee">absentee</span>`);
      if (om.out_of_state || (lrcState && lrcState !== "NC")) signalChips.push(`<span class="distress-chip absentee">out-of-state</span>`);
      // (3b) Entity-owned lead with a free NC SOS contact (registered agent /
      //      officer) — no paid skip-trace needed to reach the owner.
      const sa = (l.raw && l.raw.sos_agent) || {};
      if (sa.sosid && sa.best_contact_name) {
        signalChips.push(`<span class="distress-chip" style="color:#0a7d3a;border-color:#0a7d3a" title="NC SOS: ${sa.best_contact_name}${sa.best_contact_address ? " — " + sa.best_contact_address : ""}">📇 SOS contact</span>`);
      }
      // (3c) Hurricane-Helene damage — show the ATC-45 placard severity so a
      //      red-tagged / multi-building lead reads at a glance.
      const hel = heleneInfo(l);
      if (hel) {
        const sev = hel.placard === "Unsafe" ? "#c0392b" : "#b8860b";
        const bld = hel.buildings > 1 ? ` ×${hel.buildings} bldgs` : "";
        signalChips.push(`<span class="distress-chip" style="color:#fff;background:${sev};border-color:${sev}" title="Hurricane Helene ATC-45 placard${hel.pct ? " — " + hel.pct + "% damage" : ""}${hel.buildings > 1 ? " across " + hel.buildings + " structures" : ""}">🌀 Helene: ${hel.placard}${hel.pct ? " " + hel.pct + "%" : ""}${bld}</span>`);
      }
      // (4) Title-risk trap — senior lien may survive a junior foreclosure.
      const tr = (l.raw && l.raw.title_risk) || null;
      if (tr && tr.surviving_senior_debt_risk === true) {
        signalChips.push(`<span class="distress-chip" style="color:#fff;background:var(--danger);border-color:var(--danger)" title="Junior-lien foreclosure: a senior lien likely survives the sale. Bidding trap.">⚠ senior lien may survive</span>`);
      }
      // (5) Corroboration — is the distress court-confirmed, or only flagged by a
      //     single MLS/aggregator? Green = court-confirmed; amber = single-source
      //     aggregator (unconfirmed); nothing otherwise.
      const corr = (l.raw && l.raw.corroboration) || null;
      if (corr && corr.court_confirmed) {
        signalChips.push(`<span class="distress-chip" style="color:#fff;background:#0a7d3a;border-color:#0a7d3a" title="Confirmed by a court/authoritative filing: ${(corr.sources || []).join(", ")}">✅ ${corr.label}</span>`);
      } else if (corr && corr.tier === "aggregator" && !corr.multi_source) {
        signalChips.push(`<span class="distress-chip" style="color:#7c5e10;background:#fde68a;border-color:#f5cf6a" title="Only flagged by a single MLS/aggregator — not confirmed by any court/authoritative filing">⚠️ Single-source · ${l.source}</span>`);
      }
      const signalChipsHtml = signalChips.length
        ? `<div class="distress-chips">${signalChips.join("")}</div>` : "";
      return `
      <div class="card" data-id="${i}">
        ${g ? `<div class="card-grade-corner">${gradeBadge(g)}${intentBadge(l)}</div>` : (getIntent(l) ? `<div class="card-grade-corner">${intentBadge(l)}</div>` : "")}
        ${ds && distressLabel[ds.tier] ? `<div class="card-distress-corner">${distressBadge(ds)}</div>` : ""}
        ${photo}
        <div class="card-body">
          <div class="card-addr">${cardAddr}</div>
          <div class="card-loc">${cardLoc}</div>
          ${distressChips(ds)}
          ${signalChipsHtml}
          ${strategyBuyerChips(l)}
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
}

// ------------- Map ------------------------------------------------------------
// Desktop keeps every marker. LEAN caps them: at zoom 7 you cannot visually
// distinguish 1,500 dots from 36,364, and 36,364 of anything is a jetsam.
const MAP_CAP = LEAN ? 1500 : Infinity;

/** Marker tooltip HTML — identical text to what bindTooltip used to be given. */
function markerTip(l) {
  const g = getGrade(l) || {};
  const c = getCalc(l) || {};
  return `<strong>${g.overall || "—"}</strong> · ${l.street_address || ""}<br>` +
    `Bid: ${fmtMoney(l.opening_bid) || "(no bid)"}<br>` +
    `${c.roi_pct != null ? `ROI: ${c.roi_pct.toFixed(1)}%` : ""}`;
}

function initMap() {
  if (!map) {
    // preferCanvas: the default SVG renderer built one <path> element per
    // marker — 36,364 DOM nodes in a single synchronous loop. Canvas is
    // visually identical for circleMarkers and costs no DOM at all.
    map = L.map("map", { preferCanvas: true }).setView([35.0, -82.0], 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 19,
    }).addTo(map);
  } else {
    map.invalidateSize();
  }
  if (mapMarkers) map.removeLayer(mapMarkers);
  // featureGroup, NOT layerGroup: only FeatureGroup calls addEventParent on its
  // children, and event propagation to the group is the whole point here. With
  // a plain layerGroup the delegated handlers below would never fire and
  // click-to-open would silently die on desktop too.
  mapMarkers = L.featureGroup();
  let plotted = 0, eligible = 0;
  filtered.forEach((l) => {
    if (!l.latitude || !l.longitude) return;
    eligible++;
    if (plotted >= MAP_CAP) return;
    plotted++;
    const g = getGrade(l) || {};
    const color = g.overall === "A" ? "#1a7f37" : g.overall === "B" ? "#5b8d3a" : g.overall === "C" ? "#b8860b" : g.overall === "D" ? "#b8540c" : "#b22a2a";
    const m = L.circleMarker([l.latitude, l.longitude], {
      radius: 8,
      color: color,
      fillColor: color,
      fillOpacity: 0.7,
      weight: 2,
    });
    // The listing rides on the marker instead of in a closure. bindTooltip is
    // gone from this loop: it used to construct 36,364 L.Tooltip instances up
    // front, for the one the pointer is actually over.
    m._fcListing = l;
    mapMarkers.addLayer(m);
  });
  mapMarkers.on("mouseover", (e) => {
    const layer = e.propagatedFrom || e.layer;
    if (!layer || !layer._fcListing || layer.getTooltip()) return;
    layer.bindTooltip(markerTip(layer._fcListing));
    layer.openTooltip();
  });
  mapMarkers.on("click", (e) => {
    const layer = e.propagatedFrom || e.layer;
    if (layer && layer._fcListing) openDetail(layer._fcListing);
  });
  mapMarkers.addTo(map);

  const note = $("map-cap-note");
  if (plotted < eligible) {
    const html = `Showing the first ${plotted.toLocaleString()} of ${eligible.toLocaleString()} mapped listings — filter down, or open on desktop for all of them.`;
    if (note) note.innerHTML = html;
    else {
      const host = $("view-map");
      if (host) host.insertAdjacentHTML("afterbegin",
        `<div id="map-cap-note" style="padding:7px 10px;font:500 12px/1.35 system-ui,-apple-system,sans-serif;` +
        `background:var(--surface-2,#f2efe9);color:var(--muted,#6b6257)">${html}</div>`);
    }
  } else if (note) {
    note.remove();
  }
}

// ------------- Detail panel ---------------------------------------------------
// Lazy detail load: the heavy comps/vision raw keys live in an index-aligned
// listings_detail.json (split out of listings.json to speed initial parse).
// Fetched once on the first card open, merged into LISTINGS in place (same
// object refs as `filtered`, so re-opens are instant). Foreclosure board only;
// degrades gracefully (empty panels) if the file is missing or length-mismatched.
//
// LEAN skips this entirely. listings_detail.json inflates to 70.8 MB and then
// Object.assigns every sub-object permanently into LISTINGS[i].raw, so the heap
// never comes back down: on a phone that survived boot, the first tap on a row
// was what finished it. Until the detail shards land, mobile shows an
// "open on desktop" note in place of comps / vision / CAMA (see openDetail).
const _DETAILS_MERGED = {};
async function ensureDetails() {
  if (LEAN) return;
  if (DATASET !== "foreclosure" || _DETAILS_MERGED[DATASET]) return;
  _DETAILS_MERGED[DATASET] = true; // set first so concurrent opens don't double-fetch
  try {
    const details = await fetchJsonMaybeGz("listings_detail.json", (META && META.run_time) || "");
    if (Array.isArray(details) && details.length === LISTINGS.length) {
      for (let i = 0; i < LISTINGS.length; i++) {
        const d = details[i];
        if (d && Object.keys(d).length) LISTINGS[i].raw = Object.assign(LISTINGS[i].raw || {}, d);
      }
    }
  } catch (e) { /* detail panels degrade gracefully */ }
}

async function openDetail(l) {
  if (!l) return;
  await ensureDetails();
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

  // Strategy fit — which exit strategies this lead fits, + why
  const _sf = (l.raw && l.raw.strategy_fit) || null;
  if (_sf && _sf.tags && _sf.tags.length) {
    $("d-strategy-section").style.display = "block";
    $("d-strategy").innerHTML = _sf.tags.map((t) => {
      const m = STRATEGY_META[t] || { label: t, cls: "" };
      return `<div class="strat-row"><span class="strat-chip ${m.cls}">${m.label}</span><span class="strat-why">${(_sf.reasons && _sf.reasons[t]) || ""}</span></div>`;
    }).join("");
  } else { $("d-strategy-section").style.display = "none"; }

  // Buyers wanting this — computed from the registry (region + property category)
  const _bt = buyersForListing(l);
  const _bcount = Object.values(_bt).reduce((n, a) => n + a.length, 0);
  if (_bcount) {
    $("d-buyers-section").style.display = "block";
    // Collapsed by default and names-only: this registry is the SAME on every
    // property, so expanding its prose on each card buried the property-specific
    // findings. The full blurbs live in the Land Buyers tab (and in each row's tooltip).
    const _names = Object.entries(_bt).map(([type, buyers]) => {
      const rows = buyers.map((b) => {
        const isUrl = b.contact && /^https?:\/\//.test(b.contact);
        const t = b.buys ? ` title="${String(b.buys).replace(/"/g, "&quot;")}"` : "";
        return isUrl
          ? `<a href="${b.contact}" target="_blank" rel="noopener"${t}>${b.name} ↗</a>`
          : `<span class="buyer-name"${t}>${b.name}</span>`;
      }).join(" · ");
      return `<div class="buyer-row"><span class="buyer-group-title">${BUYER_TYPE_LABEL[type] || type}</span> ${rows}</div>`;
    }).join("");
    $("d-buyers").innerHTML =
      `<details class="ev-details"><summary>${_bcount} matching buyers — hover a name for what they buy, full detail in the <strong>Land Buyers</strong> tab</summary>${_names}</details>`;
  } else { $("d-buyers-section").style.display = "none"; }

  renderEverything(l);

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
      // On a phone this is a locator, not a map you work in: it is a 240 px band
      // mid-scroll inside the detail panel and every one of its gestures was
      // swallowing the thumb-swipe that should scroll the panel.
      //
      // On a desktop there is no thumb-swipe to protect, and panning around a
      // parcel to see what is next to it is real work. Locking it there was an
      // unintended regression (caught in verification 2026-08-10: the +/- zoom
      // controls disappeared for desktop users too). Gate it.
      detailMap = L.map("d-map", LEAN ? {
        dragging: false, touchZoom: false, scrollWheelZoom: false,
        doubleClickZoom: false, boxZoom: false, zoomControl: false, keyboard: false,
      } : {}).setView([l.latitude, l.longitude], 15);
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
  } else if (LEAN) {
    // Be honest about WHY it is empty rather than hiding the section and
    // letting it read as "no comps exist for this property".
    $("d-comps-section").style.display = "block";
    $("d-comps").innerHTML =
      `<div class="muted" style="font-size:.9em">Open this lead on a desktop for comps, photo analysis and CAMA. ` +
      `They are held in a separate 70 MB file that will not fit in a phone browser.</div>`;
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

  // Corroboration — court-confirmed (green) vs single-source aggregator (amber).
  const corr = (l.raw && l.raw.corroboration) || null;
  if (corr && corr.court_confirmed) {
    badges.push(`<span class="qbadge pos" title="Confirmed by a court/authoritative filing: ${(corr.sources || []).join(", ")}">✅ ${corr.label}</span>`);
  } else if (corr && corr.tier === "aggregator" && !corr.multi_source) {
    badges.push(`<span class="qbadge warn" title="Only flagged by a single MLS/aggregator — not confirmed by any court/authoritative filing">⚠️ Single-source · ${l.source}</span>`);
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

  // Owner & Contact (mailing addr + absentee + any free/paid skip-trace +
  // NC SOS registered agent / officers = free contact for entity-owned leads)
  const _om = (l.raw && l.raw.owner_mailing) || {};
  const _st = (l.raw && l.raw.skip_trace) || {};
  const _sa = (l.raw && l.raw.sos_agent) || {};
  const _saRows = [];
  if (_sa.sosid) {
    if (_sa.best_contact_name)
      _saRows.push(["Entity contact (SOS)",
        _sa.best_contact_name + (_sa.best_contact_address ? " — " + _sa.best_contact_address : "")]);
    if (_sa.registered_agent)
      _saRows.push(["Registered agent",
        _sa.registered_agent + (_sa.agent_is_service ? " (agent service — use officers/principal)" : "")]);
    if (_sa.officers && _sa.officers.length)
      _saRows.push(["Officers", _sa.officers.map((o) =>
        `${o.title}: ${o.name}${o.address ? " (" + o.address + ")" : ""}`).join("; ")]);
    if (_sa.principal_office_address) _saRows.push(["Principal office (SOS)", _sa.principal_office_address]);
    if (_sa.status) _saRows.push(["SOS status", _sa.status]);
  }
  // raw.owner_phone is where EVERY phone actually lives (voter file, county-published
  // parcel tables, skip trace). It drives the "has phone" filter and the CSV export, and
  // it is listed in _EV_COVERED as already-rendered — but this block used to read only
  // raw.skip_trace.phone, so no phone was visible in the detail card at all. That hid
  // 3,840 voter numbers before the county-phone lane added ~2,100 more.
  const _op = (l.raw && l.raw.owner_phone) || {};
  const _phone = _op.phone
    ? `${_op.phone} (${_op.source || "unknown source"}${_op.line_type && _op.line_type !== "unknown" ? ", " + _op.line_type : ""}${_op.needs_dnc_scrub ? " — DNC scrub required" : ""})`
    : _st.phone;
  const _alts = (_op.alternates || []).map((a) => a && a.phone ? `${a.phone} (${a.source || "?"})` : null).filter(Boolean);
  setSec("d-contact-section", "d-contact", [
    ["Owner", _om.owner], ["Mailing address", _om.mailing],
    ["Absentee owner", _om.absentee], ["Out of state", _om.out_of_state],
    ["Phone", _phone], ["Other numbers", _alts.join(" · ")], ["Email", _st.email],
  ].concat(_saRows));

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

  renderCrm(l);

  $("detail-panel").classList.remove("hidden");
}

// ------------- CRM-lite (per-lead status + notes + next action) --------------
// A static-site CRM: state lives in the operator's own browser (localStorage),
// keyed to a stable per-lead id (case_number > parcel_id > source_url) so the
// same property re-opens with its saved status/notes across sessions and across
// nightly board rebuilds. No backend, no PII leaves the machine.
const CRM_STORE_KEY = "fc_crm_v1";
const CRM_STATUSES = ["New", "Contacted", "Appointment", "Dead"];

function crmKey(l) {
  if (!l) return null;
  if (l.case_number) return "case:" + l.case_number;
  if (l.parcel_id) return "parcel:" + `${l.state || ""}:${l.parcel_id}`;
  if (l.source_url) return "url:" + l.source_url;
  return null;
}
function crmLoadAll() {
  try { return JSON.parse(localStorage.getItem(CRM_STORE_KEY)) || {}; }
  catch (e) { return {}; }
}
function crmSaveAll(all) {
  try { localStorage.setItem(CRM_STORE_KEY, JSON.stringify(all)); return true; }
  catch (e) { return false; }
}
function crmGet(key) { return (key && crmLoadAll()[key]) || null; }
function crmSet(key, patch) {
  if (!key) return null;
  const all = crmLoadAll();
  const rec = Object.assign({}, all[key], patch, { updated: new Date().toISOString() });
  all[key] = rec;
  crmSaveAll(all);
  return rec;
}

let _crmKey = null;  // key of the lead the panel is currently showing
function renderCrm(l) {
  const sec = $("d-crm-section");
  if (!sec) return;
  _crmKey = crmKey(l);
  const rec = crmGet(_crmKey) || {};
  // Reflect saved status onto the buttons.
  document.querySelectorAll("#d-crm-status .crm-status-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.status === rec.status);
  });
  const dateEl = $("d-crm-date"); if (dateEl) dateEl.value = rec.next_action || "";
  const notesEl = $("d-crm-notes"); if (notesEl) notesEl.value = rec.notes || "";
  crmShowSaved(rec.updated);
}
function crmShowSaved(ts) {
  const el = $("d-crm-saved");
  if (!el) return;
  el.textContent = ts ? `saved ${fmtDate(ts)}` : "";
}
// Wire the CRM controls once (delegated). Persists on every change.
function initCrm() {
  const statusRow = $("d-crm-status");
  if (statusRow) {
    statusRow.querySelectorAll(".crm-status-btn").forEach((b) =>
      b.addEventListener("click", () => {
        if (!_crmKey) return;
        // Toggle off if the same status is clicked again.
        const cur = (crmGet(_crmKey) || {}).status;
        const next = cur === b.dataset.status ? "" : b.dataset.status;
        const rec = crmSet(_crmKey, { status: next });
        document.querySelectorAll("#d-crm-status .crm-status-btn").forEach((x) =>
          x.classList.toggle("active", x.dataset.status === next));
        crmShowSaved(rec.updated);
      }),
    );
  }
  const dateEl = $("d-crm-date");
  if (dateEl) dateEl.addEventListener("change", () => {
    if (!_crmKey) return;
    crmShowSaved(crmSet(_crmKey, { next_action: dateEl.value }).updated);
  });
  const notesEl = $("d-crm-notes");
  if (notesEl) {
    let t = null;
    notesEl.addEventListener("input", () => {
      if (!_crmKey) return;
      clearTimeout(t);  // debounce so we don't thrash localStorage per keystroke
      t = setTimeout(() => crmShowSaved(crmSet(_crmKey, { notes: notesEl.value }).updated), 400);
    });
  }
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
    // This used to end with `...l`, spreading all 43 top-level keys of every
    // listing into a throwaway object 38,497 times to read 21 of them. The
    // spread came LAST, so wherever a column name collided with a listing key
    // the listing value won — reading those 21 fields explicitly here preserves
    // that precedence exactly. Removing the spread without preserving it would
    // have quietly changed 21 columns. Verified byte-for-byte by
    // scratchpad/b/harness.mjs over the real board.
    const row = {
      grade_overall: g.overall,
      arv_expected: c.arv_expected, rehab_expected: c.rehab_expected,
      max_bid_70: c.max_bid_70, roi_pct: c.roi_pct, cash_on_cash_pct: c.cash_on_cash_pct,
      // contact + signal block
      distress_tier: ds.tier || "", distress_score: ds.score != null ? ds.score : "",
      contactable: ds.contactable ? "yes" : "",
      owner_mailing: om.mailing || "", mail_state: om.mail_state || "",
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
      // the 21 columns the `...l` spread used to supply, in its precedence
      owner_name: l.owner_name, sale_date: l.sale_date, state: l.state, county: l.county,
      street_address: l.street_address, city: l.city, zip_code: l.zip_code,
      listing_type: l.listing_type, opening_bid: l.opening_bid,
      bedrooms: l.bedrooms, bathrooms: l.bathrooms, living_sqft: l.living_sqft,
      year_built: l.year_built, acreage: l.acreage, zoning: l.zoning,
      case_number: l.case_number, plaintiff: l.plaintiff, defendant: l.defendant,
      trustee: l.trustee, source: l.source, source_url: l.source_url,
    };
    // Leading "\n" rather than a trailing one so the concatenation of `rows` is
    // byte-for-byte what rows.join("\n") produced — the join materialised a
    // second ~19 MB string next to the first, and the Blob copied a third.
    rows.push("\n" + cols.map((k) => {
      let v = row[k];
      if (v == null) v = "";
      v = String(v).replace(/"/g, '""');
      return /[",\n]/.test(v) ? `"${v}"` : v;
    }).join(","));
  });
  const blob = new Blob(rows, { type: "text/csv" });
  const a = document.createElement("a");
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = `foreclosure-listings-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  // Never revoked before, so every export pinned its ~19 MB blob for the life
  // of the document.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// ------------- Boot ----------------------------------------------------------
initCrm();  // wire the CRM-lite controls once (static DOM, survives dataset swaps)
loadData();
