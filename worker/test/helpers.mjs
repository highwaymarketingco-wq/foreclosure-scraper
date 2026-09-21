// Test doubles for the Worker: an in-memory R2 bucket, a static-assets binding,
// a fake ExecutionContext, and a JWT signing kit backed by a stub JWKS fetch.
// Nothing here touches the network or any Cloudflare service.

import { createHash } from "node:crypto";
import worker from "../src/index.js";
import { resetAccessState } from "../src/access.js";
import { resetBucketState } from "../src/bucket.js";
import { resetCspState } from "../src/csp.js";

export const TEAM = "testteam";
export const TEAM_ORIGIN = `https://${TEAM}.cloudflareaccess.com`;
export const AUD = "a".repeat(64);
export const HOST = "https://board.example.com";

export function resetAll() {
  resetAccessState();
  resetBucketState();
  resetCspState();
}

const enc = new TextEncoder();
const md5 = (bytes) => createHash("md5").update(bytes).digest("hex");
const toBytes = (v) => (typeof v === "string" ? enc.encode(v) : v);

// ---------------------------------------------------------------------------
// Fake R2 bucket. Mirrors the parts of the real API the Worker uses:
// get(key, {onlyIf: Headers, range: {offset,length}|{offset}|{suffix}}) returning
// an object WITH body, an object WITHOUT body (precondition failed), or null;
// and head(key). An unsatisfiable range throws, as the real service does.

export class FakeR2 {
  constructor(objects = {}) {
    this.objects = new Map();
    this.log = []; // { op, key, options }
    this.bodyReads = 0; // times a buffering method (json/text/arrayBuffer/blob) was called
    for (const [k, v] of Object.entries(objects)) this.put(k, v);
  }

  put(key, value) {
    const bytes = toBytes(value);
    this.objects.set(key, { bytes, etag: md5(bytes), uploaded: new Date("2026-09-21T14:00:00Z") });
  }

  delete(key) {
    this.objects.delete(key);
  }

  _meta(key, o, extra = {}) {
    return {
      key,
      size: o.bytes.length,
      etag: o.etag,
      httpEtag: `"${o.etag}"`,
      uploaded: o.uploaded,
      writeHttpMetadata() {},
      ...extra,
    };
  }

  async head(key) {
    this.log.push({ op: "head", key });
    const o = this.objects.get(key);
    return o ? this._meta(key, o) : null;
  }

  async get(key, options = {}) {
    this.log.push({ op: "get", key, options });
    const o = this.objects.get(key);
    if (!o) return null;
    const size = o.bytes.length;

    const cond = options.onlyIf;
    if (cond) {
      const inm = cond.get("if-none-match");
      const im = cond.get("if-match");
      const etag = `"${o.etag}"`;
      if ((inm && (inm === "*" || inm.split(",").map((s) => s.trim()).includes(etag))) || (im && im !== "*" && im !== etag)) {
        return this._meta(key, o); // no body: precondition failed
      }
    }

    let start = 0;
    let length = size;
    let rangeInfo;
    if (options.range) {
      const r = options.range;
      if (r.suffix !== undefined) {
        length = Math.min(r.suffix, size);
        start = size - length;
      } else {
        start = r.offset ?? 0;
        if (start >= size) throw new Error("get: The requested range is not satisfiable (10039)");
        length = r.length !== undefined ? Math.min(r.length, size - start) : size - start;
      }
      rangeInfo = { offset: start, length };
    }
    const slice = o.bytes.slice(start, start + length);
    const self = this;
    return this._meta(key, o, {
      range: rangeInfo,
      body: new ReadableStream({
        start(c) {
          c.enqueue(slice);
          c.close();
        },
      }),
      bodyUsed: false,
      async json() {
        self.bodyReads++;
        return JSON.parse(new TextDecoder().decode(slice));
      },
      async text() {
        self.bodyReads++;
        return new TextDecoder().decode(slice);
      },
      async arrayBuffer() {
        self.bodyReads++;
        return slice.buffer.slice(slice.byteOffset, slice.byteOffset + slice.byteLength);
      },
      async blob() {
        self.bodyReads++;
        return new Blob([slice]);
      },
    });
  }
}

// ---------------------------------------------------------------------------
// Fake static assets binding. Emulates the default html_handling: "/" serves
// index.html, and "/index.html" answers a redirect to "/" (which the Worker must
// avoid by asking for "/").

export class FakeAssets {
  constructor(files = {}) {
    this.files = new Map(Object.entries(files)); // path -> string|bytes
    this.calls = [];
  }

  async fetch(input) {
    const req = input instanceof Request ? input : new Request(input);
    const path = new URL(req.url).pathname;
    this.calls.push({ path, method: req.method });
    if (path === "/index.html") return new Response(null, { status: 307, headers: { location: "/" } });
    const key = path === "/" ? "/index.html" : path;
    if (!this.files.has(key)) return new Response("Not found", { status: 404 });
    const bytes = toBytes(this.files.get(key));
    const etag = `"${md5(bytes)}"`;
    const inm = req.headers.get("if-none-match");
    if (inm && inm === etag) return new Response(null, { status: 304, headers: { etag } });
    return new Response(req.method === "HEAD" ? null : bytes, { status: 200, headers: { etag, "content-type": "application/octet-stream" } });
  }
}

export const INLINE_HASH = "sha256-" + "A".repeat(43) + "=";
export const HANDLER_HASH = "sha256-" + "B".repeat(43) + "=";

export const DEFAULT_ASSETS = {
  "/index.html": '<!doctype html><title>t</title><script src="dashboard.js"></script>',
  "/dashboard.js": "console.log(1)",
  "/style.css": "body{}",
  "/premium.css": "body{}",
  "/manifest.json": '{"name":"x"}',
  "/icons/icon-192.png": new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
  "/csp-hashes.json": JSON.stringify({ scripts: [INLINE_HASH], handlers: [HANDLER_HASH], warnings: [] }),
};

