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
  //
  // data_quality, distress_stack, equity and qa_flags are "*" for a DIFFERENT
  // reason than grade/calc: churn, not drift. The build side derives its shard
  // skip-set from this table — only "*" blocks and scalars are left out of
  // docs/detail_shards — so a block held here as a sub-list ships partly in the
  // slim payload and WHOLE in the shard, where these four rewrite ~29 MB of
  // committed .gz on every publish that re-runs the valuation. Measured across
  // the ARV fix: all 39 shards changed and these four were the only keys that
  // moved board-wide. See web_artifact.py's rule 3.
  //
  // data_quality.summary is 5.7 MB of prose and reads like an obvious LEAN cut.
  // It stays: it is the CSV's `data_quality_note` column, and the export must be
  // byte-identical on every device.
  data_quality: "*",
  distress_stack: "*",
  signal_stack: ["count"],
  strategy_fit: ["tags"],
  owner_mailing: ["mailing", "mail_state", "absentee", "out_of_state"],
  owner_phone: ["phone", "source", "needs_dnc_scrub"],
  free_phones: ["phone", "source", "confidence", "needs_dnc_scrub"],
  sc_voter_xref: ["phone", "source", "match_type", "needs_dnc_scrub"],
  sos_agent: ["sosid", "best_contact_name", "best_contact_address"],
  rod: ["has_mortgage", "has_adverse_lien", "has_hoa_lien", "hoa_lien_count"],
  equity: "*",
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
  // APPENDED LAST, on purpose: this is a NEW entry, and the key order of this
  // object is the key order of every record in the slim file, so a new key goes
  // where it moves nothing else.
  //
  // qa_flags is an ARRAY. It never reaches the `subs === "*"` branch — the
  // Array.isArray shape-drift branch above copies it verbatim first, which is
  // the same outcome. It is still declared "*" because the build side reads that
  // literal to decide docs/detail_shards skips the key.
  //
  // Listing it here is also what finally gives MOBILE the board-QA backstop.
  // arvTrust() reads raw.qa_flags for arv_above_asis / arv_below_asis /
  // verdict_on_flagged_arv / bid_on_contradicted_arv / derived_without_arv /
  // gis_row_shared, and until now the key was in no allowlist, so a phone
  // silently saw none of them — 21,678 records on today's board carry one.
  qa_flags: "*",
  // New enrichment fields — keep whole so dashboard can read all sub-keys.
  property_category: "*",
  deed_chain: "*",
};
const _LEAN_RAW_KEYS = Object.keys(_LEAN_RAW);
const _LEAN_RAW_SCALARS = [
  "intent_score", "intent_band", "multifamily_class",
  "stale_case", "geo_imprecise", "sold_confirmed", "kw_vacant", "acres",
  "child_support",
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
  if (isGzip && typeof DecompressionStream === "undefined") {
    // Release the body before unwinding. This throw is CAUGHT (:714 re-throws
    // it, :732 renders the "your browser cannot inflate this" message), so the
    // page keeps running afterwards — and a reader that was never cancelled
    // leaves the response body locked and its socket held open for the life of
    // the document. The one browser family that lands here (older Safari, no
    // DecompressionStream) is also the one least able to spare the connection.
    try { await reader.cancel("NO_DECOMPRESSION"); } catch (e) { /* already gone */ }
    throw new Error("NO_DECOMPRESSION");
  }

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
const FILTER_IDS = ["filter-state", "filter-county", "filter-category", "filter-type", "filter-contact",
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

// ===========================================================================
// WHICH RECORD IS THIS, AND WHERE IS IT? — three small gates, one place each.
//
// The board's plumbing is sound: every payload joins on every record. What it
// could not do was notice when an INPUT record describes a different property
// from the one the row is about. Three of those show up on screen, and each had
// exactly one honest answer available in data the slim board already carries:
//
//   geoTrust()    raw.geo_imprecise — the coordinates are a city/county
//                 centroid, so anything drawn or measured from them is about a
//                 landmark 1-2 miles away, not this parcel. 15,608 of 38,500.
//   ownerNames()  three owner strings exist per lead and 16,512 leads have two
//                 that disagree. One of them was printed, a different one was
//                 exported and skip-traced, and only the printed one was
//                 searchable.
//   placeOfRecord() `city` sometimes holds the COUNTY name (4,347 leads), which
//                 is a fine label and a broken people-search query.
//
// All three read only slim-allowlisted fields, so a phone gets the same answer
// as a desktop and no shard has to land first.
// ===========================================================================

/** `{}` is not data. An allowlisted block the source did not have ships as an
 *  empty object, and `if (block)` says yes to it — which is how mobile painted
 *  section headers with nothing underneath while desktop hid them. */
function _nonEmpty(v) {
  if (!v || typeof v !== "object") return false;
  if (Array.isArray(v)) return v.length > 0;
  for (const k in v) if (Object.prototype.hasOwnProperty.call(v, k)) return true;
  return false;
}

/** Escape a string for use as HTML text. `_attr` is the attribute-context twin. */
function _txt(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Is this lead's position real?
 *
 *   {imprecise:false}                       — coordinates came from the address
 *   {imprecise:true, kind, why, radiusMi}   — they did not
 *
 * The engine sets raw.geo_imprecise when it had to fall back to a city or
 * county centroid ("centroid_snap", 15,593 leads) or when the geocode landed
 * outside the county bounding box ("out_of_bbox", 15). Both mean the same thing
 * to anything that draws a pin or measures a distance: the point is a landmark,
 * not the property. calc already refuses to trust comps found this way
 * (geo_imprecise_comps), but nothing on the SCREEN did.
 */
function geoTrust(l) {
  const kind = l && l.raw && l.raw.geo_imprecise;
  if (!kind) return _GEO_OK;
  if (l._geoTrust !== undefined) return l._geoTrust;
  const out = kind === "out_of_bbox"
    ? { imprecise: true, kind, radiusMi: 5,
        why: "the geocode landed outside this county's boundary, so the point below is wrong by an unknown amount" }
    : { imprecise: true, kind, radiusMi: 2,
        why: "no street-level geocode was found, so these coordinates are the centre of the city or county — typically 1-2 miles from the property" };
  return _memo(l, "_geoTrust", out);
}
const _GEO_OK = { imprecise: false, kind: "", why: "", radiusMi: 0 };

/**
 * Every owner string this lead carries, deduped, best first.
 *
 *   {primary, all:[{name, src}], conflict:bool}
 *
 * There are THREE of them and they are written by three different joins:
 *   l.owner_name            the record's own owner (CSV column, skip-trace)
 *   raw.gis.owner           the county parcel row this lead joined to
 *   raw.owner_mailing.owner the mailing-address resolver's answer
 * On the live board 21,140 leads carry all three, and 16,512 leads have at
 * least two that disagree — 510 Kings Rd, Cleveland NC is "SERVICEMAC LLC" in
 * one and "SC HOMES LP" in another. That is not cosmetic: a disagreement is the
 * board telling you the parcel join may be wrong, and it was being hidden by
 * printing one string and skip-tracing another.
 *
 * `primary` is l.owner_name when present, because that is the field the CSV
 * exports and the people-search link already used — changing which name gets
 * searched would be a silent behaviour change on 32,330 leads. What changes is
 * that the panel now PRINTS that name, and prints the others next to it.
 *
 * (raw.owner_mailing.owner is desktop-only: web_artifact._SLIM_RAW allowlists
 * owner_mailing as ("mailing","mail_state","absentee","out_of_state"), so it is
 * absent on a phone. Read defensively; never require it.)
 */
function ownerNames(l) {
  if (!l || typeof l !== "object") return _OWNERS_NONE;
  if (l._owners !== undefined) return l._owners;
  const raw = l.raw || {};
  const gis = _nonEmpty(raw.gis) ? raw.gis : {};
  const om = _nonEmpty(raw.owner_mailing) ? raw.owner_mailing : {};
  const cand = [
    { name: String(l.owner_name || "").trim(), src: "record" },
    { name: String(gis.owner || "").trim(), src: "county parcel record" },
    { name: String(om.owner || "").trim(), src: "mailing record" },
  ].filter((x) => x.name);
  if (!cand.length) return _memo(l, "_owners", _OWNERS_NONE);
  const seen = Object.create(null);
  const all = [];
  for (const c of cand) {
    const k = _ownerKey(c.name);
    if (!k || seen[k]) continue;
    seen[k] = 1;
    all.push(c);
  }
  // LISTING A SECOND NAME AND WARNING ABOUT IT ARE TWO DIFFERENT DECISIONS.
  //
  // `conflict` used to be `all.length > 1`, which fired on 16,258 leads — and
  // 3,584 of those are the SAME owner written two ways. Measured in the browser
  // over all 38,500:
  //   "Gibson Robert N &"          vs "Gibson Robert N & Gibson Barbara W"
  //   "TABARES JOSE L"             vs "TABARES JOSE L & TABARES IRINA"
  //   "CLC Independent Living, Inc." vs "C L C INDEPENDENT LIVING INC"
  // One record simply carries the spouse, the heirs, or the punctuation the
  // other dropped. Putting "these sources name different owners — check the
  // parcel before you spend money on this one" on those is the wallpaper
  // failure: 22% of the warnings would have been false, and a warning that is
  // wrong a fifth of the time stops being read on the 12,674 where it is real.
  //
  // So `all` still carries every distinct spelling — the longer one is usually
  // the better skip-trace query and is worth showing — while `conflict` is true
  // only when two names cannot be reconciled: neither is a substring of the
  // other once punctuation is removed, and neither one's word set contains the
  // other's. That is the case that actually means "the parcel join may be
  // wrong".
  let conflict = false;
  for (let i = 0; i < all.length && !conflict; i++) {
    for (let j = i + 1; j < all.length; j++) {
      if (!_ownersAgree(all[i].name, all[j].name)) { conflict = true; break; }
    }
  }
  const out = { primary: all[0].name, primarySrc: all[0].src, all, conflict };
  return _memo(l, "_owners", out);
}

/** Punctuation- and space-free form, for deduping spellings of one name. */
function _ownerKey(s) {
  return String(s || "").toUpperCase().replace(/[^A-Z0-9]+/g, "");
}

/** Words of 2+ chars, uppercased. "L" and "&" carry no identity. */
function _ownerTokens(s) {
  const out = Object.create(null);
  const parts = String(s || "").toUpperCase().split(/[^A-Z0-9]+/);
  let n = 0;
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].length > 1 && !out[parts[i]]) { out[parts[i]] = 1; n++; }
  }
  return { set: out, size: n };
}

/**
 * Do two owner strings describe the same owner? Deliberately generous: the
 * caller uses a NO here to tell someone their parcel join may be wrong, so a
 * false alarm costs more than a missed one.
 */
function _ownersAgree(a, b) {
  const ka = _ownerKey(a), kb = _ownerKey(b);
  if (!ka || !kb) return true;                                  // nothing to compare
  if (ka === kb || ka.indexOf(kb) !== -1 || kb.indexOf(ka) !== -1) return true;
  const ta = _ownerTokens(a), tb = _ownerTokens(b);
  if (!ta.size || !tb.size) return true;
  const sub = (x, y) => { for (const k in x.set) if (!y.set[k]) return false; return true; };
  return sub(ta, tb) || sub(tb, ta);
}
const _OWNERS_NONE = { primary: "", primarySrc: "", all: [], conflict: false };

/**
 * Where to tell a people-search this person lives.
 *
 *   {q, label, trusted}
 *
 * The old query was `${l.city} ${l.state}`, and on 4,347 leads `city` holds the
 * COUNTY name — all 3,309 counties_sc.spartanburg_vacant rows plus 298 Pickens
 * and 174 national.distressed among them. TruePeopleSearch then searched a
 * county as if it were a town.
 *
 * ZIP first, whenever there is one (16,470 leads): a ZIP is unambiguous and is
 * a better query than a city name even when the city name is right, so this is
 * not a special case bolted on for the broken rows.
 *
 * When there is no ZIP and city === county the city cannot be distinguished
 * from a county label, so the query falls back to the STATE and says so.
 * Deliberately NOT a "is this a real city" list: Spartanburg SC, Pickens SC and
 * Cleveland NC are all genuine towns inside like-named counties, so a
 * name-shaped test cannot tell a correct row from a broken one — 836 of the
 * 4,347 have a ZIP and get an exact query anyway; the other 3,511 get a wider
 * search rather than a wrong one.
 */
function placeOfRecord(l) {
  const zip = String((l && l.zip_code) || "").trim();
  const city = String((l && l.city) || "").trim();
  const county = String((l && l.county) || "").trim();
  const state = String((l && l.state) || "").trim();
  if (zip) return { q: zip, label: zip, trusted: true, why: "" };
  const cityIsCounty = city && county && city.toLowerCase() === county.toLowerCase();
  if (city && !cityIsCounty) return { q: (city + " " + state).trim(), label: (city + ", " + state).trim(), trusted: true, why: "" };
  if (cityIsCounty) {
    return { q: state, label: state, trusted: false,
      why: `the city field on this lead holds "${city}", which is also the county name and may be a county label rather than a town — `
         + `searching the whole state instead of a place that might not exist` };
  }
  return { q: state, label: state || "(nowhere)", trusted: false,
    why: "this lead has no city and no ZIP, so the search is state-wide" };
}

/** The people-search URL for a lead, or "" when there is no name to search. */
/**
 * One searchable person out of an owner string that may name several.
 *
 * ownerNames() reconciles owner_name / gis.owner / owner_mailing.owner — three
 * SOURCES for the same owner. It does not split a SINGLE string that already
 * holds two people, and county record joins produce those constantly:
 * "WILLIAMS, DENNIS P;WILLIAMS, KELLY D". That whole string was being URL-
 * encoded as one `name=`, and a people search for it matches nobody — the
 * button looked live and silently returned nothing. ~706 leads board-wide.
 *
 * Only ";" is split. It is a record-join separator and never part of a name.
 * " & " is deliberately NOT split, even though it appears on ~3,664 leads:
 * "Gibson Robert N & Gibson Barbara W" is how one county renders a married
 * couple on a single deed, and "Smith & Sons LLC" is one entity. Splitting
 * there would break more searches than it fixed.
 */
function primarySearchName(name) {
  const s = String(name || "");
  const i = s.indexOf(";");
  return (i === -1 ? s : s.slice(0, i)).trim();
}

function skipTraceUrl(l) {
  const o = ownerNames(l);
  if (!o.primary) return "";
  const who = primarySearchName(o.primary);
  if (!who) return "";
  const p = placeOfRecord(l);
  return "https://www.truepeoplesearch.com/results?name=" + encodeURIComponent(who)
    + "&citystatezip=" + encodeURIComponent(p.q);
}

/**
 * Was a rehab cost actually deducted from the max bid?
 *
 *   {state:"deducted"} — rehab_expected > 0, nothing to say
 *   {state:"land"}     — rehab is 0 because it is raw land. CORRECT; say nothing.
 *   {state:"unknown"}  — no rehab figure existed and the bid deducted nothing,
 *                        so max_bid_70 is an upper bound, not a bid.
 *
 * Measured on the live board: of 21,847 published max bids, 2,594 deduct a real
 * rehab, 10,063 are land (rehab_tier "land", rehab 0 — right), and 9,190 have
 * rehab_expected == null with rehab_tier "unknown" — the bid was computed as if
 * the house needed no work. Those 9,190 are the ones a bidder must see.
 *
 * Driven by calc.rehab_expected + calc.rehab_tier, both inside `"calc": "*"` in
 * web_artifact._SLIM_RAW, so it works on today's published board with no
 * republish. A named flag from the valuation side is ALSO honoured when it
 * arrives — see _REHAB_FLAGS.
 */
