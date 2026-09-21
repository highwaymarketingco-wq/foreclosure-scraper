import test, { before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  AUD, DEFAULT_ASSETS, FakeAssets, HANDLER_HASH, INLINE_HASH, REL_NEW, REL_OLD, RUN_TIME_NEW, RUN_TIME_OLD,
  bodyBytes, call, gzBytes, makeCtx, makeEnv, makeJwtKit, resetAll, stubJwks,
} from "./helpers.mjs";

let kit;
let stub;
let token;

before(async () => {
  kit = await makeJwtKit("kid-1");
});
beforeEach(async () => {
  resetAll();
  stub = stubJwks(kit);
  token = await kit.token();
});
afterEach(() => stub.restore());

const get = (env, path, opts = {}) => call(env, path, { token, ...opts });
const isGzipMagic = (b) => b[0] === 0x1f && b[1] === 0x8b;

// ---- the gate ---------------------------------------------------------------

test("gate: every path is refused without the Access header, and nothing leaks", async () => {
  const env = makeEnv();
  const paths = [
    "/", "/index.html", "/dashboard.js", "/robots.txt", "/healthz", "/current.json", "/run_meta.json",
    "/listings_slim.json.gz", "/listings.json.gz", "/listings_part_000.json.gz", "/detail_shards/00003.json.gz",
    "/parcel_photos/buncombe_0605781823.jpg", "/nothing", "/.env",
  ];
  for (const p of paths) {
    const res = await call(env, p);
    assert.equal(res.status, 403, p);
    assert.equal(await res.text(), "Forbidden", p);
    assert.equal(res.headers.get("cache-control"), "no-store", p);
    assert.equal(res.headers.get("x-robots-tag"), "noindex, nofollow, noarchive", p);
  }
  assert.equal(env.BOARD.log.length, 0, "the bucket is not even read for an unauthenticated request");
  assert.equal(env.ASSETS.calls.length, 0, "nor the assets");
});

test("gate: POST and other methods are refused before and after auth", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "/", { method: "POST" })).status, 403);
  const res = await get(env, "/", { method: "POST" });
  assert.equal(res.status, 405);
  assert.equal(res.headers.get("allow"), "GET, HEAD");
  assert.equal((await get(env, "/", { method: "OPTIONS" })).status, 405, "no CORS preflight is ever answered");
  assert.equal(res.headers.get("access-control-allow-origin"), null);
});

test("gate: invalid tokens are refused (wrong aud, expired, forged)", async () => {
  const env = makeEnv();
  const wrongAud = await kit.token({ aud: ["e".repeat(64)] });
  const expired = await kit.token({ exp: Math.floor(Date.now() / 1000) - 600 });
  const other = await makeJwtKit("kid-1");
  const forged = await other.token();
  for (const t of [wrongAud, expired, forged, "garbage"]) {
    assert.equal((await call(env, "/healthz", { token: t })).status, 403);
  }
  assert.equal((await call(env, "/healthz", { token })).status, 200);
});

test("gate: unconfigured Worker answers 503 to everything and reads nothing", async () => {
  const env = makeEnv({ ACCESS_TEAM_DOMAIN: "REPLACE_WITH_TEAM.cloudflareaccess.com", ACCESS_AUD: "REPLACE_WITH_ACCESS_APPLICATION_AUD_TAG" });
  for (const p of ["/", "/healthz", "/listings_slim.json.gz"]) {
    const res = await call(env, p, { token });
    assert.equal(res.status, 503, p);
  }
  assert.equal(env.BOARD.log.length, 0);
});

test("gate: AUTH_DEBUG exposes the refusal reason only when switched on", async () => {
  const quiet = await call(makeEnv(), "/healthz");
  assert.equal(quiet.headers.get("x-auth-deny"), null);
  const loud = await call(makeEnv({ AUTH_DEBUG: "true" }), "/healthz");
  assert.equal(loud.headers.get("x-auth-deny"), "missing_jwt");
});

test("gate: ctx.access authenticates a request that has no JWT header", async () => {
  const env = makeEnv();
  const res = await call(env, "/healthz", { ctx: makeCtx({ aud: AUD }) });
  assert.equal(res.status, 200);
  assert.equal((await res.json()).auth, "ctx");
  const bad = await call(env, "/healthz", { ctx: makeCtx({ aud: "f".repeat(64) }) });
  assert.equal(bad.status, 403);
});