// ---------------------------------------------------------------------------
// A small realistic bucket: two releases and a pointer at the newer one.

export const REL_OLD = "20260920T101010Z";
export const REL_NEW = "20260921T141132Z";
export const RUN_TIME_OLD = "2026-09-20T10:10:10.123456Z";
export const RUN_TIME_NEW = "2026-09-21T14:11:32.810745Z";

// Bytes that begin with the gzip magic 1f 8b, as the real payloads do.
export function gzBytes(len, seed = 0) {
  const b = new Uint8Array(len);
  for (let i = 0; i < len; i++) b[i] = (i * 31 + seed) & 0xff;
  b[0] = 0x1f;
  b[1] = 0x8b;
  return b;
}

export function makeBucket() {
  const r2 = new FakeR2();
  for (const [rel, seed, rt] of [
    [REL_OLD, 1, RUN_TIME_OLD],
    [REL_NEW, 2, RUN_TIME_NEW],
  ]) {
    r2.put(`releases/${rel}/listings_slim.json.gz`, gzBytes(1000, seed));
    r2.put(`releases/${rel}/listings.json.gz`, gzBytes(2000, seed));
    r2.put(`releases/${rel}/listings_detail.json.gz`, gzBytes(500, seed));
    r2.put(`releases/${rel}/detail_shards/00000.json.gz`, gzBytes(200, seed));
    r2.put(`releases/${rel}/detail_shards/00003.json.gz`, gzBytes(300, seed));
    r2.put(`releases/${rel}/run_meta.json`, JSON.stringify({ run_time: rt, release_marker: rel }));
    r2.put(`releases/${rel}/multifamily.json`, JSON.stringify({ rel }));
    r2.put(`releases/${rel}/foreclosure_sold_pool.json`, JSON.stringify({ rel }));
  }
  r2.put("current.json", JSON.stringify({ release: REL_NEW, published_at: "2026-09-21T14:30:00Z", board_count: 170066 }));
  r2.put("parcel_photos/buncombe_0605781823.jpg", new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]));
  r2.put("parcel_photos/streetview/sc_spartanburg_7_16_05_046_00.jpg", new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 9]));
  return r2;
}

export function makeEnv(overrides = {}) {
  return {
    BOARD: makeBucket(),
    ASSETS: new FakeAssets(DEFAULT_ASSETS),
    ACCESS_TEAM_DOMAIN: TEAM,
    ACCESS_AUD: AUD,
    ACCESS_ENFORCE: "true",
    POINTER_TTL_SECONDS: "0", // tests flip the pointer; production default is 30
    ...overrides,
  };
}

export function makeCtx(access) {
  return { waitUntil() {}, passThroughOnException() {}, ...(access ? { access } : {}) };
}

// ---------------------------------------------------------------------------
// JWT kit: a real RSA key pair, tokens signed with WebCrypto, and a stub fetch
// that serves the matching JWKS (or fails) instead of the real certs URL.

const b64u = (bytes) => Buffer.from(bytes).toString("base64url");

export async function makeJwtKit(kid = "kid-1") {
  const pair = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"]
  );
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const kit = {
    kid,
    privateKey: pair.privateKey,
    publicJwk: { kty: jwk.kty, n: jwk.n, e: jwk.e, kid, alg: "RS256", use: "sig" },
    async sign(payload, { kid: k = kid, alg = "RS256", key = pair.privateKey, header = {} } = {}) {
      const h = b64u(enc.encode(JSON.stringify({ alg, kid: k, typ: "JWT", ...header })));
      const p = b64u(enc.encode(JSON.stringify(payload)));
      const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, enc.encode(`${h}.${p}`));
      return `${h}.${p}.${b64u(new Uint8Array(sig))}`;
    },
    claims(over = {}) {
      const now = Math.floor(Date.now() / 1000);
      return {
        aud: [AUD],
        email: "cash@example.com",
        exp: now + 3600,
        iat: now - 10,
        nbf: now - 10,
        iss: TEAM_ORIGIN,
        type: "app",
        sub: "abc",
        ...over,
      };
    },
    async token(over = {}, opts = {}) {
      return this.sign(this.claims(over), opts);
    },
  };
  return kit;
}

/** Replace globalThis.fetch with a stub that serves JWKS for the team's certs URL. */
export function stubJwks(kits, { fail = false } = {}) {
  const original = globalThis.fetch;
  const stub = { calls: 0, urls: [], fail, restore() { globalThis.fetch = original; } };
  globalThis.fetch = async (url) => {
    stub.calls++;
    stub.urls.push(String(url));
    if (stub.fail) return new Response("nope", { status: 503 });
    if (String(url) !== `${TEAM_ORIGIN}/cdn-cgi/access/certs`) return new Response("unexpected url", { status: 500 });
    const list = Array.isArray(kits) ? kits : [kits];
    return new Response(JSON.stringify({ keys: list.map((k) => k.publicJwk), public_cert: {}, public_certs: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return stub;
}

// ---------------------------------------------------------------------------

/** Call the Worker. `token` becomes the Cf-Access-Jwt-Assertion header. */
export async function call(env, path, { method = "GET", headers = {}, token, ctx, host = HOST } = {}) {
  const h = new Headers(headers);
  if (token) h.set("cf-access-jwt-assertion", token);
  const req = new Request(host + path, { method, headers: h });
  return worker.fetch(req, env, ctx || makeCtx());
}

export async function bodyBytes(res) {
  return new Uint8Array(await res.arrayBuffer());
}