const _REHAB_FLAGS = { rehab_not_deducted: 1, rehab_unknown_zeroed: 1, max_bid_no_rehab: 1 };
function rehabTrust(l) {
  const c = (l && l.raw && l.raw.calc) || {};
  const r = c.rehab_expected;
  if (typeof r === "number" && r > 0) return _REHAB_DEDUCTED;
  const flagged = (Array.isArray(c.arv_flags) && c.arv_flags.some((f) => _REHAB_FLAGS[f]))
    || (Array.isArray(l && l.raw && l.raw.qa_flags) && l.raw.qa_flags.some((f) => _REHAB_FLAGS[f]))
    || (l && l.raw && l.raw.data_quality && Array.isArray(l.raw.data_quality.flags)
        && l.raw.data_quality.flags.some((f) => _REHAB_FLAGS[f]));
  const tier = String(c.rehab_tier || "").toLowerCase();
  if (tier === "land" && !flagged) return _REHAB_LAND;
  if (r == null || flagged) return _REHAB_UNKNOWN;
  return _REHAB_LAND;   // rehab_expected === 0 with a named non-land tier
}
/**
 * Was the max bid CAPPED at the seller's published asking price?
 *
 * calc.py now floors max_bid_70 at the list price on the two seller-ask
 * sources, because a "max viable bid" above a price anyone can just pay is not
 * a bid. It writes no flag for this — only a note — so the note prefix IS the
 * interface. Literal, verbatim from calc.py:
 *     "Max bid capped at the $60,000 asking price (the 70%-rule figure came
 *      out $62,100)."
 * Returns the note or "".
 *
 * This is deliberately NOT routed through arvTrust: it is not a reason to
 * distrust anything. The ARV is fine, the arithmetic is fine, and the bid on
 * screen is the RIGHT number — it just is not the 70%-rule output, and a reader
 * who reconciles the two by hand deserves to know why they differ. Amber
 * caveat styling would say "doubt this"; it gets plain muted styling that says
 * "this was capped, here is by how much".
 */
const _BID_CAP_NOTE = /^Max bid capped at the \$/i;
function bidCapNote(l) {
  const c = (l && l.raw && l.raw.calc) || {};
  const notes = Array.isArray(c.notes) ? c.notes : [];
  for (let i = 0; i < notes.length; i++) {
    if (typeof notes[i] === "string" && _BID_CAP_NOTE.test(notes[i])) return notes[i];
  }
  return "";
}

const _REHAB_DEDUCTED = { state: "deducted" };
const _REHAB_LAND = { state: "land" };
const _REHAB_UNKNOWN = { state: "unknown" };
// One sentence, two contexts. REHAB_UNKNOWN_NOTE is the tooltip/CSV wording;
// REHAB_UNKNOWN_BODY is the same fact as the continuation of a bolded lead-in
// ("† No rehab was deducted.") so the panel does not read "The engine the
// engine never established one" — which is exactly what deriving one from the
// other by regex produced, and what rendering it in a browser caught.
const REHAB_UNKNOWN_BODY = "The engine never established a repair cost for this property, so the "
  + "70% rule subtracted $0. Treat the figure as a ceiling before repairs, not a number to bid.";
const REHAB_UNKNOWN_NOTE = "No rehab cost was deducted from this bid. " + REHAB_UNKNOWN_BODY;