test("gate: ACCESS_ENFORCE=false works on localhost and is refused on a public host", async () => {
  const env = makeEnv({ ACCESS_ENFORCE: "false", ACCESS_TEAM_DOMAIN: undefined, ACCESS_AUD: undefined });
  const local = await call(env, "/healthz", { host: "http://localhost:8787" });
  assert.equal(local.status, 200);
  assert.equal((await local.json()).auth, "bypass-dev");
  const pub = await call(env, "/healthz");
  assert.equal(pub.status, 500);
  assert.equal(await pub.text(), "Forbidden");
});

test("gate: the certs are fetched once for many requests", async () => {
  const env = makeEnv();
  for (let i = 0; i < 25; i++) assert.equal((await get(env, "/healthz")).status, 200);
  assert.equal(stub.calls, 1);
});

// ---- the allowlist -----------------------------------------------------------

test("allowlist: denied paths answer 404 for an authenticated user", async () => {
  const env = makeEnv();
  const denied = [
    "/.env", "/.git/config", "/README.md", "/crm.json", "/outreach_maillist.csv", "/listings.json",
    "/listings_slim.json", "/listings_detail.json", "/detail_shards/00003.json", "/parcel_photos/.gitkeep",
    "/releases/20260921T141132Z/listings.json.gz", "/csp-hashes.json", "/src/index.js", "/wrangler.jsonc",
    "/parcel_photos/..%2f..%2fcurrent.json", "/parcel_photos/%2e%2e/.env", "/parcel_photos/%2E%2E/%2E%2E/README.md", "/parcel_photos/a/b/c.jpg", "/detail_shards/00003.json.gz.bak",
  ];
  for (const p of denied) {
    const res = await get(env, p);
    assert.equal(res.status, 404, p);
    assert.equal(await res.text(), "Not found", p);
  }
  assert.equal(env.BOARD.log.length, 0, "denied paths never reach the bucket");
  assert.equal(env.ASSETS.calls.length, 0, "or the assets");
});

test("allowlist: a key that is allowlisted by name but absent gives 404, not a fallback", async () => {
  const env = makeEnv();
  assert.equal((await get(env, "/detail_shards/00099.json.gz")).status, 404);
  assert.equal((await get(env, "/parcel_photos/missing.jpg")).status, 404);
  assert.equal((await get(env, "/land_buyers.json")).status, 404);
});

test("robots.txt disallows everything; healthz reports the release", async () => {
  const env = makeEnv();
  const robots = await get(env, "/robots.txt");
  assert.equal(robots.status, 200);
  assert.equal(await robots.text(), "User-agent: *\nDisallow: /\n");
  const h = await get(env, "/healthz");
  assert.equal(h.status, 200);
  const j = await h.json();
  assert.equal(j.ok, true);
  assert.equal(j.release, REL_NEW);
  assert.equal(j.board_count, 170066);
  assert.equal(h.headers.get("cache-control"), "no-store");
});

test("healthz is 503 before anything has been published", async () => {
  const env = makeEnv();
  env.BOARD.delete("current.json");
  const res = await get(env, "/healthz");
  assert.equal(res.status, 503);
  assert.deepEqual(await res.json(), { ok: false, release: null, error: "no release published" });
  assert.equal((await get(env, "/run_meta.json")).status, 503);
});

test("a malformed pointer is ignored (path traversal in the release name)", async () => {
  const env = makeEnv();
  env.BOARD.put("current.json", JSON.stringify({ release: "../../etc" }));
  assert.equal((await get(env, "/healthz")).status, 503);
  env.BOARD.put("current.json", "not json");
  assert.equal((await get(env, "/healthz")).status, 503);
});

// ---- pointer and release resolution ------------------------------------------

test("pointer: run_meta.json comes from the release current.json names", async () => {
  const env = makeEnv();
  const res = await get(env, "/run_meta.json");
  assert.equal(res.status, 200);
  assert.equal((await res.json()).release_marker, REL_NEW);
  assert.equal(res.headers.get("x-release"), REL_NEW);
  // Roll back: point at the older release. The next request follows immediately (TTL 0 in tests).
  env.BOARD.put("current.json", JSON.stringify({ release: REL_OLD }));
  const back = await get(env, "/run_meta.json");
  assert.equal((await back.json()).release_marker, REL_OLD);
});

