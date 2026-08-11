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
  //
  // The `else if (desc)` is what makes this projector a strict fixed point on
  // an already-slim record. A build side that omits kw_vacant when it is false
  // — a reasonable byte-saving choice, and not one we can see from here — would
  // otherwise get `kw_vacant:false` written back onto every such record, so
  // projectRecord(slim) would stop deep-equalling slim. The two are
  // behaviourally identical: _catOf (:1561) treats an absent kw_vacant and a
  // false one the same once `description` is also absent, which on a slim
  // record it always is. On the fat board this changes only the 65 records of
  // 38,500 that carry an empty description, and changes them from false to
  // absent, which _catOf reads identically.
  if (rec.kw_vacant != null) {
    out.kw_vacant = !!rec.kw_vacant;
  } else if (desc) {
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
    // Copy the two keys ONLY where they are actually present. The obvious
    // `{ url: s.url, source: s.source }` invents `source: undefined` on an entry
    // that never carried one — JSON.stringify hides that, a structural
    // comparison does not, and it is the difference between this projector
    // being a fixed point on a slim record and merely looking like one.
    // Board-wide today every entry carries both keys, so this is hardening
    // against a future source, not a fix for a live bug.
    r.also_seen_in = raw.also_seen_in.map((s) => {
      if (!s || typeof s !== "object" || Array.isArray(s)) return s;
      const o = {};
      if ("url" in s) o.url = s.url;
      if ("source" in s) o.source = s.source;
      return o;
    });
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

// ---------------------------------------------------------------------------
// WHICH BOARD FILE EACH CLIENT FETCHES — and why desktop does not get the slim
// one.
//
// Phase 0 shipped `["listings_slim.json.gz", "listings.json.gz"]` for every
// client. That was harmless only because the slim file did not exist. The
// moment it does, that list hands DESKTOP a payload built to a ~25-key
// allowlist — and renderEverything() (:1641) is not a named read, it is a
// reflective sweep over Object.keys(raw). A name-based allowlist cannot
// preserve a reflective reader by construction.
//
// Measured, not assumed. scratchpad/p3/census.mjs streams the real 38,500-record
// docs/listings.json.gz through THIS FILE's own scanner and projector:
//
//   distinct raw.* keys the board carries .............. 107
//   distinct raw.* keys the LEAN allowlist keeps .......  29   (78 dropped)
//   distinct blocks "Everything We Found" renders, fat ..  47
//   ...................................... on the slim ..   2
//   rows it renders board-wide, fat ................ 172,192
//   ................................. on the slim ....  6,167   (-96.4%)
//   records whose section is non-empty, fat ......... 37,791   (98.2%)
//   ................................. on the slim ....  6,146   (16.0%)
//
// 46 blocks vanish outright, and they are not obscure: eviction_market on 80.9%
// of records, amount_owed 59.9%, tenure 43.7%, recorded_comps 18.6%,
// recorded_sales 15.3%, rent_comps_extra 12.1%, condemned, divorce, nc_ecourts,
// assessor_card. That is the completeness backstop the panel exists to be
// (:1595 "adding a source can never again mean adding data nobody can see")
// going quietly blank on the machine that currently works.
//
// So the URL is gated on LEAN. The phone fetches slim; the desktop keeps
// fetching the board it has always fetched. Desktop survives the fat payload
// today at 521 MB and the rule for this whole change is that desktop must not
// move.
//
// Mobile keeps the 404 fallback, so a missing or not-yet-published slim file
// degrades to exactly today's behaviour instead of to an empty board. Desktop
// deliberately has NO slim fallback: falling back onto the lobotomised file is
// the single failure this gate exists to prevent, and a fallback that fires
// only when listings.json.gz is missing would fire precisely when nobody is
// watching.
const BOARD_SLIM_FILE = "listings_slim.json.gz";
const BOARD_FAT_FILE = "listings.json.gz";
const BOARD_FILES = LEAN ? [BOARD_SLIM_FILE, BOARD_FAT_FILE] : [BOARD_FAT_FILE];

// run_meta.json carries a "board" block — {"schema":"slim-v1","count":N} —
// written by the same write_artifact() call that writes the payload, so its
// count is the length of the array that call emitted. It may be absent: it is
// not there today, and two board-writing scripts republish listings.json.gz
// without going through write_artifact at all.
const BOARD_SCHEMA = "slim-v1";

/**
 * The record count the build side declares, or null when it declares nothing
 * we can act on.
 *
 * Deliberately NOT derived from META.total. `total` is a summary statistic
 * assembled from a caller-supplied dict; nothing in the contract says it equals
 * the array length. `board.count` is *defined* as that length. Gating the whole
 * board on `total` would black out the dashboard the first time some run
 * reported a differently-scoped total, which is a worse failure than the one
 * being defended against.
 *
 * An unrecognised schema returns null rather than throwing: a future slim-v2
 * must be able to ship without this file refusing to render.
 */
function boardExpectedCount(board) {
  if (!board || typeof board !== "object" || Array.isArray(board)) return null;
  if (board.schema !== BOARD_SCHEMA) return null;
  const n = board.count;
  if (typeof n !== "number" || !isFinite(n) || n <= 0 || Math.floor(n) !== n) return null;
  return n;
}
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
 * `board` is run_meta.json's "board" block, or null when it has none.
 */
async function loadBoardStreaming(bust, onProgress, board) {
  const ac = new AbortController();
  const q = `?t=${encodeURIComponent(bust)}`;
  let res = null;
  let usedName = "";
  for (const name of BOARD_FILES) {
    let r = null;
    try { r = await fetch(name + q, { signal: ac.signal }); } catch (e) { r = null; }
    if (r && r.ok && r.body) { res = r; usedName = name; break; }
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

    // Do not re-derive what the build side already derived.
    //
    // The projector is a proven fixed point on a SLIM-V1 record — 945 real
    // stratified board records rebuilt as slim by an independent Python
    // implementation of the contract, across six plausible build-side
    // serialisation choices, every one an exact structural fixed point
    // (scratchpad/p3/test_idempotent.mjs). So running it over the slim file
    // cannot change a single value; it can only rebuild 38,500 objects for
    // nothing, on the device with the least memory to spare.
    //
    // But skip it only on a POSITIVE handshake: we fetched the slim file AND
    // run_meta declares schema "slim-v1". Absent block, unknown schema, or a
    // fallback to the fat file all mean project — the projector is also what
    // re-derives kw_vacant / acres / lrcpwa.mail_state / life_events when the
    // payload drifts from the contract, and that self-healing is worth more
    // than the CPU whenever we are not certain what we are holding.
    let project = LEAN;
    if (project && usedName === BOARD_SLIM_FILE && boardExpectedCount(board) !== null) {
      project = false;
    }
    let onElement;
    if (project) {
      onElement = (s) => { out.push(projectRecord(JSON.parse(s), true)); };
    } else if (!LEAN) {
      onElement = (s) => { out.push(JSON.parse(s)); };   // FULL: identity, as before
    } else {
      // One conformance check, on record 0 only. A payload still carrying
      // `description` or `raw.images` is not SLIM-V1 whatever run_meta says —
      // the realistic cause is run_meta.json publishing ahead of the payload —
      // and handing a phone unprojected fat records is the exact crash this
      // whole change exists to prevent. Cost: two `in` tests, once.
      let verified = false;
      onElement = (s) => {
        const rec = JSON.parse(s);
        if (!verified) {
          verified = true;
          if (rec && typeof rec === "object" && !Array.isArray(rec)
              && ("description" in rec || (rec.raw && typeof rec.raw === "object" && "images" in rec.raw))) {
            project = true;
          }
        }
        out.push(project ? projectRecord(rec, true) : rec);
      };
    }

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
    // Same reasoning, one level up. The document can be perfectly well-formed
    // and still be SHORT — Pages serving a payload from one publish alongside a
    // run_meta.json from another is the ordinary way that happens. A short board
    // is the dangerous shape precisely because it renders beautifully: it just
    // quietly omits leads, and the omitted lead is the one with the sale on
    // Thursday. Enforced only when the build side declares a count under a
    // schema we recognise; see boardExpectedCount.
    const want = boardExpectedCount(board);
    if (want !== null && out.length !== want) throw new Error(`BOARD_COUNT:${out.length}:${want}`);
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
      // The board block is the build side's own statement about the payload it
      // just wrote. Absent on every publish before phase 3, and absent again
      // after any run of patch_distress_score.py / patch_owner_mailing.py, both
      // of which rewrite listings.json.gz without going through write_artifact.
      // Everything downstream treats it as optional.
      const board = (META && META.board) || null;
      const declared = boardExpectedCount(board);
      const total = declared || Number(META.total) || 0;
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
        LISTINGS = await loadBoardStreaming(bust, onProgress, board);
      } catch (streamErr) {
        const em = String(streamErr && streamErr.message);
        // A machine with the headroom for the old path should show a board
        // rather than an error if the new one fails. LEAN deliberately does
        // NOT fall back: the old path on a phone IS the crash we are fixing.
        //
        // A count mismatch is NOT eligible for that fallback. This fallback
        // exists to protect desktop from a bug in THIS loader; it must not be
        // used to launder a bad payload. The old path would happily JSON.parse
        // the same well-formed, short array and render it without a word, which
        // is the exact outcome the count gate was added to make impossible.
        if (LEAN || em === "NO_DECOMPRESSION" || em.indexOf("BOARD_COUNT:") === 0) throw streamErr;
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
      const em = String((e && e.message) || "");
      let msg;
      if (em === "NO_DECOMPRESSION") {
        msg = "This board needs iOS 16.4 or newer (or a current desktop browser) to open.";
      } else if (em.indexOf("BOARD_COUNT:") === 0) {
        // Deliberately refusing to render. A short board looks completely
        // normal and the lead it drops is the one with a sale date on it, so
        // "show what we got" is the wrong default here. Publishes are not
        // atomic on Pages, so a reload a few minutes later is the actual fix.
        const p = em.split(":");
        msg = `Board is mid-publish — got ${Number(p[1]).toLocaleString()} listings, expected ${Number(p[2]).toLocaleString()}. `
          + "Showing nothing rather than a partial board with missing sale dates. Reload in a few minutes.";
      } else {
        msg = "Could not load listings — first run hasn't finished yet, or network error. Reload in a few minutes.";
      }
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

// ===========================================================================
// ARV TRUST — one place decides whether a published valuation can be believed,
// and the answer is rendered where the user actually looks.
//
// WHY THIS IS HERE. The reported bug was "a trailer on a half acre will say
// 700k". It was found by eye, scanning the TABLE. The table is the one surface
// that carried no caveat at all: `<td class="num">${fmtMoney(c.arv_expected)}</td>`,
// a bare number, at every confidence level. The "(proxy)" suffix existed only on
// the card chip and the detail badge, and only when arv_confidence was "LOW" —
// so every MEDIUM row rendered clean, including the $780,300 one. A warning
// nobody is looking at is not a warning.
//
// ARV is not a display field. max_bid_70, ROI, estimated profit, the letter
// grade and the default sort are all derived from it, so a 10x-inflated ARV
// tells someone a deal is good at an auction where they bid their own money.
// Being wrong here is much worse than being silent.
//
// TWO LEVELS, because they are two different claims:
//
//   "bad"   — something concluded this number is wrong or unverifiable.
//             Loud, and it visibly discounts the money derived from it.
//   "proxy" — no comps / no sqft, so it is an estimate of an estimate. Quiet.
//             It is true of 62% of today's board (23,874 low_arv_confidence and
//             20,447 no_sqft out of 38,500) and a red flag on two rows in three
//             is wallpaper, which is part of how the real one stayed invisible.
//
// HOW A "bad" IS DETECTED, in three independent layers, because the valuation
// work is landing concurrently and this file must be useful before, during and
// after it:
//
//   1. Named flags. The list below covers the names in play. Absent from the
//      board, it costs nothing.
//   2. A shape rule over any flag that mentions ARV and reads as a VERDICT
//      ("above", "outlier", "unverified", "ceiling", …) rather than as a
//      confidence label. So a flag named after this file ships still lands.
//   3. Thresholds the pipeline ALREADY treats as anomalous — grading.py:295
//      withholds the letter grade at ARV > $2M or ROI > 400%. It withholds only
//      the LETTER: arv_expected, max_bid_70 and roi_pct still publish, and the
//      table printed all three clean. This layer needs no board recompute and
//      is live the moment this file deploys.
//
// With none of the flags present the code returns "ok" or "proxy" exactly as
// before, so a board that has not been recomputed renders as it does today
// apart from layer 3.
// ===========================================================================
const _ARV_BAD_FLAGS = {
  // live on the board today
  arv_outlier: 1,
  // QA / data-quality names in play for the valuation fixes
  arv_above_asis: 1, arv_below_asis: 1, arv_vs_assessed_extreme: 1,
  arv_unverified: 1, arv_unreliable: 1, arv_geo_suspect: 1, arv_floored: 1,
  ppsf_ceiling: 1, ppsf_outlier: 1, land_ppa_ceiling: 1,
  type_mismatch: 1, property_type_mismatch: 1, comp_type_mismatch: 1,
  shared_centroid: 1, gis_row_shared: 1, geo_imprecise: 1,
  assessed_is_tax_amount: 1, stale_sale_floor: 1,
};
// A verdict, not a confidence label. Deliberately does NOT match
// "low_arv_confidence", which is layer-2's most important non-hit.
const _ARV_BAD_WORDS = /(above|below|exceed|extreme|outlier|suspect|unverif|unreliab|implausib|ceiling|inflat|mismatch|withheld|suppress|overrid|floor|centroid|fanout|fan_out|shared|stale)/;
const _ARV_PROXY_FLAGS = { low_arv_confidence: 1, no_sqft: 1, sqft_estimated: 1 };

const _ARV_TRUST_OK = { level: "ok", why: [] };

/**
 * `{level: "bad"|"proxy"|"ok", why: [reason, …]}` for one listing.
 *
 * Memoised non-enumerably (the exportCsv `{...l}` spread must never pick this
 * up) and safe to memoise: every input lives in raw.calc / raw.data_quality /
 * raw.grade, none of which is a lazy-detail key, so a shard merge cannot change
 * the answer.
 */
function arvTrust(l) {
  if (!l || typeof l !== "object") return _ARV_TRUST_OK;
  if (l._arvTrust !== undefined) return l._arvTrust;
  const raw = l.raw || {};
  const c = raw.calc || {};
  const why = [];
  let bad = false, proxy = false;

  const consider = (name) => {
    if (typeof name !== "string" || !name) return;
    const n = name.toLowerCase();
    if (_ARV_BAD_FLAGS[n] || (n.indexOf("arv") !== -1 && _ARV_BAD_WORDS.test(n))) {
      bad = true;
      const pretty = n.replace(/_/g, " ");
      if (why.indexOf(pretty) === -1) why.push(pretty);
    } else if (_ARV_PROXY_FLAGS[n]) {
      proxy = true;
    }
  };

  const dq = raw.data_quality;
  if (dq && Array.isArray(dq.flags)) dq.flags.forEach(consider);
  // qa_flags is written by enrichment_board_qa and is not in the slim
  // allowlist, so it is a desktop-only signal today. Read it where it exists
  // rather than requiring it.
  if (Array.isArray(raw.qa_flags)) raw.qa_flags.forEach(consider);
  // calc emits this as `arv_flags`, NOT `flags`. Reading `c.flags` was a dead
  // branch: measured on 12,000 recomputed leads, 3,394 carried a soft flag and
  // 2,660 of them (78.4%) rendered with no warning at all. This is the same
  // reader-writer mismatch that made every phone report "CONFIDENCE: LOW" —
  // when a warning has to be right to keep someone from overbidding, the key
  // name is not a detail. `flags` is kept as a fallback in case a future
  // producer uses it.
  if (Array.isArray(c.arv_flags)) c.arv_flags.forEach(consider);
  if (Array.isArray(c.flags)) c.flags.forEach(consider);
  // Boolean verdicts written straight onto calc — arv_geo_suspect already is one.
  for (const k in c) { if (c[k] === true && k.indexOf("arv") === 0) consider(k); }

  const arv = c.arv_expected;
  // grading.py:295 already refuses to letter-grade these. It withholds the
  // letter only; the number, the max bid and the ROI publish regardless.
  if (typeof arv === "number" && arv > 2000000) {
    bad = true;
    why.push("ARV over $2M — the grader already refuses to rate this as a deal");
  }
  if (typeof c.roi_pct === "number" && c.roi_pct > 400) {
    bad = true;
    why.push("ROI over 400% — implausible, so the ARV behind it is not trustworthy");
  }
  if (!bad && c.arv_confidence === "LOW") proxy = true;

  return _memo(l, "_arvTrust", bad ? { level: "bad", why }
    : proxy ? { level: "proxy", why } : _ARV_TRUST_OK);
}

/** Tooltip text for a flagged ARV. Plain, and it never claims more than it knows. */
function arvTrustTitle(t) {
  if (!t || t.level === "ok") return "";
  if (t.level === "proxy") {
    return "Proxy ARV — estimated without usable comps or a known square footage. "
      + "Treat it as a rough band, not a value.";
  }
  return "ARV flagged as unreliable — do not bid off this number. "
    + (t.why.length ? t.why.join("; ") : "failed a valuation sanity check")
    + ". Max bid and ROI are derived from it and are shown dimmed for the same reason.";
}

/**
 * The ARV cell for the table.
 *
 * Handles the case that matters most once the valuation guards land: an ARV the
 * pipeline WITHHELD. A suppressed number renders as an empty cell today, which
 * reads as "not computed yet" — indistinguishable from a lead nobody has priced.
 * Flagged-and-absent says "unverified" instead.
 */
function arvCell(c, t) {
  const v = c.arv_expected;
  const title = arvTrustTitle(t).replace(/"/g, "&quot;");
  if (t.level === "bad") {
    const body = v ? fmtMoney(v) : "unverified";
    return `<td class="num dq-arv-bad" title="${title}"><span class="dq-arv-mark">&#9888;&#xFE0E;</span>${body}</td>`;
  }
  if (!v) return `<td class="num"></td>`;
  if (t.level === "proxy") {
    return `<td class="num dq-arv-proxy" title="${title}">~${fmtMoney(v)}</td>`;
  }
  return `<td class="num">${fmtMoney(v)}</td>`;
}

/** Money derived from a flagged ARV: shown, dimmed, and labelled as derived. */
function derivedCell(inner, t) {
  if (t.level !== "bad" || !inner) return `<td class="num">${inner}</td>`;
  return `<td class="num dq-dim" title="Derived from an ARV flagged as unreliable">${inner}</td>`;
}

// One-time stylesheet for the treatments this file introduces. Injected from
// here rather than added to style.css / premium.css because those files belong
// to another owner in this change and a split definition is how a warning ends
// up half-deployed. Everything is scoped to its own class names.
let _DASH_STYLES_DONE = false;
function injectDashStyles() {
  if (_DASH_STYLES_DONE || typeof document === "undefined") return;
  _DASH_STYLES_DONE = true;
  // #listings-table wins the specificity fight with premium.css's own
  // `#listings-table td.num` colour rule — verified in the browser, the plain
  // `td.dq-arv-bad` selector lost and the warning rendered in the default text
  // colour. Both themes are set explicitly: index.html drives the theme off a
  // data-theme attribute, never off prefers-color-scheme.
  const css = `
  :root{--dq-warn:#a8200f;--dq-warn-bg:rgba(217,45,32,.11)}
  :root[data-theme="dark"]{--dq-warn:#ff8a7a;--dq-warn-bg:rgba(217,45,32,.22)}
  #listings-table td.dq-arv-bad{background:var(--dq-warn-bg);color:var(--dq-warn);font-weight:700}
  #listings-table td.dq-arv-bad .dq-arv-mark{margin-right:4px;font-weight:700}
  #listings-table td.dq-arv-proxy{color:var(--muted,#6b6257)}
  #listings-table td.dq-dim{opacity:.42}
  #listings-table td.dq-dim .roi-pos,#listings-table td.dq-dim .roi-neg{color:inherit}
  .dq-warn-mark{color:var(--dq-warn);font-weight:700}
  /* .val.big carries its own colour at a higher specificity than a bare class. */
  #detail-panel .val.dq-warn-mark{color:var(--dq-warn)}
  .arv-flag-chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;
    font-weight:700;color:#fff;background:#c0392b;border:1px solid #c0392b}
  .arv-flag-note{margin-top:6px;padding:8px 10px;border-radius:8px;font-size:12px;line-height:1.4;
    color:var(--dq-warn);background:var(--dq-warn-bg);border:1px solid rgba(217,45,32,.35)}
  .shard-loading{font-size:.9em;color:var(--muted,#6b6257);position:relative;padding-left:18px}
  .shard-loading::before{content:"";position:absolute;left:0;top:50%;width:11px;height:11px;
    margin-top:-6px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;
    animation:shard-spin .8s linear infinite}
  @keyframes shard-spin{to{transform:rotate(360deg)}}
  @media (prefers-reduced-motion:reduce){.shard-loading::before{animation:none}}
  `;
  const el = document.createElement("style");
  el.id = "dash-inline-styles";
  el.textContent = css;
  document.head.appendChild(el);
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
      const at = arvTrust(l);
      const rowClass = g.overall ? `row-${g.overall}` : "";
      // Bankruptcy listings have no address — show debtor name + chapter so
      // they're identifiable in the table view. Cross-ref hits get a 🏛 prefix.
      const isBkSource = l.source === "national.courtlistener_bankruptcy";
      const cl = isBkSource ? (l.raw && l.raw.courtlistener) || {} : null;
      const bkXref = !isBkSource && l.raw && l.raw.bankruptcy ? l.raw.bankruptcy : null;
      // The flagged-ARV marker rides on the ADDRESS, not only on the ARV cell.
      // Below 720px style.css hides the ARV, Max Bid, Rehab and every other
      // numeric column — verified in the browser: of 17 columns the phone shows
      // grade, date, address, city, opening bid and ROI. A warning that lives
      // only in the ARV cell is therefore invisible on exactly the device this
      // change is for. The address is the one cell that renders in every
      // layout, and it is where the eye lands.
      const arvMark = at.level === "bad"
        ? `<span class="dq-warn-mark" title="${arvTrustTitle(at).replace(/"/g, "&quot;")}">&#9888;&#xFE0E; </span>`
        : "";
      const addrCell = isBkSource
        ? `${arvMark}🏛 ${cl.chapter && cl.chapter !== "?" ? `Ch.${cl.chapter} ` : ""}${(l.defendant || "Bankruptcy filing").slice(0, 60)}`
        : `${arvMark}${bkXref ? "🏛 " : ""}${l.street_address || ""}`;
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
      <td>${(() => { const ds = getDistress(l); return ds && distressLabel[ds.tier] ? `<span class="tier-dot ${distressLabel[ds.tier].cls}" title="${ds.tier} · ${(ds.signals || []).join(', ')}"></span>` : ""; })()}${
        // A WITHHELD grade and a MISSING grade both render as the same dim "—",
        // which reads as "not scored yet". When the ARV is flagged the grade is
        // absent on purpose, so colour it and say so in the tooltip. The loud
        // marker stays on the address cell — one glyph per row, not two.
        (!g.overall && at.level === "bad")
          ? `<span class="grade-badge F dq-warn-mark" style="opacity:.85" title="Unrated on purpose — ${arvTrustTitle(at).replace(/"/g, "&quot;")}">—</span>`
          : gradeBadge(g)
      }${intentBadge(l)}</td>
      <td>${dateCell}</td>
      <td>${l.state || ""}</td>
      <td>${l.county || ""}</td>
      <td>${addrCell}</td>
      <td>${l.city || ""}</td>
      <td>${fmtType(l.listing_type)}</td>
      <td class="num">${fmtMoney(l.opening_bid)}</td>
      ${arvCell(c, at)}
      <td class="num">${fmtMoney(c.rehab_expected)}</td>
      ${derivedCell(fmtMoney(c.max_bid_70), at)}
      ${derivedCell(roiCell(c.roi_pct), at)}
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
      // arvTrust() is the single decision (see :1423). "proxy" keeps the old
      // quiet treatment verbatim; "bad" gets its own chip below and blanks the
      // derived ROI line rather than dimming it, because a dimmed number is
      // still a number someone can read off the card.
      const at = arvTrust(l);
      const lowArv = at.level === "proxy";
      const badArv = at.level === "bad";
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
      // (0b) Flagged valuation — first chip after the signal stack, because
      //      every money figure on this card descends from it.
      if (badArv) {
        signalChips.push(`<span class="arv-flag-chip" title="${arvTrustTitle(at).replace(/"/g, "&quot;")}">&#9888;&#xFE0E; ARV flagged</span>`);
      }
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
            ${c.arv_expected
              ? `<span${badArv ? ` class="dq-warn-mark" title="${arvTrustTitle(at).replace(/"/g, "&quot;")}"` : ""}>ARV ${badArv ? "&#9888;&#xFE0E; " : ""}${fmtMoney(c.arv_expected)}${lowArv ? " (proxy)" : ""}</span>`
              : (badArv ? `<span class="dq-warn-mark" title="${arvTrustTitle(at).replace(/"/g, "&quot;")}">ARV &#9888;&#xFE0E; unverified</span>` : "")}
            ${(l.raw && l.raw.last_sale && l.raw.last_sale.date) ? `<span title="${l.raw.last_sale.basis === "assessor_value" ? "county assessor market value as of the sale date (sale price not published)" : "last recorded sale"}">Sold ${l.raw.last_sale.date.slice(0, 7)}${l.raw.last_sale.amount ? " · " + fmtMoney(l.raw.last_sale.amount) + (l.raw.last_sale.basis === "assessor_value" ? "*" : "") : ""}</span>` : ""}
            ${l.sale_date ? `<span>${fmtDate(l.sale_date)}</span>` : ""}
            ${meta.length ? `<span>${meta.join(" · ")}</span>` : ""}
          </div>
          ${(l.raw && l.raw.also_seen_in && l.raw.also_seen_in.length) ? `<div class="card-sources" style="font-size:11px;opacity:.7;margin-top:2px">also at: ${l.raw.also_seen_in.map((s) => `<a href="${s.url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${(s.source || "source").split(".").pop()}</a>`).join(", ")}</div>` : ""}
          ${roi == null ? "" : badArv
            ? `<div class="card-roi" style="opacity:.5;font-weight:600" title="ROI withheld — it is derived from an ARV flagged as unreliable">ROI — <span style="font-weight:400">unreliable ARV</span></div>`
            : `<div class="card-roi ${roiCls}"${lowArv ? ` style="opacity:.45" title="ROI suppressed — derived from a low-confidence (proxy) ARV"` : ""}>ROI ${roi.toFixed(1)}%${c.cash_on_cash_pct != null ? ` · CoC ${c.cash_on_cash_pct.toFixed(0)}%` : ""}</div>`}
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
// was what finished it. Mobile takes the sharded path below instead — see
// ensureShardFor() — and falls back to the "open on desktop" note only when a
// shard is genuinely unavailable.
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

// ===========================================================================
// PER-LISTING DETAIL SHARDS — the mobile detail panel, completed.
//
// The whole point of the LEAN work was that the phone must never hold the
// board's heavy keys. listings_detail.json is 70.8 MB inflated and ensureDetails
// Object.assigns EVERY one of its 38,500 records permanently into LISTINGS, so
// it can never be the mobile path — which is why the panel has been telling
// people to go find a desktop.
//
// The build side now also emits docs/detail_shards/NNNNN.json.gz: the same
// index-aligned detail array, cut into fixed-size blocks. Opening one lead
// costs one block instead of the whole file.
//
// THREE THINGS THIS CODE IS CAREFUL ABOUT, all of them memory:
//
//  1. It merges ONE record, not the block. The other 999 detail records are
//     parsed (unavoidable — it is one JSON document) and then dropped when the
//     shard falls out of the LRU. Nothing but the opened lead is retained.
//  2. The LRU is 3 shards and eviction is REAL: it deletes the keys it added
//     back off LISTINGS[i].raw. Without that, thumbing through 200 leads would
//     reassemble listings_detail.json inside the heap one record at a time,
//     which is precisely the failure this change exists to prevent. The keys
//     removed are only the ones this code added (recorded at merge time), so an
//     eviction can never strip a field the board itself carried.
//  3. Desktop does not come through here at all. ensureDetails() is untouched
//     and still owns listings_detail.json.
//
// DESKTOP IS UNCHANGED. If a change is visible at 1440px, it is a bug.
// ===========================================================================
const DETAIL_SHARD_DIR = "detail_shards";
// Records per shard. The build side declares it; this is the value to assume
// when it does not, and it is also what the shards are cut at today.
const DETAIL_SHARD_SIZE_DEFAULT = 1000;
// Three, not one: opening a lead, backing out, and opening its neighbour is the
// actual browsing pattern, and neighbours share a shard. Three covers a scroll
// across a shard boundary without ever holding a meaningful fraction of the
// detail file.
const DETAIL_SHARD_LRU = 3;

/**
 * Records per shard, from run_meta.json's "board" block.
 *
 * Read defensively and from several plausible key names. This file ships before
 * the first sharded board is published, the naming is the build side's to
 * choose, and the failure mode of guessing wrong is a 404 on every shard —
 * i.e. the "open on desktop" note, forever, silently. A wrong SIZE is worse
 * than a missing one: it would fetch a real shard and read the wrong record out
 * of it, so every candidate is validated as a positive integer and anything
 * else falls back to the default rather than being coerced.
 */
function detailShardSize(board) {
  const b = (board && typeof board === "object" && !Array.isArray(board)) ? board : {};
  const nested = (b.detail_shards && typeof b.detail_shards === "object") ? b.detail_shards : {};
  const cands = [
    b.detail_shard_size, b.shard_size, b.detail_shard_records,
    nested.size, nested.shard_size, nested.count_per_shard,
  ];
  for (let i = 0; i < cands.length; i++) {
    const n = cands[i];
    if (typeof n === "number" && isFinite(n) && n > 0 && Math.floor(n) === n) return n;
  }
  return DETAIL_SHARD_SIZE_DEFAULT;
}

const _SHARD = {
  size: DETAIL_SHARD_SIZE_DEFAULT,
  sized: false,
  // "start" (00000, 01000, 02000 …) or "index" (00000, 00001, 00002 …). Both
  // are 5-digit and both are reasonable readings of "NNNNN"; shard 0 is
  // spelled identically under either, so the naming is learned from the first
  // shard that actually distinguishes them and latched from then on.
  naming: null,
  lru: [],                 // [{key, start, data:null, applied: Map<listing, string[]>}]
  inflight: Object.create(null),
  // Set once a shard fetch fails in a way that says the directory is not there
  // (as opposed to one bad block). Stops a 404 per tap for the rest of the
  // session; the panel then reads exactly as it did before this change.
  dead: false,
};

let _BI_LIST = null;   // the LISTINGS array _BI was built from
let _BI = null;        // WeakMap<listing, board index>

/**
 * A listing's index in the board — which IS its index in the detail array
 * (web_artifact writes them index-aligned from the same list).
 *
 * Built lazily and only on the LEAN path: it is 38,500 WeakMap entries that a
 * desktop never needs, and a phone only needs after the first tap.
 */
function boardIndexOf(l) {
  if (!l || typeof l !== "object") return -1;
  if (_BI_LIST !== LISTINGS) {
    _BI_LIST = LISTINGS;
    _BI = new WeakMap();
    for (let i = 0; i < LISTINGS.length; i++) {
      const r = LISTINGS[i];
      if (r && typeof r === "object") _BI.set(r, i);
    }
  }
  const v = _BI.get(l);
  return v === undefined ? -1 : v;
}

/** Zero-padded shard filename stem for a naming convention. */
function _shardStem(shardIdx, start, naming) {
  const n = naming === "index" ? shardIdx : start;
  let s = String(n);
  while (s.length < 5) s = "0" + s;
  return s;
}

/**
 * Pull one detail record out of a parsed shard.
 *
 * The shard is expected to be a plain array of `size` records covering
 * [start, start+size). It is read tolerantly anyway — a wrapper object carrying
 * its own `start`, or an index-keyed map — because the alternative to tolerating
 * a shape is silently rendering an empty panel as though the property had no
 * comps, and this panel's whole job is to not do that.
 *
 * Returns undefined when the record cannot be located, which the caller treats
 * as a failed shard, NOT as "this lead has no detail".
 */
function shardRecordAt(shard, start, i, size) {
  if (Array.isArray(shard)) {
    // A block longer than one shard is not the file we asked for — most likely
    // the whole detail array, or a shard cut at a different size than run_meta
    // declares. Reading positionally out of it would merge a DIFFERENT
    // property's comps and photo analysis into this lead and show it as fact.
    // Refuse, and let the caller say "open on desktop".
    if (size > 0 && shard.length > size) return undefined;
    const r = shard[i - start];
    return (r && typeof r === "object") ? r : undefined;
  }
  if (!shard || typeof shard !== "object") return undefined;
  const inner = Array.isArray(shard.records) ? shard.records
    : Array.isArray(shard.items) ? shard.items
    : Array.isArray(shard.detail) ? shard.detail
    : Array.isArray(shard.details) ? shard.details : null;
  if (inner) {
    const s = (typeof shard.start === "number" && isFinite(shard.start)) ? shard.start : start;
    if (size > 0 && inner.length > size) return undefined;
    const r = inner[i - s];
    return (r && typeof r === "object") ? r : undefined;
  }
  const byAbs = shard[String(i)];
  if (byAbs && typeof byAbs === "object") return byAbs;
  const byRel = shard[String(i - start)];
  if (byRel && typeof byRel === "object") return byRel;
  return undefined;
}

/** Most-recently-used last. Evicting un-merges, so the heap actually comes back. */
function _shardTouch(entry) {
  const at = _SHARD.lru.indexOf(entry);
  if (at !== -1) _SHARD.lru.splice(at, 1);
  _SHARD.lru.push(entry);
  while (_SHARD.lru.length > DETAIL_SHARD_LRU) {
    const gone = _SHARD.lru.shift();
    gone.applied.forEach((keys, li) => {
      const raw = li && li.raw;
      if (!raw) return;
      for (let i = 0; i < keys.length; i++) delete raw[keys[i]];
    });
    gone.applied = new Map();
    gone.data = null;
  }
}

function _shardEntry(key) {
  for (let i = 0; i < _SHARD.lru.length; i++) if (_SHARD.lru[i].key === key) return _SHARD.lru[i];
  return null;
}

/**
 * Merge one detail record into one listing, recording exactly which keys were
 * added so eviction can take them back out again.
 *
 * A key the board already carried is left alone: the shard is a derivative and
 * must never be able to overwrite the authoritative payload, and more
 * practically, "put it back how you found it" is only possible for keys we own.
 */
function _shardMerge(li, d, entry) {
  const raw = li.raw || (li.raw = {});
  const added = [];
  for (const k in d) {
    if (!Object.prototype.hasOwnProperty.call(d, k)) continue;
    if (Object.prototype.hasOwnProperty.call(raw, k)) continue;
    raw[k] = d[k];
    added.push(k);
  }
  entry.applied.set(li, added);
}

/**
 * Fetch + merge the detail for ONE listing. Never throws.
 * Returns true when the panel can be rendered as complete.
 */
async function ensureShardFor(l) {
  if (!LEAN || DATASET !== "foreclosure" || _SHARD.dead) return false;
  const i = boardIndexOf(l);
  if (i < 0) return false;

  if (!_SHARD.sized) { _SHARD.size = detailShardSize(META && META.board); _SHARD.sized = true; }
  const size = _SHARD.size;
  const shardIdx = Math.floor(i / size);
  const start = shardIdx * size;
  const key = String(shardIdx);

  const have = _shardEntry(key);
  if (have && have.applied.has(l)) { _shardTouch(have); return true; }

  if (!_SHARD.inflight[key]) {
    _SHARD.inflight[key] = (async () => {
      // Cache-key on run_time, the convention ensureDetails() already uses:
      // shards change only when the board does, and a phone on cell data should
      // not re-download one it already has.
      const bust = (META && META.run_time) || "";
      const namings = _SHARD.naming ? [_SHARD.naming] : ["start", "index"];
      const tried = Object.create(null);
      // Shard 0 spells the same under BOTH conventions ("00000"), so a hit on
      // it proves nothing about which convention the emitter used. Latching on
      // that ambiguous success was silently fatal: shard 0 is board indices
      // 0-999, i.e. the top of the default sort and the most likely first tap.
      // Latch "start" there and every subsequent lead misses — measured, 1 of 39
      // shards reachable for the rest of the session, so 38,000 of 38,500 leads
      // fell back to "open this lead on a desktop" with no error shown.
      // Only latch when the spelling was actually discriminating.
      const ambiguous = _shardStem(shardIdx, start, "start") === _shardStem(shardIdx, start, "index");
      for (let n = 0; n < namings.length; n++) {
        const stem = _shardStem(shardIdx, start, namings[n]);
        if (tried[stem]) continue;
        tried[stem] = true;
        try {
          const data = await fetchJsonMaybeGz(`${DETAIL_SHARD_DIR}/${stem}.json`, bust);
          if (data && typeof data === "object") {
            if (!ambiguous) _SHARD.naming = namings[n];
            return data;
          }
        } catch (e) { /* try the other spelling, then give up */ }
      }
      return null;
    })();
  }

  let data = null;
  try { data = await _SHARD.inflight[key]; } catch (e) { data = null; }
  delete _SHARD.inflight[key];

  if (!data) {
    // Shard 0 covers the whole board's first block and is spelled identically
    // under both conventions, so failing it means the directory is not there.
    // Any other shard failing is a per-block problem and must not disable a
    // feature that works everywhere else.
    if (shardIdx === 0) _SHARD.dead = true;
    return false;
  }

  const rec = shardRecordAt(data, start, i, size);
  if (rec === undefined) return false;

  let entry = _shardEntry(key);
  if (!entry) { entry = { key, start, data, applied: new Map() }; }
  else { entry.data = data; }
  _shardMerge(l, rec, entry);
  _shardTouch(entry);
  return true;
}

/**
 * Can the detail panel be rendered as COMPLETE for this lead right now?
 *   "ready"   — everything the desktop shows is in hand
 *   "pending" — a shard fetch would complete it
 *   "missing" — it cannot be completed; say so rather than showing blanks
 */
function detailShardState(l) {
  if (!LEAN) return "ready";                       // desktop: ensureDetails owns it
  if (DATASET !== "foreclosure" || _SHARD.dead) return "missing";
  if (boardIndexOf(l) < 0) return "missing";
  for (let i = 0; i < _SHARD.lru.length; i++) if (_SHARD.lru[i].applied.has(l)) return "ready";
  return "pending";
}

/**
 * What a heavy section shows when it cannot honestly claim the property has
 * none of that data.
 *
 * Returns "" in the "ready" state, and that is the point: an empty section is
 * then allowed to mean empty. Half-populating the panel and letting it read as
 * complete is the one outcome worth more than a round trip to avoid — the
 * sections this covers are comps and condition, which is what a bid is built
 * from.
 */
function detailPendingNote(detailState, what) {
  if (detailState === "loading") {
    return `<div class="shard-loading">Loading ${what} for this lead…</div>`;
  }
  if (detailState === "failed") {
    return `<div class="muted" style="font-size:.9em">Open this lead on a desktop for comps, photo analysis and CAMA. `
      + `They are held in a separate 70 MB file that will not fit in a phone browser.</div>`;
  }
  return "";
}

// Guards against a slow shard painting over a lead the user has since left.
// A phone on rural cell data is the target environment; two taps inside one
// round trip is normal, not exotic.
let _DETAIL_TOKEN = 0;

async function openDetail(l) {
  if (!l) return;
  if (!LEAN) { await ensureDetails(); renderDetail(l, "ready"); return; }

  const tok = ++_DETAIL_TOKEN;
  const st = detailShardState(l);
  if (st !== "pending") { renderDetail(l, st === "ready" ? "ready" : "failed"); return; }

  // Paint immediately with what the board already carries, then fill in. The
  // alternative is a tap that does nothing for the length of a cellular round
  // trip, which reads as a broken button.
  renderDetail(l, "loading");
  const ok = await ensureShardFor(l);
  if (tok !== _DETAIL_TOKEN) return;               // user moved on; leave their panel alone
  renderDetail(l, ok ? "ready" : "failed");
}

/**
 * Render the detail panel.
 *
 * `detailState` is about the HEAVY keys only (comps / vision / cama /
 * rent_comps / foreclosure_sold_comps — web_artifact.LAZY_DETAIL_KEYS), and it
 * exists so an empty section can say WHY it is empty:
 *   "ready"   — the property genuinely has none of that data
 *   "loading" — still fetching; do not claim either way
 *   "failed"  — could not be fetched; do not claim the property has none
 * Desktop always passes "ready", which is exactly what it did before.
 */
function renderDetail(l, detailState) {
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
    const _at = arvTrust(l);
    // The big number carries the caveat itself. A note further down the panel
    // loses to a $780,300 in 28px type — the number anchors first and the prose
    // arrives after the reader has already decided.
    if (c.arv_expected || _at.level === "bad") {
      rows.push(`
        <div class="calc-row">
          <div class="lbl">Est. ARV</div>
          <div>
            <div class="val big${_at.level === "bad" ? " dq-warn-mark" : ""}">${
              _at.level === "bad" ? "&#9888;&#xFE0E; " : _at.level === "proxy" ? "~" : ""
            }${c.arv_expected ? fmtMoney(c.arv_expected) : "unverified"}</div>
            ${c.arv_expected ? `<div class="calc-range">range: <b>${fmtMoney(c.arv_low)}</b> – <b>${fmtMoney(c.arv_high)}</b></div>` : ""}
            ${_at.level === "bad"
              ? `<div class="arv-flag-note"><strong>Do not bid off this number.</strong> ${
                  _at.why.length ? _at.why.join("; ") : "It failed a valuation sanity check"
                }. Max bid, ROI and profit below are all derived from it.</div>`
              : _at.level === "proxy"
                ? `<div class="calc-range">Proxy value — estimated without usable comps or a known square footage.</div>`
                : ""}
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
    // `vision` is a lazy-detail key, so on mobile its absence means one of two
    // completely different things. Only hide the section when we actually know
    // the property has no photo analysis.
    const note = detailPendingNote(detailState, "photo analysis");
    if (note) {
      $("d-vision-section").style.display = "block";
      $("d-vision").innerHTML = note;
    } else {
      $("d-vision-section").style.display = "none";
    }
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
  } else {
    // Be honest about WHY it is empty rather than hiding the section and
    // letting it read as "no comps exist for this property". Once the shard is
    // in hand the note goes away and an empty section means empty — which is
    // the whole difference between this and what mobile showed before.
    const note = detailPendingNote(detailState, "comps");
    if (note) {
      $("d-comps-section").style.display = "block";
      $("d-comps").innerHTML = note;
    } else {
      $("d-comps-section").style.display = "none";
    }
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
  const _bat = arvTrust(l);
  if (_bat.level === "bad") {
    badges.push(`<span class="qbadge neg" title="${arvTrustTitle(_bat).replace(/"/g, "&quot;")}">⚠ ARV flagged — do not bid off it</span>`);
  }
  if (calc.arv_expected) {
    const lowArv = _bat.level === "proxy";
    badges.push(`<span class="qbadge ${_bat.level === "bad" ? "neg" : "info"}" title="${(calc.notes && calc.notes[0]) || ''}">ARV ~$${Number(calc.arv_expected).toLocaleString()}${lowArv ? " (proxy)" : ""}</span>`);
  }
  if (calc.max_bid_70) {
    badges.push(`<span class="qbadge ${_bat.level === "bad" ? "neg" : "info"}">Max bid (70%) $${Number(calc.max_bid_70).toLocaleString()}${_bat.level === "bad" ? " — from a flagged ARV" : ""}</span>`);
  }
  if (calc.roi_pct != null) {
    const cls = _bat.level === "bad" ? "neg" : calc.roi_pct > 25 ? "pos" : calc.roi_pct > 10 ? "warn-light" : "neg";
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
injectDashStyles();  // classes this file owns: flagged-ARV treatment + shard spinner
initCrm();  // wire the CRM-lite controls once (static DOM, survives dataset swaps)
loadData();