// The search blob: 15 fields joined + lowercased, for every record, on every
// keystroke. Memoised on FULL. NOT memoised on LEAN — ~150 UTF-16 characters
// × 38,500 is ~12 MB held permanently, and RAM is the exact resource the phone
// runs out of; the 250 ms debounce already removes the per-keystroke cost.
const MEMO_BLOB = !LEAN;
function searchBlob(l) {
  if (l._blob !== undefined) return l._blob;
  const raw = l.raw || {};
  // ALL THREE owner strings, not just the county one.
  //
  // This indexed raw.gis.owner and never l.owner_name, so 2,392 leads carried
  // an owner name that is a CSV column, is what the skip-trace link searches,
  // and is what the placeholder ("address, owner, case #...") promises — and
  // typing it returned nothing. owner_mailing.owner is desktop-only (not in the
  // slim allowlist) and is included anyway: on desktop it is 25,142 more names
  // worth finding, and on a phone it is an empty string that costs a join.
  const b = [
    l.street_address, l.city, l.county, l.state, l.zip_code, l.case_number,
    l.plaintiff, l.defendant, l.trustee, l.source, l.parcel_id,
    l.owner_name,
    (_nonEmpty(raw.gis) && raw.gis.owner) || "",
    (_nonEmpty(raw.owner_mailing) && raw.owner_mailing.owner) || "",
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
  const cat = ($("filter-category") || {}).value || "";
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
    if (cat) {
      const pc = (l.raw && l.raw.property_category) ? l.raw.property_category.category : "";
      if (pc !== cat) return false;
    }
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
      // "Comp-backed only (HIGH)" is a trust claim, so it must not hand back a
      // valuation this page prints in red. Measured on a full recompute: 804
      // leads are HIGH confidence and 14 of them render "do not bid off this"
      // — arv_confidence describes how the number was BUILT, not whether
      // another record contradicts it. (0 of the 804 are weak, so nothing else
      // moves.) The "Exclude proxy (hide LOW)" option is deliberately left
      // alone: it says "hide LOW confidence", not "hide flagged", and 8,723 of
      // its 12,940 leads are the weak tier the board keeps on purpose.
      if (arvc === "comp" && arvTrust(l).level === "bad") return false;
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
// FOUR LEVELS, because they are four different claims and one treatment for all
// of them is how the real warning became wallpaper:
//
//   "bad"   — something CONCLUDED this number is wrong, or another record
//             contradicts it. Loud (red, ⚠, tinted). The money under it is
//             either already gone (grading.py withholds it server-side on the
//             contradicted tier) or is shown dimmed and labelled as derived.
//   "weak"  — calc named a reason the EVIDENCE does not describe this exact
//             property, but nothing disputes the magnitude. The pipeline
//             deliberately KEEPS the money here (16,310 leads; blanking two
//             thirds of the board's economics would delete the board), so the
//             screen has to carry the doubt instead: amber, "≈", and the reason
//             attached. Distinct from "fine" and from "do not bid off this".
//   "proxy" — no named flag at all, just a low-confidence estimate (no comps /
//             no sqft). Quiet "~", muted. True of most of the board (25,559
//             low_arv_confidence and 20,447 no_sqft out of 38,500) and a red
//             flag on two rows in three is wallpaper, which is part of how the
//             real one stayed invisible.
//   "ok"    — nothing known against it.
//
// HOW A LEVEL IS DECIDED — an explicit table, not a keyword regex.
//
// The old rule was `_ARV_BAD_FLAGS[n] || (n.includes("arv") && /above|outlier|
// …/.test(n))`. Measured by recomputing all 38,500 leads under the working-tree
// valuation code and running THIS function over the result: of the 13 flag
// strings valuation/calc.py actually emits, 8 hit neither clause —
// anchor_not_independent (15,991 leads), geo_imprecise_comps (6,173),
// land_comps_rejected (1,624), bid_proxy_arv (938), comp_kind_mismatch (538),
// floor_raise_large (377), floor_rejected_extreme (284), cama_class_mismatch
// (249). The shape rule could not see them because calc names a flag after the
// EVIDENCE ("comp_kind_mismatch"), not after the verdict, and none of those
// names contains "arv". 16,310 leads published a max bid and an ROI off a
// flagged ARV; 14,695 of them rendered with no warning louder than a "~".
//
// So every flag string is now LOOKED UP. The four tables below are exhaustive
// over what the pipeline emits today (measured, not guessed):
//   valuation/calc.py -> calc.arv_flags          13 strings
//   enrichment_data_quality.py -> data_quality.flags  12 strings
//   enrichment_board_qa.py -> raw.qa_flags        14 strings
// Anything not in a table is handled by arvFlagClass()'s documented default.
//
// AN UNRECOGNISED FLAG IS A CAVEAT, NOT A PASS. calc.arv_flags exists only to
// name reasons to distrust the ARV, so a name this file has never heard of
// still means "distrust it" — unknown entries there fall to "weak". The cost of
// a wrong guess is one extra amber caveat; the cost of the opposite default is
// somebody bidding off a number the engine had already doubted.
//
// THIS FILE DOES NOT DEPEND ON THE PIPELINE HAVING RUN IN THE RIGHT ORDER.
// data_quality writes severity names (arv_unreliable / arv_no_independent_check)
// that are the authoritative verdict, and they are read here — but main.py runs
// that layer 351 lines BEFORE the valuation, so on a real run those names are
// computed from the PREVIOUS run's calc. Classifying calc.arv_flags directly
// means the screen is right either way: the severity names confirm, they are
// not required.
// ===========================================================================

// BAD — another record, or the arithmetic itself, disputes the number. Mirrors
// grading.ARV_FLAGS_CONTRADICTED plus the data-quality/QA names for the same
// verdict. Values are the reason shown to the reader, so a warning always says
// WHY and never only "flagged".
const _ARV_BAD_FLAGS = {
  // --- valuation/calc.py :: calc.arv_flags (contradicted tier) --------------
  // NO MULTIPLIER IN THIS STRING. calc.py has TWO bid-proxy paths and they use
  // different factors — improved property is `opening_bid × 2.4` (134 leads on
  // the live board), raw land is `opening_bid × 1.5` (815). Both emit the one
  // flag `bid_proxy_arv`, so a hard-coded "× 2.4" here was actively wrong on
  // 815 of the 949: 162 Newberry Rd, Walhalla, Oconee SC publishes ARV $225,000
  // on a $150,000 bid — which is 1.5×, exactly right — while this sentence told
  // the reader the ARV was bid × 2.4, i.e. that the true figure was $360,000 or
  // that the bid behind $225,000 was $93,750. Neither is a rounding error;
  // both invent a property.
  // bidProxyWhy() below reads the real factor out of calc's own note and
  // substitutes it. This string is the fallback for when no note survived, and
  // it deliberately claims only what is true of both paths.
  bid_proxy_arv: "the ARV is a fixed multiple of the opening bid, so every figure under it is the bid restated",
  anchor_shared_across_parcels: "the county figure this ARV is anchored to is stamped on many other parcels — it is not an appraisal of THIS property",
  arv_above_anchor: "the ARV runs several times the county's own appraisal of this parcel",
  arv_above_anchor_extreme: "the ARV was past the hard multiple of the county appraisal and was withheld",
  ppsf_ceiling: "the implied $/sqft is above anything this market supports — the comps or the sqft are wrong",
  floor_raise_large: "the county/sale floor multiplied the comp ARV by more than 2.5× — confirm the assessor record belongs to this property",
  floor_rejected_extreme: "the county record and the comps disagree by more than 6× and only one of them is right",
  comp_kind_mismatch: "priced off site-built comps, but the county calls this manufactured housing",
  cama_class_mismatch: "the assessor row joined to this lead describes a commercial building — the parcel join is wrong",
  // The two ANOMALY verdicts. grading.anomaly_flags() merges these INTO
  // calc.arv_flags so the Python trust gate can see the same garbage-in tests
  // `grade()` has run since 2026-06-19. They arrive named after the verdict,
  // and they are the server-side twin of the arv_over_2m / roi_over_400
  // thresholds this file computes below — see the dedupe in arvTrust().
  arv_above_plausible_max: "the ARV is above $2M, which is not a price a comparable property in these counties has fetched",
  arv_implies_implausible_roi: "the implied ROI is over 400%, so the ARV and the opening bid are describing different properties",
  // --- enrichment_data_quality.py :: data_quality.flags --------------------
  arv_withheld: "the computed value failed a hard sanity check and was not published",
  arv_unreliable: "the pipeline classified this valuation as contradicted",
  arv_bid_and_roi_withheld: "max bid, ROI, profit and the deal verdict were withheld on purpose",
  arv_outlier: "implausible magnitude for this property",
  // --- enrichment_board_qa.py :: raw.qa_flags ------------------------------
  arv_above_asis: "the ARV sits above the as-is value by more than the board tolerates",
  arv_below_asis: "the after-repair value came out BELOW the as-is value, which cannot be true",
  verdict_on_flagged_arv: "board QA caught a deal verdict published on a flagged ARV",
  bid_on_contradicted_arv: "board QA caught a max bid published on a contradicted ARV",
  // --- ADDED THIS ROUND. Confirmed against the working tree's calc.py, not
  //     assumed: each string below is grepped and present. grading.py puts all
  //     three on the CONTRADICTED tier, so the dollars are already gone
  //     server-side and this table only has to explain the hole.
  //
  //     Two of them would have been misread by the unrecognised-name fallback
  //     rather than missed: _ARV_BAD_WORDS matches "above"/"ceiling"/"mismatch",
  //     so they would have rendered as `unrecognised valuation flag "arv above
  //     list price"` — the right LEVEL with a sentence that tells the reader
  //     nothing. Naming them is the whole point of a lookup table.
  arv_proxy_above_ceiling: "a proxy ARV came out past the $2M plausibility ceiling and was thrown away — the figure shown as withheld is what was rejected, not a value",
  arv_above_list_price: "the ARV is at least 1.6× the price the seller is publicly asking for this property, and anyone can simply pay the asking price",
  arv_land_sqft_mismatch: "the record calls this land but carries a house-sized living area, so the ARV was priced off a building that may not exist",
  derived_without_arv: "board QA caught money published with no ARV to derive it from",
  // --- names not currently emitted, kept because they were in play during
  //     the valuation work and cost nothing while absent ---------------------
  arv_vs_assessed_extreme: "the ARV and the assessed value disagree by an extreme multiple",
  arv_unverified: "nothing verified this value",
  arv_geo_suspect: "the coordinates behind the comps are suspect",
  arv_floored: "the value was forced up to a floor rather than computed",
  ppsf_outlier: "the implied $/sqft is an outlier",
  type_mismatch: "the comps are a different property type",
  property_type_mismatch: "the comps are a different property type",
  comp_type_mismatch: "the comps are a different property type",
  shared_centroid: "several leads share one coordinate, so the comps may be another property's",
  assessed_is_tax_amount: "the 'assessed value' read as a tax bill, not a valuation",
};

// WEAK — the inputs do not describe this exact property, or the best evidence
// was refused and a weaker tier carried the lead. Nothing contradicts the
// number. Mirrors grading.ARV_FLAGS_WEAK_EVIDENCE. The pipeline keeps the money
// on these, so this file is what makes the doubt visible.
const _ARV_WEAK_FLAGS = {
  // --- valuation/calc.py :: calc.arv_flags (weak-evidence tier) ------------
  // THIS ONE MATTERS MORE THAN THE OTHER FOUR ADDED THIS ROUND. Left
  // unlisted, `arv_tier_refused_ceiling` hits _ARV_BAD_WORDS on "ceiling" and
  // classifies BAD — a red "do not bid off it" on 71 leads whose valuation the
  // engine considers merely weak, where a LATER tier supplied the ARV that is
  // actually on screen. The fallback is deliberately pessimistic and that is
  // right for a name nobody has read; it is wrong here, and the fix is to read
  // it. (grading.py: ARV_FLAGS_WEAK_EVIDENCE.)
  arv_tier_refused_ceiling: "one valuation method blew the plausibility ceiling and was discarded — the ARV shown came from a different method",
  // No "arv" in the name, so it only classifies at all because calc.arv_flags
  // is a trusted namespace (`inArvFlags`). Weak either way; named so it says
  // something.
  county_values_disagree: "the county's own two valuations of this parcel disagree with each other, so the anchor under this ARV is unreliable",
  anchor_not_independent: "the ARV is the county's own figure restated, so nothing independent confirms it describes this property",
  geo_imprecise_comps: "the comps were picked by radius from a shared city centroid, not from this address",
  stale_sale_floor: "a recorded sale was refused as a floor for being undated or more than 10 years old",
  land_comps_rejected: "the land comps were refused — none close enough in acreage for $/acre to transfer",
  land_ppa_ceiling: "the county's value implied a $/acre this dirt cannot support, so it was refused",
  // The two land-AGREEMENT verdicts (calc.LAND_COMP_SPREAD_MAX). `disagree` is
  // a 2-comp pool refused for spanning >=8x, so the ARV on screen came from a
  // LATER tier and the comps on the card did not produce it. `spread` is a
  // 3+-comp MEDIAN that shipped off a pool that wide — a real comp, robust to
  // one mis-typed sale, but a band rather than a point. Both quote calc's own
  // note, which gives the reader the actual $/acre range.
  land_comps_disagree: "the two land comps disagreed by more than 8×, so their average was refused and this value came from a different tier",
  land_comp_spread: "the land comps span more than 8× in $/acre — the median shipped, but read the range, not the point",
  // --- enrichment_data_quality.py :: data_quality.flags --------------------
  arv_no_independent_check: "nothing independent confirms this value describes this property",
  // `arv_sanity_flag` only says "calc.arv_flags is non-empty" — it names no
  // severity, so it cannot promote a lead to bad on its own. The specific
  // calc flags on the same lead decide that; this one only guarantees the row
  // is never silent when they are missing (a stale board, or the LEAN payload
  // arriving before the shard).
  arv_sanity_flag: "the valuation carries a sanity flag",
  // --- enrichment_board_qa.py :: raw.qa_flags ------------------------------
  gis_row_shared: "several leads resolved to the same GIS row, so the sqft/value behind this ARV may be another parcel's",
  // --- not currently emitted, kept while absent ---------------------------
  geo_imprecise: "the coordinates used to find comps are imprecise",
};

// WEAK, BUT THE SUBJECT IS THE BID — not the ARV.
//
// grading.py puts `placeholder_opening_bid` in ARV_FLAGS_WEAK_EVIDENCE so the
// verdict is withheld (deal_status is literally `bid <= max_bid * 0.95`, which
// a $1,000 upset figure makes unconditionally GREAT). But its own comment is
// explicit that nothing here impugns the ARV, and it deliberately chose a name
// this file would NOT paint red: "a red 'do not bid off this ARV' mark would be
// a lie about which number is bad".
//
// So it is weak — the money below is genuinely wrong, because ROI, profit and
// bid/ARV are all measured against a cost that is not the real one — but the
// SENTENCE has to name the bid. arvTrust() tracks this as `subject`, and the
// headline changes only when every reason on the lead is bid-scoped.
//
// The LEVEL is deliberately not softened for the ARV cell. Measured on a full
// working-tree recompute: 66 leads carry this flag and 0 of them carry it
// alone, so on today's board the ARV cell's treatment is set by a real ARV
// reason in every single case and this decision changes nothing on screen. If
// that ever stops being true the result is one extra amber "≈" on an ARV
// nobody disputed, which is the cheap direction to be wrong in.
const _ARV_BID_FLAGS = {
  placeholder_opening_bid: "the opening bid is under 5% of the ARV — an upset or placeholder figure, not the real acquisition cost, so ROI, profit and bid/ARV are measured against the wrong number",
};

// PROXY — a confidence label, not a verdict. Quiet by design.
const _ARV_PROXY_FLAGS = {
  low_arv_confidence: "estimated without comp-grounded evidence",
  no_sqft: "no known square footage",
  sqft_estimated: "square footage is an estimate from a building footprint",
  // Absence, not distrust: there is no raw['calc'] on this lead at all, so
  // there is no ARV, no max bid and no ROI on screen to doubt. Classified
  // explicitly and QUIETLY because enrichment_data_quality.py:223 designed it
  // that way and said so in a comment — and because the alternative here is
  // actively wrong. Left unrecognised it fell to the weak default, which made
  // arvTrust() read "the engine priced this and refused the answer" and paint a
  // red "not published ⚠" on a lead that was simply never valued. 0 leads on
  // today's board (38,500/38,500 carry a calc), so this classification is
  // insurance, not a visible change.
  arv_not_computed: "this lead has no valuation block at all — nothing was computed, so there is nothing to distrust",
};

// DELIBERATELY IGNORED — real flags that are NOT claims about the ARV. Each one
// already has its own treatment elsewhere on the screen, and repeating it here
// would put an ARV warning on a lead whose ARV nobody has questioned. Listed
// explicitly so "unclassified" can keep meaning "unknown" rather than
// "everything we did not bother with".
const _ARV_IGNORED_FLAGS = {
  synthetic_address: "address quality — rendered by the ⚠ placeholder-address badge",
  approximate_address: "address quality — rendered by the 📍 approx-address badge",
  no_address: "address quality — the address cell is already empty",
  dup_address: "duplicate row detection, not a valuation claim",
  no_owner: "contactability, not a valuation claim",
  missing_last_sale: "sale-history coverage, not a valuation claim",
  court_owner_mismatch: "owner-name provenance, not a valuation claim",
  rehab_vs_condition: "rehab estimate vs condition tier — about the REHAB number, not the ARV",
  // SAME REASON AS THE LINE ABOVE, AND IT HAD TO BE STATED OR IT WOULD HAVE
  // BEEN THE LOUDEST WRONG WARNING THIS ROUND ADDED.
  //
  // calc.py now emits rehab_not_deducted into calc.arv_flags on 9,586 leads.
  // calc.arv_flags is a trusted namespace, so an unlisted name there falls to
  // arvTrust's weak default — which would have printed `≈ ARV unverified — a
  // band, not a number · rehab not deducted` on every one of them. Nothing
  // about the ARV is in doubt on those leads. The rehab is, and rehabTrust()
  // already says so ON the max bid, which is the only figure the missing rehab
  // actually moves.
  //
  // grading.py does treat it as weak evidence server-side (it drops the deal
  // verdict on 15 leads). That is the right server behaviour and it does not
  // need the client to restate it as ARV doubt: 9,586 amber ARV captions to
  // carry 15 verdict removals is the exact trade that turned the real warning
  // into wallpaper the first time.
  rehab_not_deducted: "no rehab was deducted from the max bid — rendered by rehabTrust() on the bid itself, and it is not a claim about the ARV",
};

// Promotes an UNRECOGNISED arv-named flag from the weak default to bad when the
// name reads as a verdict rather than a confidence label. Deliberately does NOT
// match "low_arv_confidence". Only reached for names absent from every table
// above, so it is a safety net for a flag added after this file ships, not the
// primary rule it used to be.
const _ARV_BAD_WORDS = /(above|below|exceed|extreme|outlier|suspect|unverif|unreliab|implausib|ceiling|inflat|mismatch|withheld|suppress|overrid|contradict)/;

// calc already writes the SPECIFIC reason into calc.notes — "none within 5x the
// subject's 2.60 ac (comp lots 0.30-0.60 ac)" is worth far more to a bidder
// than the flag name. These map a flag to the note that explains it, so the
// warning can quote the engine's own words instead of paraphrasing them.
// Patterns are anchored on wording measured in the live notes.
const _ARV_FLAG_NOTE = {
  land_comps_rejected: /^Land comps rejected/i,
  land_ppa_ceiling: /not usable as a land value/i,
  geo_imprecise_comps: /IMPRECISE coordinate/i,
  anchor_not_independent: /^No independent cross-check/i,
  comp_kind_mismatch: /does not sell at site-built/i,
  cama_class_mismatch: /assessor record joined to this lead/i,
  stale_sale_floor: /^Recorded sale \(.+NOT used as an ARV floor/i,
  floor_rejected_extreme: /floor limit/i,
  floor_raise_large: /raised .+ by the county\/sale floor/i,
  // `^ARV proxy from bid` missed calc.py's land path entirely — the note it
  // writes there is "Land ARV proxy from bid × 1.5 (150,000)", which does not
  // start with "ARV". Measured on the live board: 134 notes matched, 815 did
  // not, out of 949 leads flagged bid_proxy_arv. Those 815 lost the engine's
  // own sentence, which is the one place the real multiplier was written down.
  bid_proxy_arv: /^(?:Land\s+)?ARV proxy from bid/i,
  arv_above_anchor: /not impossible for distressed inventory/i,
  arv_above_anchor_extreme: /^ARV WITHHELD/i,
  ppsf_ceiling: /ceiling this market supports/i,
  // calc.LAND_COMPS_DISAGREE_MARKER / LAND_COMP_SPREAD_MARKER verbatim. These
  // notes carry the actual $/acre numbers ("$5,263/ac vs $73,018/ac", "read the
  // $22,500-$381,500 range, not the point"), which is the whole answer for the
  // averaged-land-comps bug and is worth far more than either flag name.
  land_comps_disagree: /^Land comp pair refused/i,
  land_comp_spread: /^Land comps span/i,
};

// Why an ARV is absent, in calc's own words. Ordered: the hard refusal first.
const _ARV_ABSENT_NOTE = /^(ARV WITHHELD|Proxy ARV \(.+\) exceeds|Insufficient (land )?data for ARV|Land comps rejected|County value \(.+\) not usable)/i;

// Names that restate a severity rather than give a reason. Every one of them is
// derived by enrichment_data_quality FROM calc.arv_flags, so when calc named
// something specific these add nothing; when it did not (a board carried over
// from before the guards, the LEAN payload, or main.py running the data-quality
// layer before the valuation) they are the only thing left and they speak.
const _ARV_GENERIC_FLAGS = {
  arv_sanity_flag: 1, arv_unreliable: 1, arv_bid_and_roi_withheld: 1,
  arv_no_independent_check: 1, arv_withheld: 1,
};

const _LVL = { ok: 0, proxy: 1, weak: 2, bad: 3 };
const _LVL_NAME = ["ok", "proxy", "weak", "bad"];
const _ARV_TRUST_OK = { level: "ok", why: [], flags: [], notes: [], absent: "", short: "", subject: "arv" };

/**
 * Capitalise a reason so it reads as a sentence after a bold lead-in. The flag
 * reasons are written lowercase because most of them are joined with "; " into
 * the middle of a sentence; only the first one after a full stop needs this.
 */
function _cap(s) {
  const t = String(s == null ? "" : s);
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

/** Escape a string for use inside a double-quoted HTML attribute. */
function _attr(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Classify ONE flag string. Returns `{level, why, subject}` or null for "not an
 * ARV claim". `inArvFlags` says the name came from calc.arv_flags, whose entire
 * purpose is to name reasons to distrust the ARV — so an unknown name there is
 * a caveat. data_quality.flags and qa_flags are MIXED namespaces (they also
 * carry address, owner and duplicate-row names), so an unknown name there is
 * only treated as an ARV claim when it says so: it mentions "arv".
 *
 * `subject` is "arv" for everything except the bid-scoped table — see
 * _ARV_BID_FLAGS. It changes the WORDS, never the level.
 */
/**
 * The REAL bid multiplier for a bid-proxy ARV, read out of calc's own note.
 *
 * calc.py writes the factor into the note and nowhere else — the flag string is
 * `bid_proxy_arv` on both paths, so the flag cannot tell 2.4 from 1.5. Matching
 * the number here is what lets one flag produce two true sentences.
 * Live strings, verbatim:
 *   "ARV proxy from bid × 2.4 (150,000 × 2.4) — rough"
 *   "Land ARV proxy from bid × 1.5 (150,000)"
 * Returns "" when no note survived, and the caller falls back to the
 * multiplier-free wording.
 */
const _BID_PROXY_MULT = /^(?:Land\s+)?ARV proxy from bid\s*[×x*]\s*([0-9]+(?:\.[0-9]+)?)/i;
function bidProxyWhy(c) {
  const notes = c && Array.isArray(c.notes) ? c.notes : [];
  for (let i = 0; i < notes.length; i++) {
    if (typeof notes[i] !== "string") continue;
    const m = _BID_PROXY_MULT.exec(notes[i]);
    if (m) return `the ARV is the opening bid × ${m[1]}, so every figure under it is the bid restated`;
  }
  return "";
}

function arvFlagClass(name, inArvFlags, c) {
  const n = String(name == null ? "" : name).toLowerCase();
  if (!n) return null;
  if (n === "bid_proxy_arv") {
    return { level: "bad", why: bidProxyWhy(c) || _ARV_BAD_FLAGS.bid_proxy_arv, subject: "arv" };
  }
  if (_ARV_BAD_FLAGS[n]) return { level: "bad", why: _ARV_BAD_FLAGS[n], subject: "arv" };
  if (_ARV_WEAK_FLAGS[n]) return { level: "weak", why: _ARV_WEAK_FLAGS[n], subject: "arv" };
  if (_ARV_BID_FLAGS[n]) return { level: "weak", why: _ARV_BID_FLAGS[n], subject: "bid" };
  if (_ARV_PROXY_FLAGS[n]) return { level: "proxy", why: _ARV_PROXY_FLAGS[n], subject: "arv" };
  if (_ARV_IGNORED_FLAGS[n]) return null;
  if (!inArvFlags && n.indexOf("arv") === -1) return null;
  const pretty = n.replace(/_/g, " ");
  if (_ARV_BAD_WORDS.test(n)) {
    return { level: "bad", subject: "arv", why: `unrecognised valuation flag "${pretty}", and the name reads as a verdict` };
  }
  return {
    level: "weak",
    subject: "arv",
    why: `unrecognised valuation flag "${pretty}" — shown as a caveat because an unknown warning must never render as silence`,
  };
}

// ===========================================================================
// THE STAMPED-VALUE CLUSTER, on the leads that KEEP their money.
//
// THE FLAG STRING, exactly, and who writes it:
//   "anchor_shared_across_parcels"
//     written by src/foreclosure_scraper/enrichment_board_qa.py
//     (SHARED_ANCHOR_FLAG) onto raw['qa_flags'] for EVERY lead in a detected
//     cluster, and additionally onto raw['calc']['arv_flags'] by that file's
//     _retract_shared_anchor() for the subset whose ARV was built on the
//     stamped county figure. valuation/grading.py lists it in
//     ARV_FLAGS_CONTRADICTED, which is what strips max_bid_70 / roi_pct /
//     profit / deal_status and withholds equity on that subset, server-side.
//
// Nothing new is written by this file and no new flag string is invented. Both
// channels already ship: web_artifact._SLIM_RAW carries "qa_flags": "*" and
// "calc": "*", so this reads identically on desktop and on a phone.
//
// MEASURED on the live board, 38,500 records:
//   1,706  carry the flag in raw.qa_flags        (in a cluster)
//   1,451  also carry it in calc.arv_flags       (ARV built on the stamp —
//          money already gone, and calc.notes carries the full prose saying so)
//     255  carry it ONLY in qa_flags             (comp-grounded ARV; of these
//          11 publish a max bid, 2 an ROI, 6 an equity figure, 0 a verdict)
//       0  of the 255 said anything about it anywhere on the panel
//
// The 255 are the ones this exists for. Their bid is defensible — the ARV came
// from recorded arms-length comps, not from the stamp — but "the county figure
// for this parcel is one number stamped across many parcels" is a fact about
// the parcel record an operator is about to bid against, and it survived the
// valuation being fine. It gets said.
//
// WHAT IS NOT SAID: how many parcels. enrichment_board_qa computes that count
// (`info['parcels']`) and writes it into the withheld leads' calc.notes prose,
// but it is not persisted on the comp-grounded ones, and the anchor field it
// grouped on (market_value / cama.appraised_value / tax_value) is not fully
// present in the slim payload — market_value and cama are both absent, so a
// client-side recount would give a phone a different N than a desktop. A number
// that changes with the device is worse than no number, so this states the
// fact and sends the reader to the parcel record.
// ===========================================================================
const STAMP_CLUSTER_FLAG = "anchor_shared_across_parcels";

/**
 * `{inCluster, arvDerivedFromStamp}` — is this lead in a stamped-value cluster,
 * and did its ARV come from the stamp?
 *
 * `arvDerivedFromStamp` true  -> the money is already withheld and calc.notes
 *                                explains it; arvTrust() paints it bad.
 * `arvDerivedFromStamp` false -> the 255. The money stands. Disclose the
 *                                cluster; do NOT contradict the valuation.
 */
function stampCluster(l) {
  const raw = (l && l.raw) || {};
  const qf = Array.isArray(raw.qa_flags) ? raw.qa_flags : null;
  if (!qf) return _STAMP_NONE;
  let inCluster = false;
  for (let i = 0; i < qf.length; i++) {
    if (String(qf[i] || "").toLowerCase() === STAMP_CLUSTER_FLAG) { inCluster = true; break; }
  }
  if (!inCluster) return _STAMP_NONE;
  const af = (raw.calc && Array.isArray(raw.calc.arv_flags)) ? raw.calc.arv_flags : [];
  let derived = false;
  for (let i = 0; i < af.length; i++) {
    if (String(af[i] || "").toLowerCase() === STAMP_CLUSTER_FLAG) { derived = true; break; }
  }
  return { inCluster: true, arvDerivedFromStamp: derived };
}
const _STAMP_NONE = { inCluster: false, arvDerivedFromStamp: false };

/** The sentence shown on a comp-grounded lead inside a cluster. */
const STAMP_CLUSTER_NOTE =
  "The county's own valuation of this parcel is one figure stamped across many "
  + "different parcels in this county, so the assessor record does not describe "
  + "this property. The ARV above did NOT come from it — it was built from "
  + "recorded comparable sales — which is why max bid, ROI and equity are still "
  + "published here rather than withheld. Read them as sound, and the county "
  + "record beneath them as unverified: check the parcel record before you bid.";

/** calc's own note explaining `flag`, or "" when it wrote none. */
function arvFlagNote(c, flag) {
  const re = _ARV_FLAG_NOTE[flag];
  if (!re || !c || !Array.isArray(c.notes)) return "";
  for (let i = 0; i < c.notes.length; i++) {
    if (typeof c.notes[i] === "string" && re.test(c.notes[i])) return c.notes[i];
  }
  return "";
}

/**
 * `{level, why[], flags[], notes[], absent, short, subject}` for one listing.
 *
 *   level  — "bad" | "weak" | "proxy" | "ok" (the worst of everything seen)
 *   why    — human reasons, worst first, for tooltips and note boxes
 *   flags  — the raw flag strings that produced them, for the chip label
 *   notes  — calc's own explanatory notes for those flags, verbatim
 *   absent — "withheld" | "refused" | "unpriced" | "" — why there is no ARV
 *   short  — a few words naming the loudest reason, for a card chip
 *   subject— "arv" (normal) or "bid" when EVERY reason on this lead is about
 *            the opening bid rather than the valuation. Chooses the headline
 *            only; the level, the colour and the ≈ are unchanged either way.
 *
 * Memoised non-enumerably (the exportCsv `{...l}` spread must never pick this
 * up) and safe to memoise: every input lives in raw.calc / raw.data_quality /
 * raw.grade / raw.qa_flags, all of which are in the slim allowlist and none of
 * which is a lazy-detail key, so a shard merge cannot change the answer.
 *
 * raw.qa_flags is why that sentence had to be earned rather than assumed. Until
 * qa_flags was added to _LEAN_RAW it reached a phone ONLY through the shard,
 * and the shard always lost the race: this function is called from renderCards
 * and from the filter, both of which run before any lead is opened, so the memo
 * was already set — from a record with no qa_flags — by the time ensureShardFor
 * merged them in. The detail panel then re-read the memo. So on mobile every
 * qa_flags byte in the shard was dead weight: paid for on the wire, never able
 * to change a single warning on screen. In the allowlist it arrives with the
 * board, before the first render, and the memo is computed from it.
 */
function arvTrust(l) {
  if (!l || typeof l !== "object") return _ARV_TRUST_OK;
  if (l._arvTrust !== undefined) return l._arvTrust;
  const raw = l.raw || {};
  const c = raw.calc || {};
  let lvl = 0;
  const hits = [];          // {rank, flag, why, note, subject}
  const seen = {};

  const consider = (name, inArvFlags) => {
    if (typeof name !== "string" || !name) return;
    const n = name.toLowerCase();
    const cls = arvFlagClass(n, inArvFlags, c);
    if (!cls) return;
    const rank = _LVL[cls.level];
    if (rank > lvl) lvl = rank;
    if (seen[n]) return;
    seen[n] = 1;
    hits.push({ rank, flag: n, why: cls.why, note: arvFlagNote(c, n), subject: cls.subject || "arv" });
  };

  // calc.arv_flags FIRST: it is the authoritative, specific list, and it is the
  // only source that survives main.py running the data-quality layer before the
  // valuation. (calc emits `arv_flags`, NOT `flags`; reading `c.flags` was a
  // dead branch for months and is kept only as a fallback for a future writer.)
  if (Array.isArray(c.arv_flags)) c.arv_flags.forEach((f) => consider(f, true));
  if (Array.isArray(c.flags)) c.flags.forEach((f) => consider(f, true));
  const dq = raw.data_quality;
  if (dq && Array.isArray(dq.flags)) dq.flags.forEach((f) => consider(f, false));
  // qa_flags is written by enrichment_board_qa. It used to be in NO slim
  // allowlist, which made it a desktop-only signal: 21,678 of 38,500 records
  // carry one and a phone saw none of them, so the board-QA reasons for
  // distrusting an ARV (arv_above_asis, verdict_on_flagged_arv, gis_row_shared,
  // ...) were simply missing on mobile. It is in _LEAN_RAW now. Still read
  // defensively — a board published before that change carries no qa_flags in
  // its slim payload, and nothing above depends on this.
  //
  // ONE NAME IS SCOPED, and the scope is the writer's, not this file's.
  // enrichment_board_qa.py writes "anchor_shared_across_parcels" onto TWO
  // channels and means two different things by it (its own comment, at
  // enrichment_board_qa.py:616):
  //
  //   raw['qa_flags']        every lead in a stamped cluster, "because sitting
  //                          in one is a fact about the lead"   — 1,706 leads
  //   calc['arv_flags']      only the leads whose ARV DESCENDS from the stamp,
  //                          "because that list is the trust gate's vocabulary
  //                          and there it would be a claim about the
  //                          valuation"                          — 1,451 leads
  //
  // The 255-lead difference is comp-grounded ARVs, and the pipeline keeps every
  // dollar on them on purpose. Reading the qa_flags copy as a verdict painted
  // all 255 "Do not bid off this number" beside a max bid the same panel still
  // prints — 7658 Hickory Creek Dr, Denver NC: ARV from 184 recorded
  // arms-length sales, $588,100 max bid, and a red do-not-bid over the top of
  // it. That is the reader/writer mismatch, in the direction that teaches an
  // operator to ignore the red.
  //
  // So: the flag stays in _ARV_BAD_FLAGS and is UNCHANGED there — it does all
  // of its work when it arrives in calc.arv_flags (the `consider(f, true)` pass
  // above, 1,451 leads, still bad, still every dollar withheld server-side).
  // From qa_flags it is skipped HERE and disclosed instead by stampCluster()
  // below, which says the true thing at full volume. No other qa_flags name is
  // scoped: arv_above_asis / arv_below_asis / verdict_on_flagged_arv /
  // bid_on_contradicted_arv / derived_without_arv are all claims about the
  // valuation on whichever channel they arrive.
  if (Array.isArray(raw.qa_flags)) {
    const _inCalcFlags = Array.isArray(c.arv_flags)
      ? c.arv_flags.map((f) => String(f || "").toLowerCase())
      : [];
    raw.qa_flags.forEach((f) => {
      const n = String(f || "").toLowerCase();
      if (n === STAMP_CLUSTER_FLAG && _inCalcFlags.indexOf(STAMP_CLUSTER_FLAG) === -1) return;
      consider(f, false);
    });
  }
  // Boolean verdicts written straight onto calc — arv_geo_suspect already is one.
  for (const k in c) { if (c[k] === true && k.indexOf("arv") === 0) consider(k, false); }

  const arv = c.arv_expected;
  // Thresholds the pipeline ALREADY treats as anomalous: grading.py withholds
  // the LETTER grade at ARV > $2M or ROI > 400%. Recomputing them here needs no
  // board rebuild, which is the point — a board written before
  // grading.anomaly_flags() existed (every published board to date: 0 of 38,500
  // rows carry a calc.arv_flags key at all) still lights up.
  //
  // grading.anomaly_flags() now emits the SAME two verdicts as real flag
  // strings, so on a fresh board both fire and the reader would be told the
  // identical thing twice — "ARV over $2M" and "the ARV is above $2M". `seen`
  // only dedupes by NAME, and these are different names for one fact, so the
  // server-side flag wins and the local recompute stays silent. Levels are
  // identical either way; this only decides which sentence is shown.
  if (typeof arv === "number" && arv > 2000000) {
    lvl = _LVL.bad;
    if (!seen.arv_above_plausible_max) {
      hits.push({ rank: _LVL.bad, flag: "arv_over_2m", subject: "arv",
        why: "ARV over $2M — the grader already refuses to rate this as a deal", note: "" });
    }
  }
  if (typeof c.roi_pct === "number" && c.roi_pct > 400) {
    lvl = _LVL.bad;
    if (!seen.arv_implies_implausible_roi) {
      hits.push({ rank: _LVL.bad, flag: "roi_over_400", subject: "arv",
        why: "ROI over 400% — implausible, so the ARV behind it is not trustworthy", note: "" });
    }
  }
  if (lvl === 0 && c.arv_confidence === "LOW") lvl = _LVL.proxy;

  // Why there is no ARV. An empty cell reads as "not computed yet", which is
  // the one thing it must never mean on a lead the engine priced and rejected.
  //
  // "refused" needs REAL evidence, not merely a hit: 12,412 leads have no ARV
  // because there was never enough data to build one ("Insufficient data for
  // ARV"), and they still carry low_arv_confidence / no_sqft. Keying off any
  // hit at all painted every one of them red. Only a distrust-level reason —
  // calc's own arv_flags, or a weak/bad flag from the layers above — means the
  // engine priced this lead and then refused the answer.
  // `!arv`, not `arv == null`: an arv_expected of 0 is not a valuation, and the
  // whole pipeline already treats it as absent (every downstream block in
  // valuation/calc.py is written `if out.arv_expected`). One lead on the live
  // board carries a literal 0 — 599 Sunset Point Drive, Oconee SC — and a
  // truthiness mismatch here would render it as an empty warning glyph.
  let absent = "";
  if (!arv) {
    // "calc.arv_flags is non-empty" was the proxy for "the engine priced this
    // and then refused the answer". That held while every name in the list was
    // a claim about the ARV. It stopped holding the moment calc.py started
    // writing rehab_not_deducted there — a flag about the max bid, carried in
    // arv_flags only so this file's rehabTrust() can see it (see
    // _ARV_IGNORED_FLAGS). A lead with no ARV whose ONLY entry is that one has
    // not been refused anything, and calling it "refused" paints a red "the
    // engine computed one and refused it" over a lead that was simply never
    // valued — the exact misreading arv_not_computed was added to prevent.
    // So: only flags this file recognises as ARV claims count as evidence of a
    // refusal. Ignored names are still ignored, unknown names still count.
    const arvClaims = Array.isArray(c.arv_flags)
      ? c.arv_flags.filter((f) => !_ARV_IGNORED_FLAGS[String(f || "").toLowerCase()])
      : [];
    const refused = arvClaims.length > 0 || hits.some((h) => h.rank >= _LVL.weak);
    absent = c.arv_withheld != null ? "withheld" : refused ? "refused" : "unpriced";
    if (absent !== "unpriced" && lvl < _LVL.bad) lvl = _LVL.bad;
  }

  // The clean, priced lead — most of what a good board is — keeps sharing one
  // frozen object rather than allocating 38,500 of them on a phone.
  if (lvl === 0 && !absent) return _memo(l, "_arvTrust", _ARV_TRUST_OK);

  hits.sort((a, b) => b.rank - a.rank);   // worst reason first
  // The severity names restate calc's verdict, they do not add a reason: a
  // reader told "cama class mismatch; comp kind mismatch; the pipeline
  // classified this as contradicted; max bid and ROI were withheld; a sanity
  // flag exists" has been given two facts and three ways of saying "flagged".
  // They still set the LEVEL above — that is the whole point of reading them —
  // but they only get to SPEAK when calc named nothing specific, which is
  // exactly the stale-board / wrong-order case they exist for.
  const specific = hits.filter((h) => !_ARV_GENERIC_FLAGS[h.flag]);
  const spoken = specific.length ? specific : hits;
  const top = spoken[0];
  // "bid" only when EVERY reason loud enough to speak is bid-scoped. One real
  // ARV reason anywhere on the lead and the headline goes back to the ARV,
  // because that is the number the reader is about to bid off.
  const loud = hits.filter((h) => h.rank >= _LVL.weak);
  const out = {
    level: _LVL_NAME[lvl],
    why: spoken.filter((h) => h.rank >= _LVL.weak).map((h) => h.why),
    flags: spoken.filter((h) => h.rank >= _LVL.weak).map((h) => h.flag),
    notes: hits.map((h) => h.note).filter(Boolean),
    absent,
    short: top && top.rank >= _LVL.weak ? top.flag.replace(/_/g, " ") : "",
    subject: loud.length && loud.every((h) => h.subject === "bid") ? "bid" : "arv",
  };
  // An absent ARV gets calc's own explanation even when no FLAG carried a note
  // — "Insufficient land data for ARV" is the whole answer on 548 of the 553
  // refused leads, and on the 12,412 unpriced ones "Insufficient data for ARV"
  // is the difference between "—" meaning something and "—" meaning nothing.
  if (absent && !out.notes.length && Array.isArray(c.notes)) {
    for (let i = 0; i < c.notes.length; i++) {
      if (typeof c.notes[i] === "string" && _ARV_ABSENT_NOTE.test(c.notes[i])) {
        out.notes = [c.notes[i]];
        break;
      }
    }
  }
  if (!out.why.length && lvl >= _LVL.weak) {
    out.why = [absent === "unpriced" ? "" : "failed a valuation sanity check"].filter(Boolean);
  }
  return _memo(l, "_arvTrust", out);
}

/** Tooltip text for a flagged ARV. Plain, and it never claims more than it knows. */
function arvTrustTitle(t) {
  if (!t || t.level === "ok") return "";
  if (t.level === "proxy") {
    return "Proxy ARV — estimated without usable comps or a known square footage. "
      + "Treat it as a rough band, not a value.";
  }
  // Lowercase on purpose: every use below puts it after a colon, mid-sentence.
  // The note boxes, which put it after a full stop, run it through _cap().
  const why = t.why.length ? t.why.join("; ") : "failed a valuation sanity check";
  const detail = t.notes.length ? "\n\nThe engine's own note: " + t.notes.join("\n") : "";
  if (t.absent === "withheld" || t.absent === "refused") {
    return "No ARV published — the engine computed one and refused it: " + why
      + ". Max bid, ROI and profit are blank on purpose, not missing." + detail;
  }
  if (t.level === "weak") {
    if (t.subject === "bid") {
      // Nothing here doubts the ARV. Saying "ARV unverified" would point the
      // reader at the wrong number — see _ARV_BID_FLAGS.
      return "The opening bid is a placeholder, not the real cost: " + why
        + ". The ARV itself is not disputed, but ROI, profit and bid/ARV are "
        + "measured against that bid, and no deal verdict is published." + detail;
    }
    return "ARV unverified — treat it as a band, not a number: " + why
      + ". Max bid and ROI below are the same number restated, so they carry the "
      + "same doubt, and no deal verdict is published." + detail;
  }
  return "ARV flagged as unreliable — do not bid off this number: " + why
    + ". Max bid and ROI are derived from it and are discounted for the same reason."
    + detail;
}

/**
 * The ARV cell for the table.
 *
 * An absent ARV used to render `<td class="num"></td>` — visually identical to
 * a lead nobody has priced. Measured on a full recompute: 553 leads had no ARV,
 * no `arv_withheld` and a live calc flag, and 374 of them rendered that empty
 * cell (2085 SOUTHPORT RD among them). Absence is now always explicit and
 * always carries its reason.
 */
function arvCell(c, t) {
  const title = _attr(arvTrustTitle(t) || "No ARV computed for this lead.");
  const v = c.arv_expected;
  if (!v) {   // 0 is not a valuation — see the `!arv` note in arvTrust()
    if (t.absent === "withheld") {
      return `<td class="num dq-arv-bad" title="${title}"><span class="dq-arv-mark">&#9888;&#xFE0E;</span>withheld</td>`;
    }
    if (t.absent === "refused") {
      return `<td class="num dq-arv-bad" title="${title}"><span class="dq-arv-mark">&#9888;&#xFE0E;</span>not published</td>`;
    }
    // Genuinely unpriced. Still not blank: a blank cell is indistinguishable
    // from a render failure, and the reason (calc's own note) is worth a hover.
    const why = t.notes.length ? t.notes[0] : "No ARV computed — not enough data to value this property.";
    return `<td class="num dq-none" title="${_attr(why)}">&mdash;</td>`;
  }
  if (t.level === "bad") {
    return `<td class="num dq-arv-bad" title="${title}"><span class="dq-arv-mark">&#9888;&#xFE0E;</span>${fmtMoney(v)}</td>`;
  }
  if (t.level === "weak") {
    return `<td class="num dq-arv-weak" title="${title}">&#8776;${fmtMoney(v)}</td>`;
  }
  if (t.level === "proxy") {
    return `<td class="num dq-arv-proxy" title="${title}">~${fmtMoney(v)}</td>`;
  }
  return `<td class="num">${fmtMoney(v)}</td>`;
}

/**
 * Money derived from the ARV.
 *
 * "bad": dimmed and labelled. "weak": the number is real but it is a band, so
 * it renders in the caveat colour with a "≈" and says why on hover — a plain
 * black $947,700 next to an ARV the engine has already doubted is the specific
 * thing this round is closing (16,310 leads publish a max bid and an ROI off a
 * flagged ARV; 287 of them are max bids of $500,000 or more).
 */
function derivedCell(inner, t) {
  if (!inner) return `<td class="num"></td>`;
  if (t.level === "bad") {
    return `<td class="num dq-dim" title="${_attr("Derived from an ARV flagged as unreliable. " + arvTrustTitle(t))}">${inner}</td>`;
  }
  if (t.level === "weak") {
    return `<td class="num dq-soft" title="${_attr(arvTrustTitle(t))}">&#8776;${inner}</td>`;
  }
  return `<td class="num">${inner}</td>`;
}

/**
 * The max-bid cell. derivedCell() plus the rehab question, because the rehab
 * question is about THIS number and nothing else.
 *
 * 70% rule = ARV × 0.70 − rehab. On 9,190 of the 21,847 published max bids
 * there was no rehab estimate, so the subtraction was of zero and the cell is a
 * pre-repair ceiling wearing the clothes of a bid. That does not belong in a
 * notes line at the bottom of a panel; it belongs on the figure, in the column
 * a bidder reads across. The marker is "†" — deliberately not "⚠" or "≈", both
 * of which already mean something specific about the ARV in this file, and a
 * fourth meaning on the same two glyphs is how a warning stops being read.
 *
 * The 10,063 LAND rows are left completely alone: a vacant parcel correctly
 * deducts no rehab, and a caveat on a number that is right is how the caveat on
 * numbers that are wrong becomes wallpaper.
 */
function maxBidCell(c, t, l) {
  const cell = derivedCell(fmtMoney(c.max_bid_70), t);
  if (c.max_bid_70 == null || rehabTrust(l).state !== "unknown") return cell;
  const ttl = _attr(REHAB_UNKNOWN_NOTE);
  return cell
    .replace('<td class="num', '<td class="num rehab-unknown')
    .replace("</td>", `<span class="rehab-dag" title="${ttl}">&dagger;</span></td>`);
}

/**
 * A few words naming why the valuation is caveated, for a card chip or a badge.
 * Falls back to the level when calc named no flag (the $2M / 400% layer).
 */
function arvShortWhy(t) {
  if (!t || t.level === "ok" || t.level === "proxy") return "";
  if (t.level === "weak" && t.subject === "bid" && !t.short) return "placeholder opening bid";
  return t.short || (t.level === "bad" ? "sanity check failed" : "unverified");
}

/**
 * The headline for the WEAK tier, in three lengths. One helper so the chip, the
 * badge and the detail note can never drift apart — and so the bid-scoped case
 * says "bid" in all three places instead of two out of three.
 *
 *   chip  — a card chip, room for four words
 *   badge — the detail-panel quick badge
 *   note  — the bold lead-in of the note box under the big number
 */
function arvWeakLabel(t, form) {
  if (t && t.subject === "bid") {
    if (form === "chip") return "&#8776; Placeholder bid";
    if (form === "badge") return "≈ Opening bid is a placeholder — ROI and profit rest on it";
    return "The opening bid is a placeholder, not the real cost.";
  }
  if (form === "chip") return "&#8776; ARV unverified";
  if (form === "badge") return "≈ ARV unverified — a band, not a number";
  return "Unverified — a band, not a number.";
}

/**
 * The rendered `data_quality.summary` line.
 *
 * The pipeline writes a full investor-readable caveat per lead and it reached
 * the CSV (`data_quality_note`) and a `title=` attribute on an address badge —
 * nowhere a reader looks. `summary` is in web_artifact._SLIM_RAW, so this works
 * on a phone.
 */
function dqSummaryLine(l) {
  const dq = (l && l.raw && l.raw.data_quality) || null;
  const s = dq && typeof dq.summary === "string" ? dq.summary.trim() : "";
  if (!s || /^OK\b/.test(s)) return "";
  const t = arvTrust(l);
  const cls = t.level === "bad" ? "dq-summary bad" : t.level === "weak" ? "dq-summary weak" : "dq-summary";
  return `<div class="${cls}"><strong>Data quality:</strong> ${_attr(s)}</div>`;
}

/**
 * The "Sold <date> · $<amount>" line for a card — E8.
 *
 * `raw.last_sale` with `basis: "assessor_value"` is the county's market value
 * as of that date, not a sale price. On 725 BRYANT RD that figure is $780,300,
 * read off an assessor row calc's own note rejects ("a 'GEN WHSE 50' — a
 * commercial building, not this single family. Parcel join looks wrong"), and
 * it printed clean beside the repaired $121,100 ARV. Measured by exact-amount
 * match against calc's notes: 236 leads print the county value calc refused and
 * 798 print the recorded sale calc refused — 1,034 cards where a rejected
 * source reappears as though it corroborated something.
 *
 * The figure is not hidden (a record does exist); it is struck through and
 * named as rejected, so it can never be read as a second opinion.
 */
const _REJECTED_FLOOR_RE = /(County market value|County value|Recorded sale) \(\$([\d,]+)\)\s*(?:NOT used as an ARV floor|not usable)/i;
function lastSaleChip(l, c) {
  const ls = (l && l.raw && l.raw.last_sale) || null;
  if (!ls || !ls.date) return "";
  const isAssessor = ls.basis === "assessor_value";
  let rejectedNote = "";
  if (ls.amount != null && c && Array.isArray(c.notes)) {
    for (let i = 0; i < c.notes.length; i++) {
      const n = c.notes[i];
      if (typeof n !== "string") continue;
      const m = _REJECTED_FLOOR_RE.exec(n);
      if (m && Math.abs(parseFloat(m[2].replace(/,/g, "")) - ls.amount) < 1) { rejectedNote = n; break; }
    }
  }
  const when = ls.date.slice(0, 7);
  if (rejectedNote) {
    return `<span class="dq-rejected" title="${_attr("This figure is the same record the valuation REFUSED to use. " + rejectedNote)}">`
      + `Sold ${when} · <s>${fmtMoney(ls.amount)}</s> &#9888;&#xFE0E; rejected by the valuation</span>`;
  }
  const title = isAssessor
    ? "county assessor market value as of the sale date (sale price not published)"
    : "last recorded sale";
  return `<span title="${_attr(title)}">Sold ${when}`
    + (ls.amount ? ` · ${fmtMoney(ls.amount)}${isAssessor ? "*" : ""}` : "") + `</span>`;
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
  :root{--dq-warn:#a8200f;--dq-warn-bg:rgba(217,45,32,.11);
        --dq-soft:#8a5a00;--dq-soft-bg:rgba(191,132,0,.13);--dq-soft-line:rgba(191,132,0,.55)}
  :root[data-theme="dark"]{--dq-warn:#ff8a7a;--dq-warn-bg:rgba(217,45,32,.22);
        --dq-soft:#e8b45e;--dq-soft-bg:rgba(232,180,94,.16);--dq-soft-line:rgba(232,180,94,.6)}
  #listings-table td.dq-arv-bad{background:var(--dq-warn-bg);color:var(--dq-warn);font-weight:700}
  #listings-table td.dq-arv-bad .dq-arv-mark{margin-right:4px;font-weight:700}
  #listings-table td.dq-arv-proxy{color:var(--muted,#6b6257)}
  #listings-table td.dq-dim{opacity:.42}
  #listings-table td.dq-dim .roi-pos,#listings-table td.dq-dim .roi-neg{color:inherit}
  /* WEAK: amber + a dotted rule, no fill. A fill on 16,310 of 38,500 rows would
     be the wallpaper that hid the real warning; colour + the "≈" is a caveat a
     reader can still scan past a screen of, and it is unmistakably neither the
     plain-black "fine" nor the red-tinted "do not bid off this". */
  #listings-table td.dq-arv-weak,#listings-table td.dq-soft{color:var(--dq-soft);
    text-decoration:underline dotted var(--dq-soft-line);text-underline-offset:3px}
  #listings-table td.dq-arv-weak{font-weight:600}
  #listings-table td.dq-soft .roi-pos,#listings-table td.dq-soft .roi-neg{color:inherit}
  #listings-table td.dq-none{color:var(--muted,#6b6257);opacity:.55}
  .dq-warn-mark{color:var(--dq-warn);font-weight:700}
  .dq-soft-mark{color:var(--dq-soft);font-weight:700}
  /* SPECIFICITY, the second time. style.css:622 sets '.card-meta span' to the
     muted colour at (0,1,1), which beats a bare '.dq-warn-mark' at (0,1,0) — so
     on the CARD the flagged-ARV chip kept its warning glyph and silently lost
     its colour, rendering the same muted grey as "1,400 sqft · 1990". Measured
     in the browser on 725 Bryant Rd: computed colour rgb(170,182,202), i.e. the
     plain meta colour, in both themes. Same for the struck-through rejected
     sale figure. '.card-meta span.x' is (0,2,1) and wins. This is the second
     silent half-deployed warning in this file's history (the first was the
     table, above); a treatment added to a NEW container needs its computed
     colour checked THERE, not only where it was first written. */
  .card-meta span.dq-warn-mark{color:var(--dq-warn)}
  .card-meta span.dq-soft-mark{color:var(--dq-soft)}
  .card-meta span.dq-rejected{color:var(--dq-warn)}
  .card-meta span.dq-rejected s{opacity:.75}
  /* .val.big carries its own colour at a higher specificity than a bare class. */
  #detail-panel .val.dq-warn-mark{color:var(--dq-warn)}
  #detail-panel .val.dq-soft-mark{color:var(--dq-soft)}
  .arv-flag-chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;
    font-weight:700;color:#fff;background:#c0392b;border:1px solid #c0392b}
  .arv-weak-chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;
    font-weight:700;color:var(--dq-soft);background:var(--dq-soft-bg);border:1px solid var(--dq-soft-line)}
  /* style.css's .qbadge.warn-light is the grade-C palette, which the detail
     panel ALSO gives to an ordinary 10-25% ROI badge — so a weak-ARV warning
     and a mediocre-but-fine return rendered in the same colour. Repaint the
     ones this file owns in the weak vocabulary (--dq-soft, same as the "≈"
     everywhere else) so the caveat is a caveat and not a middling score. */
  .qbadge.warn-light.dq-weak{color:var(--dq-soft);background:var(--dq-soft-bg);
    border:1px solid var(--dq-soft-line)}
  .arv-flag-note{margin-top:6px;padding:8px 10px;border-radius:8px;font-size:12px;line-height:1.4;
    color:var(--dq-warn);background:var(--dq-warn-bg);border:1px solid rgba(217,45,32,.35)}
  .arv-weak-note{margin-top:6px;padding:8px 10px;border-radius:8px;font-size:12px;line-height:1.4;
    color:var(--dq-soft);background:var(--dq-soft-bg);border:1px solid var(--dq-soft-line)}
  .arv-weak-note .arv-note-quote,.arv-flag-note .arv-note-quote{display:block;margin-top:4px;
    font-style:italic;opacity:.85}
  /* data_quality.summary, finally on screen instead of only in the CSV. */
  .dq-summary{margin:0 0 10px;padding:8px 10px;border-radius:8px;font-size:12px;line-height:1.45;
    color:var(--muted,#6b6257);background:rgba(127,127,127,.10);border:1px solid rgba(127,127,127,.25)}
  .dq-summary.weak{color:var(--dq-soft);background:var(--dq-soft-bg);border-color:var(--dq-soft-line)}
  .dq-summary.bad{color:var(--dq-warn);background:var(--dq-warn-bg);border-color:rgba(217,45,32,.35)}
  /* A figure the valuation refused, reprinted elsewhere on the card. */
  .dq-rejected{color:var(--dq-warn)}
  .dq-rejected s{opacity:.75}
  /* ---- Location not verified (raw.geo_imprecise) ------------------------- */
  /* The card's photo slot when the only thing available was a centroid. It has
     to look like an ABSENCE, not like a picture — the whole defect was a map
     that looked like evidence. */
  .card-img.geo-unknown{display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:4px;background:repeating-linear-gradient(45deg,rgba(127,127,127,.07) 0 10px,transparent 10px 20px);
    color:var(--dq-soft);border-bottom:1px solid var(--dq-soft-line)}
  .card-img.geo-unknown .geo-unknown-glyph{font-size:26px;opacity:.6;filter:grayscale(1)}
  .card-img.geo-unknown .geo-unknown-txt{font-size:11px;font-weight:700;letter-spacing:.02em;
    text-transform:uppercase}
  /* .geo-note / .geo-note-sm / .geo-note code are defined ONCE, below, with the
     rest of the caveat vocabulary. */
  /* NOTE — this string is a JS template literal. Do not use backticks in these
     comments; one pair ends the CSS and takes the whole file with it. Caught by
     node --check, which is the only reason it is not shipping right now. */
  /* Owner identity, the rehab dagger and the people-search link are styled in
     ONE place further down this sheet. A duplicate set of the same class names
     lived here and the two blocks were silently splitting properties between
     them — the later rule wins per PROPERTY, not per block, so .owner-src took
     its colour from one and its italics from the other. Do not re-add them. */
  /* SPECIFICITY, THE THIRD TIME IN THIS FILE. style.css's ".detail-grid .val"
     is (0,2,0) and sets the ordinary text colour; a bare ".owner-conflict" is
     (0,1,0) and LOST. Measured in the browser: computed colour rgb(230,236,247)
     — plain body text — in dark theme, so the one line telling a reader that
     two records name different owners rendered as if it were ordinary content.
     Same trap as the card meta and the table cell, both documented above. */
  #detail-panel .detail-grid .val.owner-conflict{color:var(--dq-soft)}
  /* Comps table: the distance cell renders struck through in the caveat colour
     when the subject's own coordinates are a centroid. The table already
     scrolls inside its own box on mobile (premium.css), so the added column
     cannot widen the panel — verified at 390px: table box 349px, its own
     scrollWidth 478px, document scrollWidth == clientWidth == 390. */
  .comps-table td.dq-soft{color:var(--dq-soft)}
  .comps-table td.dq-soft s{opacity:.8}
  .shard-loading{font-size:.9em;color:var(--muted,#6b6257);position:relative;padding-left:18px}
  .shard-loading::before{content:"";position:absolute;left:0;top:50%;width:11px;height:11px;
    margin-top:-6px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;
    animation:shard-spin .8s linear infinite}
  @keyframes shard-spin{to{transform:rotate(360deg)}}
  @media (prefers-reduced-motion:reduce){.shard-loading::before{animation:none}}
  /* ---- Location honesty (geoTrust) ---------------------------------------
     The card photo slot, the mini-map banner and the comps distance note all
     emit these. They were shipping with NO rule anywhere, which renders the
     photo slot as two lines of unstyled 40px text and the banner as bare body
     copy — a warning that looks like a rendering accident is not a warning.
     They live here, with the rest of the caveat vocabulary, so they reuse the
     same --dq-soft amber as "≈" and the weak-ARV notes rather than inventing a
     third colour for "do not trust this". */
  .geo-note{margin:0 0 8px;padding:8px 10px;border-radius:8px;font-size:12px;line-height:1.45;
    color:var(--dq-soft);background:var(--dq-soft-bg);border:1px solid var(--dq-soft-line)}
  .geo-note code{font-size:11px;padding:0 3px;border-radius:3px;background:rgba(127,127,127,.18)}
  .geo-note-sm{font-size:11px;padding:6px 8px;margin-bottom:6px}
  /* .card-img.no-photo is flex/centred at 40px — override both, and stripe the
     tile so it never reads as a photo that failed to load. */
  .card-img.no-photo.geo-unknown{flex-direction:column;gap:5px;font-size:11px;color:var(--dq-soft);
    background:repeating-linear-gradient(45deg,rgba(127,127,127,.06) 0 11px,rgba(127,127,127,.14) 11px 22px)}
  .card-img.no-photo.geo-unknown .geo-unknown-glyph{font-size:28px;line-height:1;opacity:.65;filter:grayscale(1)}
  .card-img.no-photo.geo-unknown .geo-unknown-txt{font-size:11px;font-weight:700;letter-spacing:.02em;
    text-align:center;padding:0 8px}
  /* The comps table gained a Dist column; 7 columns does not fit 390px. Scroll
     the table, never the page. */
  #d-comps,#d-rent,#d-fc-comps{overflow-x:auto}
  /* ---- A max bid with no rehab deducted (rehabTrust) ----------------------
     Rendered ON the number in all three places it appears, because a bidder
     reads the figure and not the notes under it. Class names here MUST be the
     ones maxBidCell() / the calc row / the badge actually emit — rehab-unknown,
     rehab-dag, rehab-note. (They were briefly bid-norehab* here and rehab-* in
     the markup, i.e. a silent no-op: the dagger rendered as unstyled body text.
     Same reader/writer mismatch this file has been bitten by four times.) */
  .rehab-dag{color:var(--dq-soft);font-weight:700;margin-left:3px;cursor:help}
  /* Colour AND a dotted rule. The colour alone is the whole marker in a
     monochrome print or for a colour-blind reader, and this cell is a dollar
     figure someone bids against. */
  #listings-table td.rehab-unknown{color:var(--dq-soft);
    text-decoration:underline dotted var(--dq-soft-line);text-underline-offset:3px}
  #listings-table td.rehab-unknown .rehab-dag{margin-left:2px;text-decoration:none}
  .qbadge.rehab-unknown{border-color:var(--dq-soft-line)}
  .rehab-note{margin-top:5px;padding:6px 8px;border-radius:6px;font-size:11px;line-height:1.4;
    color:var(--dq-soft);background:var(--dq-soft-bg);border:1px solid var(--dq-soft-line)}
  #detail-panel .val .rehab-dag{font-size:.6em;vertical-align:super}
  /* ---- Owner identity (ownerNames) + people-search ------------------------
     Names MUST match the markup in renderDetail's Owner & Contact block:
     owner-src, owner-conflict, owner-conflict-why, skiptrace-row, skiptrace-why. */
  .owner-src{font-size:11px;opacity:.75;font-style:italic;white-space:nowrap}
  .owner-conflict{color:var(--dq-soft)}
  .owner-conflict-why{margin-top:4px;font-size:11px;line-height:1.4;font-style:normal}
  .skiptrace-row{grid-column:1 / -1;margin-top:8px;padding-top:8px;
    border-top:1px solid var(--border-subtle,rgba(127,127,127,.25));font-size:12.5px}
  .skiptrace-row a{font-weight:600;text-decoration:none;color:var(--accent-2,#2563eb)}
  .skiptrace-row a:hover{text-decoration:underline}
  .skiptrace-why{margin-top:3px;font-size:11px;line-height:1.4;color:var(--dq-soft)}
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
      // "weak" gets its own mark for the same reason: below 720px the ARV, Max
      // Bid and ROI columns are all hidden, so the amber "≈" on those cells is
      // invisible on a phone. "≈" is one vocabulary across this file — it means
      // "a band, not a number" wherever it appears.
      const arvMark = at.level === "bad"
        ? `<span class="dq-warn-mark" title="${_attr(arvTrustTitle(at))}">&#9888;&#xFE0E; </span>`
        : at.level === "weak"
          ? `<span class="dq-soft-mark" title="${_attr(arvTrustTitle(at))}">&#8776; </span>`
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
        (!g.overall && (at.level === "bad" || at.level === "weak"))
          ? `<span class="grade-badge F ${at.level === "bad" ? "dq-warn-mark" : "dq-soft-mark"}" style="opacity:.85" title="${_attr("Unrated on purpose — " + arvTrustTitle(at))}">—</span>`
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
      ${maxBidCell(c, at, l)}
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
  "property_category","child_support",
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

// ===========================================================================
// THE CARD PHOTO SLOT — what is allowed to sit in it.
//
// The slot's own contract is written on the geo-unknown branch below: "whatever
// is in it reads as THIS IS THE PROPERTY". That branch already refuses to draw
// a pushpin map on a coordinate this file does not trust. The branch ABOVE it
// did not, and `raw.zillow.photo` is not always a photograph.
//
// MEASURED on docs/listings.json, 38,500 records, 2026-08-11:
//   27,710 leads fill this slot from raw.zillow.photo
//    4,069 of those are a real photograph      (ap./p./nh.rdcpix.com)
//   23,641 of those are a SATELLITE MAP TILE   (server.arcgisonline.com,
//          .../World_Imagery/MapServer/tile/{z}/{y}/{x}, all of them zoom 19)
//   16,728 of the tiles sit on a coordinate geoTrust() already accepts — those
//          are unchanged by this function and keep the tile
//    6,426 of the tiles sit on a coordinate geoTrust() calls IMPRECISE: a city
//          or county centroid, typically 1-2 miles from the property and
//          frequently a courthouse lawn or a town square
//
// Those 6,426 are the defect. A zoom-19 aerial computed from the lead's own
// lat/lng is the SAME claim the pushpin makes — "the property is here" — and it
// is a worse version of it, because it is photographic and therefore reads as
// evidence rather than as a diagram. It arrives uncaptioned in the one slot on
// the card that means "this is the house".
//
// So the gate is the same gate, applied one branch higher.
//
// WHAT REPLACES IT. raw.images.real is the assessor/listing photo channel
// (enrichment_assessor_photo.py writes `["parcel_photos/<county>_<parcel>.jpg"]`,
// the listing scrapers write rdcpix / landwatch URLs). It is NOT a trustworthy
// name on its own: of the 5,808 leads in this cohort that HAVE an images.real,
// 5,665 of the values are themselves arcgisonline tiles — the same lie under a
// different key. So every candidate is classified, not trusted by field name.
// After classification 143 of the 6,426 yield a genuine photograph and 6,283
// fall through to the honest empty state.
//
// raw.images is NOT in web_artifact._SLIM_RAW, so a phone has no images block
// at grid-render time (the shard that carries it is fetched when a lead is
// OPENED, long after these cards paint). That is read defensively here rather
// than worked around: on LEAN the cohort simply takes the empty state, which is
// the honest answer, never a wrong one.
// ===========================================================================

// A URL that was COMPUTED FROM A COORDINATE — a tile or static map, not a
// photograph of a building. Hosts measured on the live board; the openstreetmap
// and googleapis arms cover the static-map URL this same function's callers
// build, so a future writer that stores one into raw.zillow.photo is caught.
const _DERIVED_IMG_RE = /(server\.arcgisonline\.com|staticmap\.openstreetmap|tile\.openstreetmap\.org|maps\.googleapis\.com\/maps\/api\/staticmap|api\.mapbox\.com\/styles)/i;

/** True when `u` is a real photograph rather than a map/satellite tile. */
function isPhotograph(u) {
  return typeof u === "string" && !!u && !_DERIVED_IMG_RE.test(u);
}

/**
 * First photographic URL in a raw.images value. The channel is written as a
 * LIST by enrichment_assessor_photo (`images["real"] = [rel]`) and as a bare
 * string by other writers, so both shapes are read.
 */
function _firstPhoto(v) {
  if (Array.isArray(v)) {
    for (let i = 0; i < v.length; i++) if (isPhotograph(v[i])) return v[i];
    return "";
  }
  return isPhotograph(v) ? v : "";
}

/**
 * A genuine photograph for this lead from raw.images, or "".
 *
 * Order is provenance order, best first: `real` is the assessor/listing photo
 * the enricher went and fetched, `primary` is whatever that enricher chose to
 * lead with, `streetview`/`street` is a Street View frame — a photograph, but
 * of a location, so it is last.
 */
function realPropertyPhoto(l) {
  const im = l && l.raw && l.raw.images;
  if (!im || typeof im !== "object" || Array.isArray(im)) return "";
  return _firstPhoto(im.real) || _firstPhoto(im.primary)
      || _firstPhoto(im.streetview) || _firstPhoto(im.street);
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
      } else if (l.raw && l.raw.zillow && l.raw.zillow.photo
                 && (isPhotograph(l.raw.zillow.photo) || !geoTrust(l).imprecise)) {
        // UNCHANGED PATH, now with the gate spelled out. Two populations reach
        // here and both are legitimate: a real photograph (4,069 leads — a
        // photograph makes no claim about coordinates, so geo trust is
        // irrelevant to it), and a satellite tile on a coordinate geoTrust()
        // accepts (16,728). Neither is touched.
        photo = `<div class="card-img" style="background-image:url('${l.raw.zillow.photo}')"></div>`;
      } else if (l.raw && l.raw.zillow && l.raw.zillow.photo && realPropertyPhoto(l)) {
        // GATED, and REPLACED. The stored image is a tile computed from a
        // coordinate this file does not trust — but a genuine photograph of the
        // property exists in raw.images. 143 of the 6,426 land here. The photo
        // is honest (it depicts a building, it does not assert a location); the
        // title says where it came from so it is never mistaken for a fresh
        // capture.
        const _rp = realPropertyPhoto(l);
        photo = `<div class="card-img" style="background-image:url('${_rp}')" `
          + `title="${_attr("County assessor / listing photo. The satellite tile this record stored was discarded: " + geoTrust(l).why + ", so an aerial computed from it would picture the wrong place.")}"></div>`;
      } else if (l.raw && l.raw.zillow && l.raw.zillow.photo) {
        // GATED, and EMPTY. A satellite tile of an untrusted point, and no
        // photograph to put in its place. 6,283 of the 6,426 land here (every
        // one of them on a phone, where raw.images has not arrived yet).
        // The empty state is the same one the map branch already uses, because
        // it is the same fact: this file does not know where this property is.
        const _gtp = geoTrust(l);
        photo = `<div class="card-img no-photo geo-unknown photo-unverified" title="${_attr("No photo of this property. The image on this record is a satellite tile computed from its coordinates, and " + _gtp.why + " — so the tile pictures somewhere this property is not. It is not shown.")}">`
          + `<span class="geo-unknown-glyph">🛰</span>`
          + `<span class="geo-unknown-txt">no verified photo</span></div>`;
      } else if (l.latitude && l.longitude && !geoTrust(l).imprecise) {
        const staticUrl = `https://staticmap.openstreetmap.de/staticmap.php?center=${l.latitude},${l.longitude}&zoom=17&size=400x250&markers=${l.latitude},${l.longitude},red-pushpin`;
        photo = `<div class="card-img" style="background-image:url('${staticUrl}')"></div>`;
      } else if (l.latitude && l.longitude) {
        // GATED. This slot is the PHOTO slot: whatever is in it reads as "this
        // is the property". A zoom-17 street map with a red pushpin is the most
        // specific claim the card can make about where a lead is, and on 8,387
        // of the leads that reach this branch the pin is a city or county
        // centroid — a landmark 1-2 miles away, frequently a courthouse or a
        // town square. Nothing said so, and there is no more convincing way to
        // tell someone a wrong address is right than to draw it on a map.
        //
        // The verified-geo leads (287 of 8,674 here) keep the map. This is the
        // gate, not a removal.
        const gt = geoTrust(l);
        photo = `<div class="card-img no-photo geo-unknown" title="${_attr("Location not verified — " + gt.why + ". No map is drawn because a pin would name a place this property is not.")}">`
          + `<span class="geo-unknown-glyph">📍</span>`
          + `<span class="geo-unknown-txt">location not verified</span></div>`;
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
      const weakArv = at.level === "weak";
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
        signalChips.push(`<span class="arv-flag-chip" title="${_attr(arvTrustTitle(at))}">&#9888;&#xFE0E; ARV flagged${arvShortWhy(at) ? " · " + arvShortWhy(at) : ""}</span>`);
      } else if (weakArv) {
        // The reason, not just the severity. 94 Long Ridge Road publishes a
        // $947,700 max bid off an ARV whose only flag is land_comps_rejected —
        // and calc's own note says "none within 5x the subject's 2.60 ac". The
        // chip names it; the tooltip quotes the note verbatim.
        signalChips.push(`<span class="arv-weak-chip" title="${_attr(arvTrustTitle(at))}">${arvWeakLabel(at, "chip")}${arvShortWhy(at) ? " · " + arvShortWhy(at) : ""}</span>`);
      }
      // (0c) Stamped-value cluster on a comp-grounded ARV — the 255 leads that
      //      keep every dollar. The panel says it in full; the card says it too,
      //      because the card is where a bid list gets built and 11 of these
      //      carry a live max bid. Amber, like the weak chip beside it: the
      //      unverified record is the COUNTY's, not this valuation.
      const _csc = stampCluster(l);
      if (_csc.inCluster && !_csc.arvDerivedFromStamp) {
        signalChips.push(`<span class="arv-weak-chip" title="${_attr(STAMP_CLUSTER_NOTE)}">🧬 county value stamped across parcels</span>`);
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
            ${(l.raw && l.raw.property_category) ? '<span class="cat-badge" style="background:'+({"foreclosure":"#e74c3c","preforeclosure":"#f39c12","tax_delinquency":"#9b59b6","distressed_property":"#3498db"}[l.raw.property_category.category]||"#7f8c8d")+';color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;text-transform:uppercase;">'+l.raw.property_category.category.replace(/_/g," ")+'</span>' : ""}
            ${fmtType(l.listing_type)}
            ${l.opening_bid ? `<span>Bid ${fmtMoney(l.opening_bid)}</span>` : ""}
            ${c.arv_expected
              ? `<span${badArv ? ` class="dq-warn-mark" title="${_attr(arvTrustTitle(at))}"` : weakArv ? ` class="dq-soft-mark" title="${_attr(arvTrustTitle(at))}"` : ""}>ARV ${badArv ? "&#9888;&#xFE0E; " : weakArv ? "&#8776;" : ""}${fmtMoney(c.arv_expected)}${lowArv ? " (proxy)" : ""}</span>`
              : (at.absent === "withheld" || at.absent === "refused"
                  ? `<span class="dq-warn-mark" title="${_attr(arvTrustTitle(at))}">ARV &#9888;&#xFE0E; ${at.absent === "withheld" ? "withheld" : "not published"}</span>`
                  : "")}
            ${lastSaleChip(l, c)}
            ${l.sale_date ? `<span>${fmtDate(l.sale_date)}</span>` : ""}
            ${meta.length ? `<span>${meta.join(" · ")}</span>` : ""}
          </div>
          ${(l.raw && l.raw.also_seen_in && l.raw.also_seen_in.length) ? `<div class="card-sources" style="font-size:11px;opacity:.7;margin-top:2px">also at: ${l.raw.also_seen_in.map((s) => `<a href="${s.url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${(s.source || "source").split(".").pop()}</a>`).join(", ")}</div>` : ""}
          ${roi == null ? "" : badArv
            ? `<div class="card-roi" style="opacity:.5;font-weight:600" title="ROI withheld — it is derived from an ARV flagged as unreliable">ROI — <span style="font-weight:400">unreliable ARV</span></div>`
            : weakArv
              // Kept, because the pipeline keeps it and blanking two thirds of
              // the board's economics would delete the board — but it renders
              // in the caveat colour with "≈" and says why, so it can never be
              // read as plain fact.
              ? `<div class="card-roi" style="color:var(--dq-soft);font-weight:600" title="${_attr(arvTrustTitle(at))}">ROI &#8776;${roi.toFixed(1)}%${c.cash_on_cash_pct != null ? ` · CoC &#8776;${c.cash_on_cash_pct.toFixed(0)}%` : ""} <span style="font-weight:400">— band, not a number</span></div>`
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
  // applied: Map<listing, {keys: string[], subs: {[key]: string[]}}> — whole keys
  // the shard added, and sub-keys it deepened INTO a block slim already owns.
  // Eviction must undo each at its own granularity; see _shardMerge.
  lru: [],
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
    // Undo at the SAME granularity it was applied — see _shardMerge. Deleting
    // the whole key here would take slim's own sub-tuple with it, leaving the
    // record worse than before the shard ever loaded.
    gone.applied.forEach((rec, li) => {
      const raw = li && li.raw;
      if (!raw || !rec) return;
      const keys = rec.keys || [];
      for (let i = 0; i < keys.length; i++) delete raw[keys[i]];
      const subs = rec.subs || {};
      for (const k in subs) {
        if (!Object.prototype.hasOwnProperty.call(subs, k)) continue;
        const blk = raw[k];
        if (!_isPlainObj(blk)) continue;
        const sk = subs[k];
        for (let i = 0; i < sk.length; i++) delete blk[sk[i]];
      }
    });
    gone.applied = new Map();
    gone.data = null;
  }
}

function _shardEntry(key) {
  for (let i = 0; i < _SHARD.lru.length; i++) if (_SHARD.lru[i].key === key) return _SHARD.lru[i];
  return null;
}

function _isPlainObj(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

/**
 * Merge one detail record into one listing, recording exactly what was added so
 * eviction can take it back out again.
 *
 * The shard NEVER overwrites a value the board already carries: it is a
 * derivative, the board is authoritative, and "put it back how you found it" is
 * only possible for what we ourselves put there.
 *
 * But "already carries the KEY" is not the same as "already carries the BLOCK",
 * and conflating the two silently cost mobile every sub-key slim drops. The slim
 * projector emits an allowlisted block whenever the source has it, even when no
 * sub-key survives, and several blocks are allowlisted down to a sub-tuple
 * (zillow -> photo, gis -> owner, signal_stack -> count, ...). So the key was
 * ALWAYS already present, this function skipped it, and the shard's full copy
 * was never applied. Measured on the live board at 375x812: zillow.description
 * 0/10 leads, gis.mailing 0/10, signal_stack.signals 0/10, corroboration.sources
 * 0/10 — 50,459,084 of 216,924,819 shard bytes (23.3%) were unreachable
 * duplicates being shipped to phones that could never read them.
 *
 * So: an absent key is assigned whole; a present PLAIN-OBJECT block is DEEPENED
 * with only the sub-keys the record lacks. Anything else (arrays, scalars, a
 * type mismatch between the two sides) is left strictly alone.
 *
 * `applied` therefore records at two granularities — {keys, subs} — because
 * eviction has to undo a deepening without deleting the block slim owns.
 */
function _shardMerge(li, d, entry) {
  const raw = li.raw || (li.raw = {});
  const added = [];                       // whole keys this shard put on the record
  const deepened = Object.create(null);   // key -> sub-keys put INTO a block slim owns
  for (const k in d) {
    if (!Object.prototype.hasOwnProperty.call(d, k)) continue;
    const val = d[k];
    if (!Object.prototype.hasOwnProperty.call(raw, k)) {
      raw[k] = val;
      added.push(k);
      continue;
    }
    const cur = raw[k];
    if (!_isPlainObj(val) || !_isPlainObj(cur)) continue;
    const subs = [];
    for (const sk in val) {
      if (!Object.prototype.hasOwnProperty.call(val, sk)) continue;
      if (Object.prototype.hasOwnProperty.call(cur, sk)) continue;
      cur[sk] = val[sk];
      subs.push(sk);
    }
    if (subs.length) deepened[k] = subs;
  }
  entry.applied.set(li, { keys: added, subs: deepened });
}

/**
 * Merge one lead from a shard body ALREADY held in the LRU. No network, no
 * gunzip, no JSON.parse — the bytes are in `entry.data` and stay there until
 * eviction, which is the whole reason the LRU exists.
 *
 * Returns false when the shard is not resident (so the caller fetches) or when
 * the resident body has no record at this index (so the caller can try the
 * other shard-naming convention rather than concluding "no detail exists").
 *
 * `entry.data` is nulled by _shardTouch on eviction, so a resident-but-evicted
 * entry correctly reports false.
 */
function _shardMergeFromCache(l, i, size, key) {
  const entry = _shardEntry(key);
  if (!entry || !entry.data) return false;
  const rec = shardRecordAt(entry.data, entry.start, i, size);
  if (rec === undefined) return false;
  _shardMerge(l, rec, entry);
  _shardTouch(entry);
  return true;
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
  // The block is ALREADY IN MEMORY — a different lead in the same 1,000-record
  // shard pulled it. Only `applied.has(l)` was checked, so every tap on a lead
  // whose neighbour had been opened re-fetched, re-inflated and re-parsed the
  // whole shard on the main thread. Measured on the live board: 8 taps inside
  // shard 0 = 8 fetches, 3,945 ms total (~493 ms each). Shard 0 is board
  // indices 0-999, i.e. the top of the default sort, so this is the first thing
  // anyone does. The LRU held the data the whole time; this was a lookup bug,
  // not a caching one.
  if (_shardMergeFromCache(l, i, size, key)) return true;

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

  // Category badge
  const pc = (l.raw && l.raw.property_category) ? l.raw.property_category : null;
  const cs = (l.raw && l.raw.child_support) ? l.raw.child_support : null;
  const hoa = (l.raw && l.raw.rod) ? l.raw.rod.has_hoa_lien : false;
  let catBadge = "";
  if (pc) {
    const catColors = {"foreclosure":"#e74c3c","preforeclosure":"#f39c12","tax_delinquency":"#9b59b6","distressed_property":"#3498db"};
    const cc = catColors[pc.category] || "#7f8c8d";
    catBadge = ' <span class="cat-badge" style="background:'+cc+';color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;">'+pc.category.replace(/_/g," ")+'</span>';
    if (pc.subcategory && pc.subcategory !== pc.category) {
      catBadge += ' <span class="cat-sub" style="color:#888;font-size:11px;">'+pc.subcategory.replace(/_/g," ")+'</span>';
    }
  }
  let extraFlags = "";
  if (cs && cs.flag) extraFlags += ' <span class="cs-flag" style="background:#c0392b;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;">CHILD SUPPORT</span>';
  if (hoa) extraFlags += ' <span class="hoa-flag" style="background:#8e44ad;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;">HOA LIEN</span>';
  $("d-title").innerHTML = (l.listing_type || "listing").replace(/_/g, " ")+" — "+(l.county || "")+" County"+catBadge+extraFlags;
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
    // data_quality.summary reached the CSV export and a title= attribute and
    // nowhere else. It is the one place the pipeline writes the whole caveat in
    // plain words, so it opens the block the numbers live in.
    const _dqLine = dqSummaryLine(l);
    if (_dqLine) rows.push(_dqLine);
    // calc's own explanation of the flags, quoted rather than paraphrased.
    const _quote = _at.notes.length
      ? `<span class="arv-note-quote">The engine's note: ${_at.notes.map(_attr).join("<br>")}</span>` : "";
    // The big number carries the caveat itself. A note further down the panel
    // loses to a $780,300 in 28px type — the number anchors first and the prose
    // arrives after the reader has already decided.
    if (c.arv_expected || _at.level === "bad" || _at.level === "weak") {
      const _absentWord = _at.absent === "withheld" ? "withheld"
        : _at.absent === "refused" ? "not published" : "unverified";
      rows.push(`
        <div class="calc-row">
          <div class="lbl">Est. ARV</div>
          <div>
            <div class="val big${_at.level === "bad" ? " dq-warn-mark" : _at.level === "weak" ? " dq-soft-mark" : ""}">${
              _at.level === "bad" ? "&#9888;&#xFE0E; " : _at.level === "weak" ? "&#8776;" : _at.level === "proxy" ? "~" : ""
            }${c.arv_expected ? fmtMoney(c.arv_expected) : _absentWord}</div>
            ${c.arv_expected ? `<div class="calc-range">range: <b>${fmtMoney(c.arv_low)}</b> – <b>${fmtMoney(c.arv_high)}</b></div>` : ""}
            ${_at.absent === "withheld" || _at.absent === "refused"
              ? `<div class="arv-flag-note"><strong>No ARV published — the engine computed one and refused it.</strong> ${
                  _at.why.length ? _cap(_attr(_at.why.join("; "))) : "It failed a valuation sanity check"
                }. Max bid, ROI and profit are blank on purpose, not missing.${_quote}</div>`
              : _at.level === "bad"
                ? `<div class="arv-flag-note"><strong>Do not bid off this number.</strong> ${
                    _at.why.length ? _cap(_attr(_at.why.join("; "))) : "It failed a valuation sanity check"
                  }. Max bid, ROI and profit below are all derived from it.${_quote}</div>`
                : _at.level === "weak"
                  ? `<div class="arv-weak-note"><strong>${arvWeakLabel(_at, "note")}</strong> ${
                      _cap(_attr(_at.why.join("; ")))
                    }. ${_at.subject === "bid"
                      ? "The ARV itself is not disputed. The figures below are still shown, but ROI, profit and bid/ARV are measured against that placeholder bid and no deal verdict is published."
                      : "Nothing disputes the magnitude, so the figures below are still shown, but they are this number restated and no deal verdict is published."}${_quote}</div>`
                  : _at.level === "proxy"
                    ? `<div class="calc-range">Proxy value — estimated without usable comps or a known square footage.</div>`
                    : ""}
            ${
              // calc.arv_vs_assessed: WRITTEN ON 23,156 LEADS, READ BY NOBODY.
              // It is the ratio of the published ARV to the county's own
              // assessed value — the one cross-check on this page that comes
              // from a source the valuation did not produce, and it was
              // reaching no device at all. A 1.0 says the county agrees; a 4.5
              // says one of the two records is about a different building, and
              // that is exactly the failure this whole round is about.
              typeof c.arv_vs_assessed === "number" && c.arv_expected
                ? `<div class="calc-range ${c.arv_vs_assessed >= 3 || c.arv_vs_assessed <= 0.34 ? "dq-soft-mark" : ""}" title="${_attr(
                    "The published ARV divided by the county's assessed value. Near 1.0 means the county's own record agrees with this valuation. Far from 1.0 means they disagree, and one of the two is describing a different property.")}">`
                  + `vs county assessment: <b>${c.arv_vs_assessed.toFixed(2)}×</b>`
                  + (c.arv_vs_assessed >= 3 ? " — the county values this at a third of the ARV or less"
                    : c.arv_vs_assessed <= 0.34 ? " — the county values this at three times the ARV or more" : "")
                  + `</div>`
                : ""}
          </div>
        </div>`);
    }
    // THE STAMPED-VALUE CLUSTER, on the leads that KEEP their money.
    //
    // On the 1,451 leads whose ARV was built on the stamp, calc.notes already
    // carries the full prose and _quote above prints it verbatim — nothing is
    // added here, because saying it twice is how a warning becomes wallpaper.
    // The 255 comp-grounded ones had NO note, no flag the panel rendered and no
    // sentence anywhere: measured on the rendered board, 0 of 255 matched
    // /stamped across many properties/ or /shared across parcels/. They get the
    // fact, in the same visual register as the other caveats and next to the
    // numbers it qualifies. See stampCluster() for the flag strings and counts.
    const _sc = stampCluster(l);
    if (_sc.inCluster && !_sc.arvDerivedFromStamp) {
      rows.push(`<div class="calc-row stamp-cluster-row"><div class="lbl">County record</div>`
        + `<div><div class="arv-weak-note"><strong>This parcel sits in a stamped-value cluster.</strong> `
        + `${_attr(STAMP_CLUSTER_NOTE)}</div></div></div>`);
    }
    if (c.rehab_expected != null) {
      rows.push(`
        <div class="calc-row">
          <div class="lbl">Est. Rehab</div>
          <div>
            <div class="val">${fmtMoney(c.rehab_expected)}</div>
            <div class="calc-range">tier: <b>${c.rehab_tier || "—"}</b> · range: <b>${fmtMoney(c.rehab_low)}</b> – <b>${fmtMoney(c.rehab_high)}</b></div>
            ${
              // calc.rehab_with_contingency: written on 3,455 leads, read by
              // nobody. It is the rehab the engine actually expects someone to
              // spend (rehab + contingency), and it is the number that decides
              // whether a deal survives, so it belongs next to the estimate it
              // corrects rather than in a field only the JSON has ever seen.
              typeof c.rehab_with_contingency === "number" && c.rehab_with_contingency > (c.rehab_expected || 0)
                ? `<div class="calc-range">with contingency: <b>${fmtMoney(c.rehab_with_contingency)}</b> `
                  + `<span class="muted">— budget this, not the figure above</span></div>`
                : ""}
          </div>
        </div>`);
    }
    if (l.opening_bid) {
      rows.push(`<div class="calc-row"><div class="lbl">Opening Bid</div><div class="val big">${fmtMoney(l.opening_bid)}</div></div>`);
    }
    // Everything below is arv_expected restated. On the contradicted tier the
    // pipeline has already deleted these fields, so this only reaches the two
    // cases where money survives a caveat: the weak tier (kept on purpose) and
    // the $2M / ROI>400% layer, which grading.py withholds the LETTER for but
    // not the figures. Either way the number must not render as plain fact.
    const _derived = (v, extraCls) => {
      const cls = _at.level === "bad" ? " dq-warn-mark" : _at.level === "weak" ? " dq-soft-mark" : "";
      const pre = _at.level === "weak" ? "&#8776;" : "";
      const ttl = cls ? ` title="${_attr(arvTrustTitle(_at))}"` : "";
      return `<div class="val ${extraCls || ""}${cls}"${ttl}>${pre}${v}</div>`;
    };
    if (c.max_bid_70 != null) {
      // The 70% rule is ARV × 0.70 − rehab. When there was no rehab estimate
      // the engine subtracted $0, so this is a ceiling before repairs. Said
      // here, under the number, rather than in the notes block below where the
      // reader arrives after they have already read the figure.
      const _rt = rehabTrust(l).state;
      rows.push(`<div class="calc-row"><div class="lbl">Max Bid (70% rule)</div><div>${
        _derived(fmtMoney(c.max_bid_70) + (_rt === "unknown" ? `<span class="rehab-dag">&dagger;</span>` : ""), "big")
      }${_rt === "unknown"
        ? `<div class="rehab-note"><strong>&dagger; No rehab was deducted.</strong> ${_txt(REHAB_UNKNOWN_BODY)}</div>`
        : _rt === "land"
          ? `<div class="calc-range">No rehab deducted — this is land, so there is nothing to repair.</div>`
          : ""}${
        // The asking-price cap, in calc's own words. Plain muted styling, not
        // the amber caveat vocabulary: this number is RIGHT, it just is not the
        // 70%-rule output, and a reader doing the arithmetic themselves would
        // otherwise find a discrepancy with no explanation on screen.
        (() => { const _cap = bidCapNote(l); return _cap ? `<div class="calc-range">${_txt(_cap)}</div>` : ""; })()
      }</div></div>`);
    }
    if (c.wholesale_mao != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Wholesale MAO</div>${_derived(fmtMoney(c.wholesale_mao) + (c.wholesale_spread != null ? ` <span class="muted">(spread ${fmtMoney(c.wholesale_spread)})</span>` : ""))}</div>`);
    }
    if (c.bid_to_arv_pct != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Bid / ARV</div>${_derived(c.bid_to_arv_pct.toFixed(1) + "%")}</div>`);
    }
    if (c.total_investment != null) {
      rows.push(`<div class="calc-row"><div class="lbl">Total Investment</div>${_derived(fmtMoney(c.total_investment))}</div>`);
    }
    if (c.estimated_profit != null) {
      const cls = _at.level === "bad" || _at.level === "weak" ? "big" : "big " + (c.estimated_profit > 0 ? "pos" : "neg");
      rows.push(`<div class="calc-row"><div class="lbl">Est. Profit</div>${_derived(fmtMoney(c.estimated_profit), cls)}</div>`);
    }
    if (c.roi_pct != null) {
      const cls = _at.level === "bad" || _at.level === "weak" ? "big" : "big " + (c.roi_pct > 0 ? "pos" : "neg");
      rows.push(`<div class="calc-row"><div class="lbl">ROI</div>${_derived(c.roi_pct.toFixed(1) + "%", cls)}</div>`);
    }
    if (c.cash_on_cash_pct != null) {
      const cls = _at.level === "bad" || _at.level === "weak" ? "" : (c.cash_on_cash_pct > 0 ? "pos" : "neg");
      rows.push(`<div class="calc-row"><div class="lbl">Cash-on-Cash</div>${_derived(c.cash_on_cash_pct.toFixed(1) + "%", cls)}</div>`);
    }
    const _eq = _nonEmpty(l.raw && l.raw.equity) ? l.raw.equity : null;
    if (_eq && _eq.value != null) {
      const ec = _eq.is_underwater ? "neg" : ((_eq.pct || 0) >= 0.4 ? "pos" : "");
      rows.push(`<div class="calc-row"><div class="lbl">Owner Equity</div><div class="val big ${ec}">${fmtMoney(_eq.value)} <span class="muted">(${Math.round((_eq.pct || 0) * 100)}%)</span></div></div>`);
      rows.push(`<div class="calc-row"><div class="lbl">Est. Payoff</div><div class="val">${fmtMoney(_eq.payoff_estimate)} <span class="muted">${String(_eq.payoff_source || "").replace(/_/g, " ")} · ${_eq.confidence || ""}</span></div></div>`);
      if (_eq.senior_liens) rows.push(`<div class="calc-row"><div class="lbl">Senior Liens</div><div class="val neg">${fmtMoney(_eq.senior_liens)}</div></div>`);
    } else if (_eq && _eq.withheld_reason) {
      // THE EQUITY GATE'S OWN REASON, FINALLY ON A SCREEN.
      //
      // enrichment writes equity.withheld_reason on 4,240 leads — a full
      // paragraph explaining that equity was suppressed because the ARV it
      // would be computed from is contradicted (3,127) or was never published
      // (1,113). It was allowlisted into the slim payload deliberately ("the
      // sentences that say WHY a figure is missing, the detail panel reads
      // them" — web_artifact._SLIM_RAW), shipped to every device, and then read
      // by no line of code in this file. The panel simply omitted the row, so
      // "no equity figure" was indistinguishable from "we did not look".
      //
      // equity.arv_trust ("contradicted" | "withheld") is the same story in one
      // word and labels the row.
      const _et = String(_eq.arv_trust || "").replace(/_/g, " ");
      rows.push(`<div class="calc-row"><div class="lbl">Owner Equity</div><div>`
        + `<div class="val big dq-warn-mark">not published</div>`
        + `<div class="arv-flag-note"><strong>Equity was withheld${_et ? ` — ARV ${_txt(_et)}` : ""}.</strong> `
        + `${_txt(_cap(_eq.withheld_reason.replace(/^No owner-equity figure published:\s*/i, "")))}</div>`
        + `</div></div>`);
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
    $("d-calc").innerHTML = dqSummaryLine(l)
      + "<em>Calculator data not available — listing missing key fields.</em>";
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
  //
  // GATED ON geoTrust(). Same lie as the card, one screen further in: a marker
  // dropped at zoom 15 is a claim that the property is THERE, and on 15,603 of
  // the leads that reach here the coordinate is a city/county centroid.
  //
  // The map is not deleted — a county-level locator is genuinely useful and
  // most of the board is precisely placed. What is deleted is the CLAIM of
  // precision: no pin, a shaded circle the size of the actual uncertainty, a
  // zoom that matches that circle rather than a street, and a banner above it
  // in words. A reader who wants the street can still pan; a reader who glances
  // can no longer come away with a false address.
  const _gt = geoTrust(l);
  const _mapNote = $("d-map-note");
  if (_mapNote) {
    // CLEARED, not just hidden. The detail panel is one set of static nodes
    // reused for every lead, so leaving the previous lead's sentence in a
    // display:none node keeps another property's warning one style change away
    // from being shown on this one. Same leak class as the skip-trace row
    // below. Verified: opening a centroid lead and then a precisely-geocoded
    // one left the banner text populated behind display:none.
    const _showNote = !!(l.latitude && l.longitude && _gt.imprecise);
    _mapNote.style.display = _showNote ? "block" : "none";
    _mapNote.innerHTML = _showNote
      ? `<strong>This pin is not the property.</strong> ${_txt(_cap(_gt.why))}. `
        + `The circle is roughly how far off it can be; the address above is what to trust.`
      : "";
  }
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
      } : {}).setView([l.latitude, l.longitude], _gt.imprecise ? 12 : 15);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(detailMap);
      if (_gt.imprecise) {
        // A circle, not a marker. Leaflet's default pin is a point claim, and
        // on a centroid lead there is no honest point to make.
        L.circle([l.latitude, l.longitude], {
          radius: _gt.radiusMi * 1609,
          color: "#b26a00", weight: 2, dashArray: "5,5",
          fillColor: "#b26a00", fillOpacity: 0.12,
        }).addTo(detailMap).bindTooltip("Approximate area only — the property is somewhere in here");
      } else {
        L.marker([l.latitude, l.longitude]).addTo(detailMap);
      }
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
    // DISTANCE, and whether it means anything.
    //
    // Every comp carries distance_mi and it was never rendered, so "3 Sold
    // Comps (zip + sqft + beds matched)" implied proximity without ever
    // stating it. Showing it is the easy half. The half that matters: on
    // 11,985 leads the subject's own coordinates are a centroid, so those
    // 35,691 distances are measured FROM A LANDMARK — a median of 0.5 mi from
    // a town square says nothing about how near the comp is to the house. They
    // render struck through, in the caveat colour, with the reason on hover.
    const _cgt = geoTrust(l);
    const _distTh = `<th title="${_attr(_cgt.imprecise
      ? "Distance from this lead's stored coordinate — which is a city/county centroid, not the property."
      : "Straight-line distance from the property.")}">Dist${_cgt.imprecise ? " ⚠" : ""}</th>`;
    const _distTd = (c) => {
      if (c.distance_mi == null) return `<td class="num">—</td>`;
      const v = `${Number(c.distance_mi).toFixed(1)} mi`;
      if (!_cgt.imprecise) return `<td class="num">${v}</td>`;
      return `<td class="num dq-soft" title="${_attr("Measured from a city/county centroid, not from this property — " + _cgt.why + ". The distance is not usable.")}"><s>${v}</s></td>`;
    };
    const _distNote = _cgt.imprecise
      ? `<div class="geo-note geo-note-sm"><strong>Distances below are not measurements of this property.</strong> `
        + `${_txt(_cap(_cgt.why))}, so every comp distance is from that landmark. The comps themselves may still be sound — `
        + `the engine flags this as <code>geo_imprecise_comps</code> — but do not read the mileage as nearness.</div>`
      : "";
    $("d-comps").innerHTML = compHeader + _distNote + `
      <table class="comps-table">
        <thead><tr><th>Address</th><th>Sold</th><th>Date</th>${_distTh}<th>SqFt</th><th>Bd/Ba</th><th>$/SqFt</th></tr></thead>
        <tbody>
        ${comps.map(c => `
          <tr>
            <td>${c.url ? `<a href="${c.url}" target="_blank">${c.address || "—"}</a>` : (c.address || "—")}</td>
            <td>${c.sold_price ? `$${Number(c.sold_price).toLocaleString()}` : "—"}</td>
            <td>${c.sold_date ? c.sold_date.slice(0,10) : "—"}</td>
            ${_distTd(c)}
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
  //
  // `_nonEmpty`, not truthiness: web_artifact emits an allowlisted block even
  // when the source had none of its sub-keys, so `raw.gis` is `{}` on 8,063
  // leads and `if (gis)` said yes to every one of them — a "County Records"
  // header over nothing, on mobile only, because that is the payload the phone
  // reads. Desktop's fat board omits the key entirely and hid the section, so
  // the two devices disagreed about whether this property has a county record.
  const gis = _nonEmpty(l.raw && l.raw.gis) ? l.raw.gis : null;
  if (gis) {
    $("d-gis-section").style.display = "block";
    const rows = [];
    // "Owner:" used to print gis.owner flat, while the CSV column and the
    // people-search searched l.owner_name — two different names, no label on
    // either, and 16,512 leads where they disagree. Label WHICH record this
    // name came from; the canonical name and the disagreement are rendered in
    // Owner & Contact below.
    if (gis.owner) rows.push(`<div><strong>Owner on the county parcel record:</strong> ${_txt(gis.owner)}</div>`);
    if (gis.mailing) rows.push(`<div><strong>Mailing:</strong> ${_txt(gis.mailing)}</div>`);
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
    // CLEAR, not just hide. The detail panel is one set of nodes reused for
    // every lead, so hiding without clearing leaves the PREVIOUS property's
    // owner and mailing address sitting in the DOM of this one — invisible
    // until anything unhides it, and present in a copy, a print or a11y tree
    // either way. This section names a person and an address; it does not get
    // to keep the last one.
    $("d-gis").innerHTML = "";
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
  const _batTtl = _attr(arvTrustTitle(_bat));
  const _batWhy = arvShortWhy(_bat);
  if (_bat.absent === "withheld" || _bat.absent === "refused") {
    badges.push(`<span class="qbadge neg" title="${_batTtl}">⚠ No ARV published${_batWhy ? " — " + _batWhy : ""}</span>`);
  } else if (_bat.level === "bad") {
    badges.push(`<span class="qbadge neg" title="${_batTtl}">⚠ ARV flagged — do not bid off it${_batWhy ? " · " + _batWhy : ""}</span>`);
  } else if (_bat.level === "weak") {
    // Amber, and it names the reason. "warn-light" rather than "neg": nothing
    // contradicts this number, the evidence just does not describe this exact
    // property, and rendering that identically to a contradicted ARV is how a
    // real warning turns into wallpaper.
    badges.push(`<span class="qbadge warn-light dq-weak" title="${_batTtl}">${arvWeakLabel(_bat, "badge")}${_batWhy ? " · " + _batWhy : ""}</span>`);
  }
  // Stamped-value cluster, comp-grounded. Amber, not red: the valuation is
  // sound and the money below it stands — what is unverified is the COUNTY
  // record, which is a different subject and gets different words. On the 1,451
  // leads whose ARV came from the stamp the badge above already says "ARV
  // flagged — do not bid off it", so this stays quiet there.
  const _scb = stampCluster(l);
  if (_scb.inCluster && !_scb.arvDerivedFromStamp) {
    badges.push(`<span class="qbadge warn-light dq-weak" title="${_attr(STAMP_CLUSTER_NOTE)}">🧬 County value stamped across parcels · ARV is comp-based, money stands</span>`);
  }
  // `dq-weak` repaints warn-light into the weak vocabulary — see injectDashStyles.
  // It is added only where warn-light MEANS "caveated", never where it is just
  // the palette for a middling ROI, so the two can be told apart.
  const _weakCls = "warn-light dq-weak";
  if (calc.arv_expected) {
    const lowArv = _bat.level === "proxy";
    const cls = _bat.level === "bad" ? "neg" : _bat.level === "weak" ? _weakCls : "info";
    // One glyph vocabulary across the whole file: ⚠ = do not bid off it,
    // ≈ = a band not a number, ~ = a proxy estimate. This badge used "~" for
    // the BAD tier too, which said "rough estimate" on the one tier that means
    // "another record disputes this".
    const mark = _bat.level === "bad" ? "&#9888;&#xFE0E; " : _bat.level === "weak" ? "≈" : "~";
    badges.push(`<span class="qbadge ${cls}" title="${_attr(_bat.level === "ok" ? ((calc.notes && calc.notes[0]) || "") : arvTrustTitle(_bat))}">ARV ${mark}$${Number(calc.arv_expected).toLocaleString()}${lowArv ? " (proxy)" : ""}</span>`);
  }
  if (calc.max_bid_70) {
    const cls = _bat.level === "bad" ? "neg" : _bat.level === "weak" ? _weakCls : "info";
    // The reason, in the badge itself. A bidder reading "Max bid (70%) $947,700"
    // on a phone gets no hover, so "— band, not a number" was the only thing on
    // screen saying the number was caveated and it did not say WHY. 94 Long
    // Ridge Road now reads "≈$947,700 — band, not a number · land comps
    // rejected", and the tooltip still quotes calc's note verbatim.
    const tail = _bat.level === "bad"
      ? " — from a flagged ARV" + (_batWhy ? " · " + _batWhy : "")
      : _bat.level === "weak"
        ? " — band, not a number" + (_batWhy ? " · " + _batWhy : "")
        : "";
    // The rehab caveat rides the badge too. This chip row is what a phone sees
    // above the fold; a bidder who never scrolls to the calculator still gets
    // told that the subtraction was of zero.
    const _rbt = rehabTrust(l).state;
    const _rtail = _rbt === "unknown" ? " † no rehab deducted" : "";
    const _rttl = _rbt === "unknown" ? _attr(REHAB_UNKNOWN_NOTE) : _batTtl;
    badges.push(`<span class="qbadge ${cls}${_rbt === "unknown" ? " rehab-unknown" : ""}" title="${_rttl}">Max bid (70%) ${_bat.level === "weak" ? "≈" : ""}$${Number(calc.max_bid_70).toLocaleString()}${tail}${_rtail}</span>`);
  }
  if (calc.roi_pct != null) {
    const cls = _bat.level === "bad" ? "neg" : _bat.level === "weak" ? _weakCls
      : calc.roi_pct > 25 ? "pos" : calc.roi_pct > 10 ? "warn-light" : "neg";
    badges.push(`<span class="qbadge ${cls}" title="${_batTtl}">ROI ${_bat.level === "weak" ? "≈" : ""}${calc.roi_pct.toFixed(0)}%</span>`);
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

  // These badges WRAP now rather than being painted off the right edge of the
  // page — see the .qbadge block in style.css for the measurement that forced
  // it. Nothing is needed here: whether a given badge is one line or three is a
  // pure layout question, it changes when the phone is rotated, and CSS is the
  // only layer that stays right across that.
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
  // ONE OWNER NAME, NAMED, AND IT IS THE ONE THE BUTTON SEARCHES.
  //
  // This row used to print raw.owner_mailing.owner. The CSV column and the
  // people-search URL used l.owner_name. The County Records section printed
  // raw.gis.owner. Three names, three call sites, no labels — and on 16,512 of
  // 38,500 leads at least two of them disagree, which is the board's own signal
  // that the parcel join may have attached this lead to a different property.
  // Hiding it made the disagreement look like agreement.
  //
  // Now: the canonical name (l.owner_name where it exists — unchanged from what
  // the export and the link already used) is the row, every other name is shown
  // beneath it with the record it came from, and the skip-trace link is
  // rendered right there so what is searched is what is on screen.
  const _owners = ownerNames(l);
  const _place = placeOfRecord(l);
  const _tps = skipTraceUrl(l);
  const _ownerRows = [];
  if (_owners.primary) {
    _ownerRows.push(`<div class="lbl">Owner</div><div class="val">${_txt(_owners.primary)}`
      + `<span class="owner-src"> — from the ${_txt(_owners.primarySrc)}</span></div>`);
    // Every other spelling is LISTED whenever one exists — "TABARES JOSE L &
    // TABARES IRINA" is a better mail-merge and skip-trace target than
    // "TABARES JOSE L", and hiding it helps nobody. The RED LINE underneath is
    // gated separately on _owners.conflict, which is true only when the names
    // cannot be reconciled (see ownerNames). Listing without warning: 3,584
    // leads. Listing with the warning: 12,674.
    if (_owners.all.length > 1) {
      _ownerRows.push(`<div class="lbl">Also recorded as</div><div class="val${_owners.conflict ? " owner-conflict" : ""}"`
        + (_owners.conflict
          ? ` title="${_attr("These records name owners that cannot be reconciled. That is usually a stale county row or a sale another source has not caught up with — but it can also mean this lead is joined to the wrong parcel. Verify before mailing.")}"`
          : ` title="${_attr("The same owner, recorded differently by each source — one carries a spouse, an heir, or punctuation the other dropped. Shown because the fuller spelling is usually the better skip-trace query.")}"`)
        + `>`
        + _owners.all.slice(1).map((o) => `${_txt(o.name)} <span class="owner-src">(${_txt(o.src)})</span>`).join("<br>")
        + (_owners.conflict
          ? `<div class="owner-conflict-why">These sources name different owners — check the parcel before you spend money on this one.</div>`
          : "")
        + `</div>`);
    }
  }
  // BUILT IN ONE ASSIGNMENT, NOT APPENDED TO setSec's.
  //
  // setSec HIDES a section whose rows are all empty but does not CLEAR it, and
  // the detail panel is one set of static nodes reused for every lead. Appending
  // to it therefore leaks: verified in the browser, opening 510 Kings Rd and
  // then a lead with no owner left "🔎 Look up SERVICEMAC LLC in 28150" sitting
  // in the second lead's contact block — the wrong person, on the wrong
  // property, behind a live link. It happened to be inside a display:none
  // section that time, which is luck, not a design. Rendering the whole block
  // here means the previous lead's identity cannot survive into the next one.
  const _contactRows = kv([
    ["Mailing address", _om.mailing],
    ["Absentee owner", _om.absentee], ["Out of state", _om.out_of_state],
    ["Phone", _phone], ["Other numbers", _alts.join(" · ")], ["Email", _st.email],
  ].concat(_saRows));
  // The people-search was a CSV column only — a link nobody can click from a
  // phone, pointed at a query built from `city` even when `city` holds a COUNTY
  // name (4,347 leads). placeOfRecord() prefers the ZIP and states what it
  // searched, so a reader can see the query is wide before they blame the
  // result.
  const _tpsHtml = _tps
    ? `<div class="skiptrace-row"><a href="${_attr(_tps)}" target="_blank" rel="noopener noreferrer">`
      + `🔎 Look up ${_txt(_owners.primary)} in ${_txt(_place.label)} →</a>`
      + (_place.trusted ? "" : `<div class="skiptrace-why">Searching ${_txt(_place.label)} because ${_txt(_place.why)}.</div>`)
      + `</div>`
    : "";
  const _gridHtml = _ownerRows.join("") + _contactRows;
  if (_gridHtml || _tpsHtml) {
    $("d-contact").innerHTML = (_gridHtml ? `<div class="detail-grid">${_gridHtml}</div>` : "") + _tpsHtml;
    $("d-contact-section").style.display = "block";
  } else {
    $("d-contact").innerHTML = "";
    $("d-contact-section").style.display = "none";
  }

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
    // APPENDED, deliberately at the end so no existing column moves.
    //   skiptrace_locale   what the people-search URL actually searched
    //   city_may_be_county "yes" when `city` equals `county` and could be a
    //                      county label rather than a town (4,347 leads)
    //   owner_name_conflict the other owner strings this lead carries, when
    //                      they disagree with owner_name (16,512 leads)
    //   rehab_deducted     whether max_bid_70 subtracted a rehab cost
    "truepeoplesearch_url", "skiptrace_locale", "city_may_be_county",
    "owner_name_conflict", "rehab_deducted",
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
    // Was `citystatezip=${l.city} ${l.state}`, which searched a COUNTY on the
    // 4,347 leads where `city` holds the county name — every one of the 3,309
    // spartanburg_vacant rows among them. skipTraceUrl() prefers the ZIP
    // (16,470 leads have one) and widens to the state rather than querying a
    // place that may not exist. Same function the detail panel's link uses, so
    // the export and the screen can no longer drift apart.
    const tps = skipTraceUrl(l);
    const _plc = placeOfRecord(l);
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
      skiptrace_locale: tps ? _plc.label : "",
      city_may_be_county: (l.city && l.county && String(l.city).trim().toLowerCase() === String(l.county).trim().toLowerCase()) ? "yes" : "",
      owner_name_conflict: (() => {
        const o = ownerNames(l);
        return o.conflict ? o.all.slice(1).map((x) => `${x.name} (${x.src})`).join(" | ") : "";
      })(),
      rehab_deducted: (() => {
        if (c.max_bid_70 == null) return "";
        const rt = rehabTrust(l).state;
        return rt === "deducted" ? "yes" : rt === "land" ? "n/a (land)" : "NO — bid deducted $0";
      })(),
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