test("pointer: cached in the isolate for POINTER_TTL_SECONDS, so R2 is not read per request", async () => {
  const env = makeEnv({ POINTER_TTL_SECONDS: "30" });
  await get(env, "/healthz");
  await get(env, "/healthz");
  await get(env, "/multifamily.json");
  const pointerReads = env.BOARD.log.filter((l) => l.key === "current.json").length;
  assert.equal(pointerReads, 1);
  // A flip is not seen inside the window ...
  env.BOARD.put("current.json", JSON.stringify({ release: REL_OLD }));
  assert.equal((await (await get(env, "/healthz")).json()).release, REL_NEW);
});

test("pointer: if the pointer goes missing later, the last good release keeps serving", async () => {
  const env = makeEnv({ POINTER_TTL_SECONDS: "0" });
  assert.equal((await get(env, "/healthz")).status, 200);
  env.BOARD.delete("current.json");
  const res = await get(env, "/multifamily.json");
  assert.equal(res.status, 200);
  assert.equal((await res.json()).rel, REL_NEW);
});

test("/current.json is served no-store and is not confused with a release file", async () => {
  const env = makeEnv();
  const res = await get(env, "/current.json");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("cache-control"), "no-store");
  assert.equal((await res.json()).release, REL_NEW);
});

test("run_meta.json is no-store, even when a ?t= is given", async () => {
  const env = makeEnv();
  for (const q of ["", `?t=${Date.now()}`, `?t=${encodeURIComponent(RUN_TIME_OLD)}`]) {
    const res = await get(env, `/run_meta.json${q}`);
    assert.equal(res.headers.get("cache-control"), "no-store", q);
    assert.equal((await res.json()).release_marker, REL_NEW, `${q}: run_meta always describes the current release`);
  }
});

test("?t=<run_time> pins the release, so a stale tab never reads shards from a newer board", async () => {
  const env = makeEnv();
  // Pointer is at REL_NEW. A tab that loaded REL_OLD asks for a shard with its own run_time.
  const q = `?t=${encodeURIComponent(RUN_TIME_OLD)}`;
  const shard = await get(env, `/detail_shards/00003.json.gz${q}`);
  assert.equal(shard.status, 200);
  assert.equal(shard.headers.get("x-release"), REL_OLD);
  assert.deepEqual(await bodyBytes(shard), gzBytes(300, 1), "bytes of the OLD release");
  assert.equal(shard.headers.get("cache-control"), "private, max-age=31536000, immutable");
  // Colons unencoded, as dashboard.js builds shard URLs.
  const raw = await get(env, `/detail_shards/00003.json.gz?t=${RUN_TIME_NEW}`);
  assert.equal(raw.headers.get("x-release"), REL_NEW);
  assert.deepEqual(await bodyBytes(raw), gzBytes(300, 2));
});

test("?t= for a release that has been pruned is a 404, never the newer board", async () => {
  const env = makeEnv();
  const res = await get(env, `/listings_slim.json.gz?t=${encodeURIComponent("2026-01-01T00:00:00.000000Z")}`);
  assert.equal(res.status, 404);
  assert.equal(res.headers.get("cache-control"), "no-store");
});

test("without a usable ?t= the current release is served and must be revalidated", async () => {
  const env = makeEnv();
  for (const q of ["", "?t=", `?t=${Date.now()}`, "?t=not-a-time", "?t=../../x", `?t=${encodeURIComponent("2026-09-20T10:10:10+00:00")}`]) {
    const res = await get(env, `/listings_slim.json.gz${q}`);
    assert.equal(res.status, 200, q);
    assert.equal(res.headers.get("x-release"), REL_NEW, q);
    assert.equal(res.headers.get("cache-control"), "private, no-cache", q);
  }
});

test("a hostile ?t= cannot select an arbitrary key", async () => {
  const env = makeEnv();
  await get(env, `/listings_slim.json.gz?t=${encodeURIComponent("2026-09-21T14:11:32.810745Z/../../current")}`);
  await get(env, `/listings_slim.json.gz?t=${encodeURIComponent("../current.json")}`);
  for (const l of env.BOARD.log) {
    assert.match(l.key, /^(current\.json|releases\/[0-9A-Za-z]+\/listings_slim\.json\.gz)$/);
  }
});

// ---- headers for the gzip payloads -------------------------------------------

