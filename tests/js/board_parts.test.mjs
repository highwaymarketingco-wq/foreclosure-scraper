// Tests for the BOARD-LOADER region of docs/dashboard.js: the full board loaded as N parts
// (docs/listings_part_NNN.json.gz, audit O1) fetched in parallel and concatenated in order.
//
// The code under test is sliced out of dashboard.js (the PORTABLE region, which holds the
// streaming scanner and the slim projector, plus the BOARD-LOADER region) and run under node's
// vm with a stubbed fetch, so it is the code that ships. Real gzip, real streams.
//
// Run:  node --test tests/js/board_parts.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.join(HERE, "..", "..", "docs");
const JS = fs.readFileSync(path.join(DOCS, "dashboard.js"), "utf8");
const HTML = fs.readFileSync(path.join(DOCS, "index.html"), "utf8");

function region(begin, end) {
  const a = JS.indexOf(begin);
  const b = JS.indexOf(end);
  assert.ok(a >= 0 && b > a, `${begin} .. ${end} not found in dashboard.js`);
  return JS.slice(a, b);
}
const PORTABLE = region("// ---- BEGIN PORTABLE", "// ---- END PORTABLE");
const LOADER = region("// ---- BEGIN BOARD-LOADER", "// ---- END BOARD-LOADER");
const IOGUARD = region("// ---- BEGIN IO-GUARD", "// ---- END IO-GUARD");

const gz = (rows) => zlib.gzipSync(Buffer.from(JSON.stringify(rows)));
const plain = (v) => JSON.parse(JSON.stringify(v));
// parcel_id is in the phone's allowlist, so the id survives projection on the LEAN paths too
const rows = (from, n) => Array.from({ length: n }, (_, i) => ({ id: from + i, parcel_id: `P${from + i}`, raw: { grade: { overall: "B" } } }));

/** A sandbox running the shipped loader. `files` maps a URL path to {body, status, delayMs}. */
function load({ lean = false, files }) {
  const calls = [];
  const fetchStub = (url, opts = {}) => {
    calls.push(String(url));
    const name = String(url).split("?")[0];
    const f = files[name];
    return new Promise((resolve, reject) => {
      const fire = () => {
        if (opts.signal && opts.signal.aborted) return reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
        if (!f) return resolve(new Response("not found", { status: 404 }));
        resolve(new Response(f.body, { status: f.status || 200 }));
      };
      if (f && f.delayMs) setTimeout(fire, f.delayMs); else fire();
    });
  };
  const sandbox = {
    LEAN: lean, fetch: fetchStub, Response, ReadableStream, DecompressionStream, TextDecoderStream,
    AbortController, Uint8Array, setInterval, clearInterval, Date, JSON, Math, Promise, Error,
    Array, Object, String, Number, isFinite, Infinity, encodeURIComponent, Set, Map, RegExp,
    parseInt, parseFloat, isNaN, console,
    // the loader only calls these on paths these tests do not take, but the region references them
    document: undefined, $: () => null,
    fetchJsonMaybeGz: async (base, bust) => {
      const r = await fetchStub(`${base}.gz?t=${bust}`);
      if (!r.ok) throw new Error(`${base} missing`);
      return JSON.parse(zlib.gunzipSync(Buffer.from(await r.arrayBuffer())).toString("utf8"));
    },
  };
  vm.createContext(sandbox);
  const api = vm.runInContext(
    `"use strict";\n${PORTABLE}\n${LOADER}\n;({ loadBoardStreaming, boardPartsFromMeta, fetchFullBoardFallback, boardExpectedCount })`,
    sandbox,
  );
  return { ...api, calls };
}

function metaFor(counts) {
  let start = 0;
  const files = counts.map((n, i) => {
    const e = { name: `listings_part_${String(i).padStart(3, "0")}.json.gz`, start, end: start + n, records: n, bytes: 1, sha256: "0".repeat(64) };
    start += n;
    return e;
  });
  return { board_parts: { schema: "board-parts-v1", count: files.length, records: start, max_bytes: 25165824, rows_per_part: 3, files } };
}

// ---------------------------------------------------------------------------
test("boardPartsFromMeta accepts a well-formed block and reports the row total", () => {
  const S = load({ files: {} });
  const p = plain(S.boardPartsFromMeta(metaFor([3, 3, 2])));
  assert.equal(p.records, 8);
  assert.deepEqual(p.files.map((f) => [f.name, f.start, f.end, f.records]),
    [["listings_part_000.json.gz", 0, 3, 3], ["listings_part_001.json.gz", 3, 6, 3], ["listings_part_002.json.gz", 6, 8, 2]]);
});

