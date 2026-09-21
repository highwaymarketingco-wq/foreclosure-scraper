// Tests for the IO-GUARD region of docs/dashboard.js: login-page detection (for a
// private host behind Cloudflare Access) and CRM export/import merging.
//
// The code under test is sliced out of dashboard.js and run under node's vm, so
// it is the code that ships.
//
// Run:  node --test tests/js/io_guard.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.join(HERE, "..", "..", "docs");
const JS = fs.readFileSync(path.join(DOCS, "dashboard.js"), "utf8");
const HTML = fs.readFileSync(path.join(DOCS, "index.html"), "utf8");
const MANIFEST = JSON.parse(fs.readFileSync(path.join(DOCS, "manifest.json"), "utf8"));

const a = JS.indexOf("// ---- BEGIN IO-GUARD");
const b = JS.indexOf("// ---- END IO-GUARD");
assert.ok(a > 0 && b > a, "IO-GUARD region not found in dashboard.js");
const REGION = JS.slice(a, b);

function load() {
  const sandbox = { Object, Array, String, Number, JSON, Date, URL, isNaN };
  vm.createContext(sandbox);
  const names = ["isDataUrl", "sessionProblem", "sessionReloadDecision", "sessionReloadClear",
    "crmCleanRecord", "crmMerge", "crmParseImport", "crmExportDoc", "SESSION_RELOAD_KEY",
    "CRM_EXPORT_FORMAT", "CRM_IMPORT_MAX_BYTES", "CRM_NOTES_MAX"];
  return vm.runInContext(`"use strict";\n${REGION}\n;({ ${names.join(", ")} })`, sandbox);
}
// Arrays/objects built in the vm carry that realm's prototypes.
const plain = (v) => JSON.parse(JSON.stringify(v));

const ORIGIN = "https://board.example.com";
const res = (o = {}) => ({
  ok: true, status: 200, type: "basic", redirected: false, url: `${ORIGIN}/run_meta.json`,
  headers: { get: (k) => (o.ct !== undefined && k.toLowerCase() === "content-type" ? o.ct : null) }, ...o,
});

// ---------------------------------------------------------------------------
test("isDataUrl: only same-origin .json / .json.gz files count as data", () => {
  const S = load();
  for (const u of ["run_meta.json?t=1", "listings_slim.json.gz?t=2026-09-21T13%3A45%3A12Z", "detail_shards/00003.json.gz",
    "multifamily.json", "land_buyers.json?t=5", `${ORIGIN}/run_meta.json`]) {
    assert.equal(S.isDataUrl(u, ORIGIN), true, u);
  }
  for (const u of ["manifest.webmanifest", "https://tile.openstreetmap.org/1/2/3.png", "https://other.example.com/x.json",
    "//other.example.com/x.json", "style.css", "", null, undefined]) {
    assert.equal(S.isDataUrl(u, ORIGIN), false, String(u));
  }
});

test("sessionProblem: 401, 403, opaque redirect, cross-origin redirect and a 200 web page are login pages", () => {
  const S = load();
  assert.match(S.sessionProblem(res({ ok: false, status: 401 }), ORIGIN), /HTTP 401/);
  assert.match(S.sessionProblem(res({ ok: false, status: 403 }), ORIGIN), /HTTP 403/);
  assert.match(S.sessionProblem(res({ type: "opaqueredirect", ok: false, status: 0 }), ORIGIN), /login redirect/);
  assert.match(S.sessionProblem(res({ redirected: true, url: "https://team.cloudflareaccess.com/cdn-cgi/access/login" }), ORIGIN), /redirected to another site/);
  assert.match(S.sessionProblem(res({ ct: "text/html; charset=utf-8" }), ORIGIN), /web page instead of data/);
});

test("sessionProblem: real data, a missing optional file and a same-origin redirect are not", () => {
  const S = load();
  assert.equal(S.sessionProblem(res({ ct: "application/json" }), ORIGIN), "");
  assert.equal(S.sessionProblem(res({ ct: "application/gzip" }), ORIGIN), "");
  assert.equal(S.sessionProblem(res({ ct: null }), ORIGIN), "");
  // GitHub Pages answers a missing file with an HTML 404. That is not a login.
  assert.equal(S.sessionProblem(res({ ok: false, status: 404, ct: "text/html" }), ORIGIN), "");
  assert.equal(S.sessionProblem(res({ redirected: true, url: `${ORIGIN}/other.json` }), ORIGIN), "");
  assert.equal(S.sessionProblem(null, ORIGIN), "");
});

test("sessionReloadDecision: one reload, then hold; it clears after a good load; it never loops without storage", () => {
  const S = load();
  const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
  const st = mem();
  assert.equal(S.sessionReloadDecision(st), "reload");
  assert.equal(S.sessionReloadDecision(st), "hold");        // still failing after the reload: no loop
  assert.equal(S.sessionReloadDecision(st), "hold");
  S.sessionReloadClear(st);                                  // a load succeeded
  assert.equal(S.sessionReloadDecision(st), "reload");       // a later lapse may reload once again
  // storage that throws (private mode): cannot count reloads, so never reload
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };
  assert.equal(S.sessionReloadDecision(broken), "hold");
  assert.doesNotThrow(() => S.sessionReloadClear(broken));
  // setItem failing after a clean getItem also holds
  const halfBroken = { getItem: () => null, setItem() { throw new Error("quota"); }, removeItem() {} };
  assert.equal(S.sessionReloadDecision(halfBroken), "hold");
});