test("gzip payloads are served as opaque application/gzip with NO Content-Encoding", async () => {
  const env = makeEnv();
  for (const p of ["/listings_slim.json.gz", "/listings.json.gz", "/listings_detail.json.gz", "/detail_shards/00003.json.gz"]) {
    const res = await get(env, p);
    assert.equal(res.status, 200, p);
    assert.equal(res.headers.get("content-type"), "application/gzip", p);
    assert.equal(res.headers.get("content-encoding"), null, `${p}: dashboard.js sniffs 1f 8b and inflates itself`);
    assert.equal(res.headers.get("accept-ranges"), "bytes", p);
    assert.ok(res.headers.get("etag"), p);
    assert.ok(isGzipMagic(await bodyBytes(res)), `${p}: bytes are passed through untouched`);
  }
});

test("board parts are served from the pinned release, with their own bytes, immutable when pinned", async () => {
  const env = makeEnv();
  for (let i = 0; i < 3; i++) {
    const name = `/listings_part_${String(i).padStart(3, "0")}.json.gz`;
    // pinned to the OLDER release: the part comes from that release, not from "current"
    const old = await get(env, `${name}?t=${RUN_TIME_OLD}`);
    assert.equal(old.status, 200, name);
    assert.equal(old.headers.get("x-release"), REL_OLD, name);
    assert.equal(old.headers.get("content-type"), "application/gzip", name);
    assert.equal(old.headers.get("content-encoding"), null, name);
    assert.equal(old.headers.get("cache-control"), "private, max-age=31536000, immutable", name);
    assert.deepEqual(await bodyBytes(old), gzBytes(700 + i, 1 * 10 + i), `${name} (old release bytes)`);
    const cur = await get(env, `${name}?t=${RUN_TIME_NEW}`);
    assert.equal(cur.headers.get("x-release"), REL_NEW, name);
    assert.deepEqual(await bodyBytes(cur), gzBytes(700 + i, 2 * 10 + i), `${name} (new release bytes)`);
  }
  // a part the release does not have is a 404, never another release's file
  const missing = await get(env, `/listings_part_009.json.gz?t=${RUN_TIME_NEW}`);
  assert.equal(missing.status, 404);
});

test("json and photo content types", async () => {
  const env = makeEnv();
  assert.equal((await get(env, "/multifamily.json")).headers.get("content-type"), "application/json; charset=utf-8");
  assert.equal((await get(env, "/foreclosure_sold_pool.json")).headers.get("content-type"), "application/json; charset=utf-8");
  const photo = await get(env, "/parcel_photos/buncombe_0605781823.jpg");
  assert.equal(photo.headers.get("content-type"), "image/jpeg");
  assert.equal(photo.headers.get("cache-control"), "private, max-age=86400");
  assert.equal((await get(env, "/parcel_photos/streetview/sc_spartanburg_7_16_05_046_00.jpg")).status, 200);
});

// ---- Range --------------------------------------------------------------------

test("Range: bytes=0-1 returns 206 with the gzip magic and a correct Content-Range", async () => {
  const env = makeEnv();
  const res = await get(env, "/listings_slim.json.gz", { headers: { range: "bytes=0-1" } });
  assert.equal(res.status, 206);
  assert.equal(res.headers.get("content-range"), "bytes 0-1/1000");
  const b = await bodyBytes(res);
  assert.equal(b.length, 2);
  assert.ok(isGzipMagic(b));
  assert.equal(res.headers.get("content-encoding"), null);
});

test("Range: middle, open-ended, suffix, and clamped end", async () => {
  const env = makeEnv();
  const full = gzBytes(1000, 2);
  const cases = [
    ["bytes=100-199", 100, 200, "bytes 100-199/1000"],
    ["bytes=900-", 900, 1000, "bytes 900-999/1000"],
    ["bytes=-50", 950, 1000, "bytes 950-999/1000"],
    ["bytes=990-5000", 990, 1000, "bytes 990-999/1000"],
    ["bytes=-5000", 0, 1000, "bytes 0-999/1000"],
  ];
  for (const [range, a, b, cr] of cases) {
    const res = await get(env, "/listings_slim.json.gz", { headers: { range } });
    assert.equal(res.status, 206, range);
    assert.equal(res.headers.get("content-range"), cr, range);
    assert.deepEqual(await bodyBytes(res), full.slice(a, b), range);
  }
});

test("Range: unsatisfiable is 416 with the object size", async () => {
  const env = makeEnv();
  for (const range of ["bytes=1000-", "bytes=5000-6000", "bytes=-0"]) {
    const res = await get(env, "/listings_slim.json.gz", { headers: { range } });
    assert.equal(res.status, 416, range);
    assert.equal(res.headers.get("content-range"), "bytes */1000", range);
  }
});