test("boardPartsFromMeta refuses anything that is not exactly the writer's shape", () => {
  const S = load({ files: {} });
  const good = () => metaFor([3, 3, 2]);
  assert.equal(S.boardPartsFromMeta(null), null);
  assert.equal(S.boardPartsFromMeta({}), null);
  assert.equal(S.boardPartsFromMeta({ board_parts: [] }), null);
  const cases = {
    "wrong schema": (m) => { m.board_parts.schema = "board-parts-v9"; },
    "no files": (m) => { m.board_parts.files = []; },
    "names out of order": (m) => { m.board_parts.files.reverse(); },
    "a gap in the names": (m) => { m.board_parts.files[1].name = "listings_part_005.json.gz"; },
    "a path in a name": (m) => { m.board_parts.files[0].name = "../listings_part_000.json.gz"; },
    "rows not contiguous": (m) => { m.board_parts.files[1].start = 4; },
    "records != end - start": (m) => { m.board_parts.files[1].records = 9; },
    "negative": (m) => { m.board_parts.files[0].start = -1; },
    "non-integer": (m) => { m.board_parts.files[0].end = 2.5; },
    "declared total wrong": (m) => { m.board_parts.records = 99; },
    "declared count wrong": (m) => { m.board_parts.count = 7; },
  };
  for (const [why, mutate] of Object.entries(cases)) {
    const m = good();
    mutate(m);
    assert.equal(S.boardPartsFromMeta(m), null, why);
  }
});

// ---------------------------------------------------------------------------
test("desktop: every part is requested up front, and the rows come back in name order", async () => {
  const all = rows(0, 8);
  const files = {
    // the FIRST part is the slowest to answer: order must not depend on arrival order
    "listings_part_000.json.gz": { body: gz(all.slice(0, 3)), delayMs: 40 },
    "listings_part_001.json.gz": { body: gz(all.slice(3, 6)) },
    "listings_part_002.json.gz": { body: gz(all.slice(6, 8)), delayMs: 10 },
  };
  const S = load({ files });
  const parts = S.boardPartsFromMeta(metaFor([3, 3, 2]));
  const pending = S.loadBoardStreaming("2026-09-21T14:11:32.810745Z", null, null, parts);
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(S.calls.length, 3, "all three part requests are in flight before the first has answered");
  const out = plain(await pending);
  assert.deepEqual(out.map((r) => r.id), [0, 1, 2, 3, 4, 5, 6, 7], "index i is the join key: order is the contract");
  for (const c of S.calls) {
    assert.match(c, /^listings_part_00[012]\.json\.gz\?t=2026-09-21T14%3A11%3A32\.810745Z$/, "same ?t=<run_time> cache key as every payload file");
  }
});

test("desktop: a part with the wrong number of rows is refused with the mid-publish error", async () => {
  const files = {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: gz(rows(3, 4)) },     // run_meta says 3
  };
  const S = load({ files });
  await assert.rejects(S.loadBoardStreaming("t", null, null, S.boardPartsFromMeta(metaFor([3, 3]))),
    (e) => /^BOARD_COUNT:7:6$/.test(e.message));
});

test("desktop: the slim count from run_meta.board must agree with the parts too", async () => {
  const files = {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: gz(rows(3, 3)) },
  };
  const S = load({ files });
  const board = { schema: "slim-v1", count: 7 };
  await assert.rejects(S.loadBoardStreaming("t", null, board, S.boardPartsFromMeta(metaFor([3, 3]))),
    (e) => /^BOARD_COUNT:6:7$/.test(e.message));
  const ok = await S.loadBoardStreaming("t", null, { schema: "slim-v1", count: 6 }, S.boardPartsFromMeta(metaFor([3, 3])));
  assert.equal(ok.length, 6);
});

test("desktop: a missing part or a truncated part fails loudly, never a short board", async () => {
  const S1 = load({ files: {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: "gone", status: 404 },
  } });
  await assert.rejects(S1.loadBoardStreaming("t", null, null, S1.boardPartsFromMeta(metaFor([3, 3]))), /board part missing: listings_part_001/);

  const full = gz(rows(3, 3));
  const S2 = load({ files: {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: full.subarray(0, full.length - 8) },   // cut the gzip trailer
  } });
  await assert.rejects(S2.loadBoardStreaming("t", null, null, S2.boardPartsFromMeta(metaFor([3, 3]))));
});

test("desktop: a part served already inflated (no gzip magic) still loads", async () => {
  const S = load({ files: {
    "listings_part_000.json.gz": { body: Buffer.from(JSON.stringify(rows(0, 2))) },
    "listings_part_001.json.gz": { body: gz(rows(2, 2)) },
  } });
  const out = await S.loadBoardStreaming("t", null, null, S.boardPartsFromMeta(metaFor([2, 2])));
  assert.deepEqual(plain(out).map((r) => r.id), [0, 1, 2, 3]);
});

test("desktop without parts in run_meta still loads the single listings.json.gz (pre-split publish, rollback)", async () => {
  const S = load({ files: { "listings.json.gz": { body: gz(rows(0, 5)) } } });
  const out = await S.loadBoardStreaming("t", null, null, null);
  assert.equal(out.length, 5);
  assert.deepEqual(S.calls.map((c) => c.split("?")[0]), ["listings.json.gz"]);
});