// ---------------------------------------------------------------------------
// CRM merge
const rec = (o) => ({ status: "Contacted", notes: "n", next_action: "2026-10-01", updated: "2026-09-10T12:00:00.000Z", ...o });

test("crmMerge: a newer incoming record wins, an older one does not, a tie keeps local", () => {
  const S = load();
  const local = { "case:A": rec({ notes: "local A", updated: "2026-09-10T12:00:00.000Z" }),
                  "case:B": rec({ notes: "local B", updated: "2026-09-15T12:00:00.000Z" }),
                  "case:C": rec({ notes: "local C", updated: "2026-09-12T12:00:00.000Z" }) };
  const incoming = { "case:A": rec({ notes: "import A", updated: "2026-09-11T12:00:00.000Z" }),   // newer
                     "case:B": rec({ notes: "import B", updated: "2026-09-14T12:00:00.000Z" }),   // older
                     "case:C": rec({ notes: "import C", updated: "2026-09-12T12:00:00.000Z" }) }; // tie
  const { merged, stats } = S.crmMerge(local, incoming);
  assert.equal(merged["case:A"].notes, "import A");
  assert.equal(merged["case:B"].notes, "local B");
  assert.equal(merged["case:C"].notes, "local C");
  assert.deepEqual(plain(stats), { added: 0, updated: 1, kept: 2, skipped: 0 });
});

test("crmMerge never deletes: every local lead survives, new ones are added", () => {
  const S = load();
  const local = { "case:ONLY-LOCAL": rec({ notes: "keep me" }), "parcel:SC:1": rec() };
  const { merged, stats } = S.crmMerge(local, { "url:https://x/y": rec({ notes: "new" }) });
  assert.deepEqual(Object.keys(merged).sort(), ["case:ONLY-LOCAL", "parcel:SC:1", "url:https://x/y"]);
  assert.equal(merged["case:ONLY-LOCAL"].notes, "keep me");
  assert.equal(stats.added, 1);
  // Importing nothing, or garbage, changes nothing.
  assert.deepEqual(Object.keys(S.crmMerge(local, {}).merged).sort(), Object.keys(local).sort());
  assert.deepEqual(Object.keys(S.crmMerge(local, null).merged).sort(), Object.keys(local).sort());
  assert.deepEqual(Object.keys(S.crmMerge(local, [1, 2]).merged).sort(), Object.keys(local).sort());
  assert.deepEqual(Object.keys(S.crmMerge(null, { "case:X": rec() }).merged), ["case:X"]);
});

test("crmMerge: a newer record overlays field by field, so an older note it omits is not lost", () => {
  const S = load();
  const local = { "case:A": { status: "New", notes: "call the estate lawyer", updated: "2026-09-01T00:00:00Z" } };
  const incoming = { "case:A": { status: "Contacted", updated: "2026-09-02T00:00:00Z" } };     // no notes field
  const { merged } = S.crmMerge(local, incoming);
  assert.equal(merged["case:A"].status, "Contacted");
  assert.equal(merged["case:A"].notes, "call the estate lawyer");
});

test("crmMerge accepts updated_at as a synonym and treats a missing date as oldest", () => {
  const S = load();
  const { merged } = S.crmMerge(
    { "case:A": { notes: "no date", status: "New" }, "case:B": rec({ updated: "2026-09-10T00:00:00Z" }) },
    { "case:A": { notes: "dated", updated_at: "2026-01-01T00:00:00Z" }, "case:B": rec({ notes: "older", updated: undefined, updated_at: "2026-09-01T00:00:00Z" }) });
  assert.equal(merged["case:A"].notes, "dated");
  assert.equal(merged["case:A"].updated, "2026-01-01T00:00:00Z");   // normalised to `updated`
  assert.equal(merged["case:B"].notes, "n");
});

test("crmMerge: hostile keys and junk records are skipped, never applied", () => {
  const S = load();
  const incoming = JSON.parse('{"__proto__": {"polluted": true}, "constructor": {"notes": "x"}, "prototype": {"notes": "x"},'
    + ' "case:BAD": "not an object", "case:EMPTY": {}, "case:ARR": [1], "case:OK": {"notes": "fine"},'
    + ' "case:NOTES": {"notes": "' + "x".repeat(S.CRM_NOTES_MAX + 500) + '", "status": "' + "s".repeat(80) + '", "next_action": "tomorrow", "extra": "dropped"}}');
  const { merged, stats } = S.crmMerge({}, incoming);
  assert.equal(({}).polluted, undefined);
  assert.equal(Object.keys(merged).sort().join(), "case:NOTES,case:OK");
  assert.equal(merged["case:OK"].notes, "fine");
  assert.equal(merged["case:NOTES"].notes.length, S.CRM_NOTES_MAX);       // capped
  assert.equal("status" in merged["case:NOTES"], false);                  // 80 chars: refused
  assert.equal("next_action" in merged["case:NOTES"], false);             // not a date: refused
  assert.equal("extra" in merged["case:NOTES"], false);                   // unknown field dropped
  assert.equal(stats.skipped, 6);
  assert.equal(stats.added, 2);
});