test("Range: malformed or multi-range is ignored and the whole object is sent", async () => {
  const env = makeEnv();
  for (const range of ["bytes=0-1,5-6", "bytes=5-2", "items=0-5", "bytes=abc", "bytes=-", "bytes=0-1e3"]) {
    const res = await get(env, "/listings_slim.json.gz", { headers: { range } });
    assert.equal(res.status, 200, range);
    assert.equal((await bodyBytes(res)).length, 1000, range);
    assert.equal(res.headers.get("content-range"), null, range);
  }
});

test("Range with If-Range: honoured only for the current ETag", async () => {
  const env = makeEnv();
  const etag = (await get(env, "/listings_slim.json.gz")).headers.get("etag");
  const ok = await get(env, "/listings_slim.json.gz", { headers: { range: "bytes=0-9", "if-range": etag } });
  assert.equal(ok.status, 206);
  const stale = await get(env, "/listings_slim.json.gz", { headers: { range: "bytes=0-9", "if-range": '"old-etag"' } });
  assert.equal(stale.status, 200, "a changed object is resent whole, not stitched");
  assert.equal((await bodyBytes(stale)).length, 1000);
});

test("Range on a missing object is 404", async () => {
  const env = makeEnv();
  assert.equal((await get(env, "/detail_shards/00099.json.gz", { headers: { range: "bytes=0-1" } })).status, 404);
  assert.equal((await get(env, "/detail_shards/00099.json.gz", { headers: { range: "bytes=-0" } })).status, 404);
});

// ---- ETag and conditional requests ------------------------------------------------

test("ETag: If-None-Match returns 304 with no body and keeps the cache headers", async () => {
  const env = makeEnv();
  const first = await get(env, "/listings_slim.json.gz");
  const etag = first.headers.get("etag");
  assert.match(etag, /^"[0-9a-f]+"$/);
  const second = await get(env, "/listings_slim.json.gz", { headers: { "if-none-match": etag } });
  assert.equal(second.status, 304);
  assert.equal((await bodyBytes(second)).length, 0);
  assert.equal(second.headers.get("etag"), etag);
  assert.equal(second.headers.get("cache-control"), "private, no-cache");
  assert.equal(second.headers.get("x-content-type-options"), "nosniff");
  const other = await get(env, "/listings_slim.json.gz", { headers: { "if-none-match": '"something-else"' } });
  assert.equal(other.status, 200);
});

test("ETag: an If-Match that fails is 412", async () => {
  const env = makeEnv();
  const res = await get(env, "/listings_slim.json.gz", { headers: { "if-match": '"nope"' } });
  assert.equal(res.status, 412);
});

test("ETag: photos and shell files revalidate too", async () => {
  const env = makeEnv();
  const photo = await get(env, "/parcel_photos/buncombe_0605781823.jpg");
  const again = await get(env, "/parcel_photos/buncombe_0605781823.jpg", { headers: { "if-none-match": photo.headers.get("etag") } });
  assert.equal(again.status, 304);
  const html = await get(env, "/");
  const html2 = await get(env, "/", { headers: { "if-none-match": html.headers.get("etag") } });
  assert.equal(html2.status, 304);
  assert.equal(html2.headers.get("cache-control"), "private, no-cache");
});

test("HEAD returns headers and length with no body, and does not stream the object", async () => {
  const env = makeEnv();
  const res = await get(env, "/listings.json.gz", { method: "HEAD" });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-length"), "2000");
  assert.equal(res.headers.get("content-type"), "application/gzip");
  assert.equal(res.body, null);
  assert.ok(env.BOARD.log.every((l) => l.op !== "get" || l.key === "current.json"), "only head() was used for the payload");
});

// ---- streaming, no buffering ---------------------------------------------------------