test("progress is reported across parts", async () => {
  const S = load({ files: {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: gz(rows(3, 3)) },
  } });
  const seen = [];
  await S.loadBoardStreaming("t", (n) => seen.push(n), null, S.boardPartsFromMeta(metaFor([3, 3])));
  assert.equal(seen[seen.length - 1], 6);
  assert.ok(seen.every((n, i) => i === 0 || n >= seen[i - 1]), "monotonic");
});

// ---------------------------------------------------------------------------
test("a phone takes the slim file and never fetches a part when slim exists", async () => {
  const slim = rows(0, 4).map((r) => ({ ...r }));
  const S = load({ lean: true, files: {
    "listings_slim.json.gz": { body: gz(slim) },
    "listings_part_000.json.gz": { body: gz(rows(0, 4)) },
  } });
  const out = await S.loadBoardStreaming("t", null, { schema: "slim-v1", count: 4 }, S.boardPartsFromMeta(metaFor([4])));
  assert.equal(out.length, 4);
  assert.deepEqual(S.calls.map((c) => c.split("?")[0]), ["listings_slim.json.gz"]);
});

test("a phone whose slim file 404s falls back to the parts, two in flight at most", async () => {
  const S = load({ lean: true, files: {
    // part 0 is slow, so while it is outstanding the window (two parts) is all that may be in flight
    "listings_part_000.json.gz": { body: gz(rows(0, 2)), delayMs: 40 },
    "listings_part_001.json.gz": { body: gz(rows(2, 2)) },
    "listings_part_002.json.gz": { body: gz(rows(4, 2)), delayMs: 5 },
    "listings_part_003.json.gz": { body: gz(rows(6, 2)) },
  } });
  const parts = S.boardPartsFromMeta(metaFor([2, 2, 2, 2]));
  const pending = S.loadBoardStreaming("t", null, null, parts);
  await new Promise((r) => setTimeout(r, 10));
  const early = S.calls.map((c) => c.split("?")[0]);
  assert.equal(early[0], "listings_slim.json.gz");
  assert.ok(early.filter((c) => c.startsWith("listings_part_")).length <= 2, "a phone never buffers the whole board");
  const out = plain(await pending);
  assert.deepEqual(out.map((r) => r.parcel_id), ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"]);
});

// ---------------------------------------------------------------------------
test("the fetch fallback (no streaming) concatenates parts fetched in parallel and holds the same counts", async () => {
  const S = load({ files: {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: gz(rows(3, 2)) },
  } });
  const out = plain(await S.fetchFullBoardFallback("t", S.boardPartsFromMeta(metaFor([3, 2])), null));
  assert.deepEqual(out.map((r) => r.id), [0, 1, 2, 3, 4]);
  const S2 = load({ files: {
    "listings_part_000.json.gz": { body: gz(rows(0, 3)) },
    "listings_part_001.json.gz": { body: gz(rows(3, 1)) },
  } });
  await assert.rejects(S2.fetchFullBoardFallback("t", S2.boardPartsFromMeta(metaFor([3, 2])), null), /BOARD_COUNT:/);
});

// ---------------------------------------------------------------------------
test("session handling: a part URL is a data URL, so the fetch guard checks it like every payload file", () => {
  const sb = { Object, Array, String, Number, JSON, Date, URL, isNaN };
  vm.createContext(sb);
  const G = vm.runInContext(`"use strict";\n${IOGUARD}\n;({ isDataUrl, sessionProblem })`, sb);
  const ORIGIN = "https://board.example.com";
  assert.equal(G.isDataUrl("listings_part_000.json.gz?t=2026-09-21T13%3A45%3A12Z", ORIGIN), true);
  assert.equal(G.isDataUrl(`${ORIGIN}/listings_part_003.json.gz`, ORIGIN), true);
  assert.match(G.sessionProblem({ ok: false, status: 403, type: "basic", redirected: false, headers: { get: () => null } }, ORIGIN), /HTTP 403/);
});

test("the dashboard no longer names the single board file anywhere except the pre-split fallback", () => {
  const uses = JS.split("\n").filter((l) => /["'`]listings\.json\.gz["'`]/.test(l) && !l.trim().startsWith("//") && !l.trim().startsWith("*"));
  assert.equal(uses.length, 1, uses.join("\n"));
  assert.match(uses[0], /const BOARD_FAT_FILE = "listings\.json\.gz";/);
});

test("index.html bumps the dashboard cache-buster for this change", () => {
  const m = /dashboard\.js\?v=(\d{8}[a-z]?)/.exec(HTML);
  assert.ok(m, "dashboard.js must be loaded with a ?v= cache-buster");
  assert.notEqual(m[1], "20260921a", "the cache-buster must move when dashboard.js changes");
});