test("crmParseImport reads the export wrapper and the bare localStorage value, and refuses the rest", () => {
  const S = load();
  const doc = S.crmExportDoc({ "case:A": rec() }, "2026-09-21T00:00:00Z", ORIGIN);
  assert.equal(doc.format, "fc-crm-export");
  assert.equal(doc.count, 1);
  assert.equal(doc.origin, ORIGIN);
  const wrapped = S.crmParseImport(JSON.stringify(doc));
  assert.equal(wrapped.ok, true);
  assert.deepEqual(Object.keys(wrapped.records), ["case:A"]);
  const bare = S.crmParseImport(JSON.stringify({ "case:A": rec() }));
  assert.equal(bare.ok, true);
  assert.deepEqual(Object.keys(bare.records), ["case:A"]);
  assert.equal(S.crmParseImport("").ok, false);
  assert.equal(S.crmParseImport("{not json").ok, false);
  assert.equal(S.crmParseImport("[1,2]").ok, false);
  assert.equal(S.crmParseImport("42").ok, false);
  assert.equal(S.crmParseImport(JSON.stringify({ format: "something-else", records: {} })).ok, false);
  assert.equal(S.crmParseImport(JSON.stringify({ format: "fc-crm-export" })).ok, false);
  assert.equal(S.crmParseImport("x".repeat(S.CRM_IMPORT_MAX_BYTES + 1)).ok, false);
});

test("export then import round-trips into an empty browser, and re-importing changes nothing", () => {
  const S = load();
  const all = { "case:A": rec({ notes: "a" }), "parcel:SC:9": rec({ status: "Dead", notes: "b", updated: "2026-09-20T00:00:00Z" }) };
  const file = JSON.stringify(S.crmExportDoc(all, "2026-09-21T00:00:00Z", ORIGIN));
  const first = S.crmMerge({}, S.crmParseImport(file).records);
  assert.deepEqual(plain(first.merged), plain(all));
  assert.equal(first.stats.added, 2);
  const again = S.crmMerge(first.merged, S.crmParseImport(file).records);
  assert.deepEqual(plain(again.merged), plain(all));
  assert.deepEqual(plain(again.stats), { added: 0, updated: 0, kept: 2, skipped: 0 });
  // Export skips non-object junk and hostile keys.
  const doc = S.crmExportDoc(JSON.parse('{"__proto__": {"x": 1}, "case:A": {"notes": "a"}, "case:J": "junk"}'), "t", "");
  assert.deepEqual(Object.keys(doc.records), ["case:A"]);
});

// ---------------------------------------------------------------------------
// Wiring: the files the private-host move touches.
test("manifest.json is host-relative and index.html fetches it with credentials", () => {
  for (const k of ["id", "start_url", "scope"]) {
    assert.equal(MANIFEST[k], "./", `manifest ${k} must be relative`);
    assert.doesNotMatch(String(MANIFEST[k]), /foreclosure-scraper/);
  }
  assert.match(HTML, /<link rel="manifest" href="manifest\.json" crossorigin="use-credentials">/);
});

test("no runtime URL hard-codes the public GitHub Pages host or the /foreclosure-scraper/ subpath", () => {
  const strip = (src) => src.split("\n").filter((ln) => !/^\s*(\/\/|\*|\/\*|<!--)/.test(ln)).join("\n");
  for (const [name, src] of [["dashboard.js", JS], ["index.html", HTML]]) {
    const code = strip(src);
    assert.doesNotMatch(code, /github\.io/i, `${name} names github.io`);
    assert.doesNotMatch(code, /\/foreclosure-scraper\//, `${name} hard-codes /foreclosure-scraper/`);
  }
});

test("the session guard wraps fetch before loadData runs, and a good load clears its flag", () => {
  const install = JS.indexOf("(function installSessionGuard()");
  const boot = JS.lastIndexOf("loadData();");
  assert.ok(install > 0 && boot > install, "the guard must be installed before loadData()");
  assert.match(JS, /DS_CACHE\[name\] = \{ listings: LISTINGS, meta: META \};\n\s+sessionOk\(\);/);
  assert.match(JS, /Session expired, reload to sign in\./);
});

test("CRM Export / Import are in the page: buttons, one file input, and the wiring", () => {
  assert.equal((HTML.match(/data-crm-io="export"/g) || []).length, 2);
  assert.equal((HTML.match(/data-crm-io="import"/g) || []).length, 2);
  assert.equal((HTML.match(/id="crm-import-file"/g) || []).length, 1);
  assert.match(JS, /initCrmIo\(\);/);
  assert.match(JS, /localStorage\.getItem\(CRM_STORE_KEY\)/);          // still the same store
});