test("big objects are streamed: the Worker never buffers or parses them", async () => {
  const env = makeEnv();
  env.BOARD.put(`releases/${REL_NEW}/listings.json.gz`, gzBytes(5 * 1024 * 1024, 7));
  const before = env.BOARD.bodyReads;
  const res = await get(env, "/listings.json.gz");
  assert.equal(res.status, 200);
  assert.ok(res.body instanceof ReadableStream, "body is a stream");
  // The only buffered read allowed is the ~100 byte pointer.
  assert.equal(env.BOARD.bodyReads - before, 1);
  const bytes = await bodyBytes(res);
  assert.equal(bytes.length, 5 * 1024 * 1024);
  // Second request: pointer is cached, so nothing at all is buffered.
  const env2 = makeEnv({ POINTER_TTL_SECONDS: "30" });
  await get(env2, "/healthz");
  const b2 = env2.BOARD.bodyReads;
  await bodyBytes(await get(env2, "/listings_slim.json.gz"));
  assert.equal(env2.BOARD.bodyReads, b2);
});

// ---- security headers -----------------------------------------------------------------

test("security headers are on every kind of response", async () => {
  const env = makeEnv();
  const responses = [
    await get(env, "/listings_slim.json.gz"),
    await get(env, "/multifamily.json"),
    await get(env, "/parcel_photos/buncombe_0605781823.jpg"),
    await get(env, "/dashboard.js"),
    await get(env, "/robots.txt"),
    await get(env, "/healthz"),
    await get(env, "/does-not-exist"),
    await call(env, "/"), // 403
    await get(env, "/", { method: "POST" }), // 405
    await get(env, "/listings_slim.json.gz", { headers: { range: "bytes=5000-" } }), // 416
    await get(env, "/listings_slim.json.gz", { headers: { "if-none-match": (await get(env, "/listings_slim.json.gz")).headers.get("etag") } }), // 304
  ];
  for (const res of responses) {
    const label = `${res.status}`;
    assert.equal(res.headers.get("x-content-type-options"), "nosniff", label);
    assert.equal(res.headers.get("referrer-policy"), "no-referrer", label);
    assert.equal(res.headers.get("x-robots-tag"), "noindex, nofollow, noarchive", label);
    assert.equal(res.headers.get("x-frame-options"), "DENY", label);
    assert.match(res.headers.get("strict-transport-security"), /max-age=\d+/, label);
    assert.match(res.headers.get("content-security-policy"), /default-src 'none'/, label);
    assert.equal(res.headers.get("access-control-allow-origin"), null, `${label}: no CORS, unlike the GitHub Pages site it replaces`);
  }
});

// ---- the shell ----------------------------------------------------------------------------

test("shell: / serves index.html with a hashed CSP; /index.html does not redirect", async () => {
  const env = makeEnv();
  const res = await get(env, "/");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "text/html; charset=utf-8");
  assert.equal(res.headers.get("x-csp-mode"), "hashed");
  assert.equal(res.headers.get("referrer-policy"), "strict-origin-when-cross-origin", "OSM tiles refuse no-referrer");
  const csp = res.headers.get("content-security-policy");
  assert.match(csp, /script-src 'self' https:\/\/unpkg\.com '/);
  assert.ok(csp.includes(`'${INLINE_HASH}'`));
  assert.ok(csp.includes(`'unsafe-hashes' '${HANDLER_HASH}'`));
  assert.ok(!/script-src[^;]*unsafe-inline/.test(csp), "hashed mode has no unsafe-inline for scripts");
  assert.match(csp, /connect-src 'self'/);
  assert.match(csp, /font-src https:\/\/fonts\.gstatic\.com/);
  assert.match(csp, /style-src 'self' 'unsafe-inline' https:\/\/fonts\.googleapis\.com https:\/\/unpkg\.com/);
  assert.match(csp, /img-src 'self' data: blob: https:/);
  assert.match(csp, /frame-ancestors 'none'/);
  const idx = await get(env, "/index.html");
  assert.equal(idx.status, 200, "the Worker asks the assets for / so it never sees the 307");
  assert.equal(await idx.text(), DEFAULT_ASSETS["/index.html"]);
});

test("shell: cache policy by file type and ?v=", async () => {
  const env = makeEnv();
  assert.equal((await get(env, "/")).headers.get("cache-control"), "private, no-cache");
  assert.equal((await get(env, "/manifest.json")).headers.get("cache-control"), "private, no-cache");
  assert.equal((await get(env, "/dashboard.js")).headers.get("cache-control"), "private, no-cache");
  assert.equal((await get(env, "/dashboard.js?v=20260921a")).headers.get("cache-control"), "private, max-age=3600");
  assert.equal((await get(env, "/style.css?v=20260811c")).headers.get("cache-control"), "private, max-age=3600");
  assert.equal((await get(env, "/dashboard.js?v=")).headers.get("cache-control"), "private, no-cache");
  const icon = await get(env, "/icons/icon-192.png");
  assert.equal(icon.status, 200);
  assert.equal(icon.headers.get("content-type"), "image/png");
  assert.equal(icon.headers.get("cache-control"), "private, max-age=86400");
  assert.equal((await get(env, "/manifest.json")).headers.get("content-type"), "application/manifest+json; charset=utf-8");
  assert.equal((await get(env, "/dashboard.js")).headers.get("content-type"), "text/javascript; charset=utf-8");
});

test("shell: only the shell allowlist reaches the assets binding", async () => {
  const env = makeEnv();
  await get(env, "/csp-hashes.json");
  await get(env, "/nothing.js");
  assert.equal(env.ASSETS.calls.length, 0);
  await get(env, "/premium.css");
  assert.deepEqual(env.ASSETS.calls.map((c) => c.path), ["/premium.css"]);
});

test("shell: csp-hashes.json is fetched once per isolate", async () => {
  const env = makeEnv();
  await get(env, "/");
  await get(env, "/");
  await get(env, "/index.html");
  assert.equal(env.ASSETS.calls.filter((c) => c.path === "/csp-hashes.json").length, 1);
});

test("shell: without csp-hashes.json the page still loads, in a labelled weaker mode", async () => {
  const assets = { ...DEFAULT_ASSETS };
  delete assets["/csp-hashes.json"];
  const env = makeEnv({ ASSETS: new FakeAssets(assets) });
  const res = await get(env, "/");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("x-csp-mode"), "relaxed-no-hashes");
  assert.match(res.headers.get("content-security-policy"), /script-src 'self' https:\/\/unpkg\.com 'unsafe-inline'/);
});

test("shell: a malformed hash list is not trusted", async () => {
  const assets = { ...DEFAULT_ASSETS, "/csp-hashes.json": JSON.stringify({ scripts: ["sha256-short"], handlers: [] }) };
  const env = makeEnv({ ASSETS: new FakeAssets(assets) });
  assert.equal((await get(env, "/")).headers.get("x-csp-mode"), "relaxed-no-hashes");
});

test("shell: CSP_RELAXED=true is the break-glass switch", async () => {
  const env = makeEnv({ CSP_RELAXED: "true" });
  const res = await get(env, "/");
  assert.equal(res.headers.get("x-csp-mode"), "relaxed");
  assert.ok(!res.headers.get("content-security-policy").includes("sha256-"));
});

test("shell: missing asset is a plain 404", async () => {
  const assets = { ...DEFAULT_ASSETS };
  delete assets["/premium.css"];
  const env = makeEnv({ ASSETS: new FakeAssets(assets) });
  assert.equal((await get(env, "/premium.css")).status, 404);
});

// ---- failure containment ---------------------------------------------------------------------

test("an unexpected bucket error is a bare 500 that leaks nothing", async () => {
  const env = makeEnv();
  env.BOARD.get = async (key) => {
    if (key === "current.json") throw new Error("secret internal detail: bucket foreclosure-board");
    throw new Error("secret internal detail");
  };
  const res = await get(env, "/multifamily.json");
  assert.equal(res.status, 503, "pointer unreadable and never cached: no release");
  const env2 = makeEnv();
  const realGet = env2.BOARD.get.bind(env2.BOARD);
  env2.BOARD.get = async (key, o) => {
    if (key.startsWith("releases/")) throw new Error("secret internal detail: r2 exploded");
    return realGet(key, o);
  };
  const res2 = await get(env2, "/multifamily.json");
  assert.equal(res2.status, 500);
  const text = await res2.text();
  assert.equal(text, "Server error");
  assert.ok(!text.includes("secret"));
  assert.equal(res2.headers.get("cache-control"), "no-store");
});

test("timing: authorised photo request end to end (informational)", async () => {
  const env = makeEnv({ POINTER_TTL_SECONDS: "30" });
  await get(env, "/healthz"); // warm keys and pointer
  const t0 = performance.now();
  const N = 300;
  for (let i = 0; i < N; i++) {
    const res = await get(env, "/parcel_photos/buncombe_0605781823.jpg");
    await res.arrayBuffer();
  }
  const per = (performance.now() - t0) / N;
  console.log(`# node timing, not workerd: ${per.toFixed(3)} ms per authorised photo request (JWT cached, R2 faked)`);
  assert.ok(per < 5, "pathologically slow");
});
