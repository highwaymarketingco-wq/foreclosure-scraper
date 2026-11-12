// worker/src/bucket.js
//
// Everything that touches the R2 bucket binding (env.BOARD): reading the
// release pointer, and streaming objects with Range and conditional support.
//
// CPU rule (Workers Free = 10 ms): nothing here parses or transforms a large
// object. Bodies are handed to the Response as the R2 stream. The only JSON
// parsed is the ~100 byte pointer file.
//
// R2 API facts used (Cloudflare docs, read 2026-09-21):
//   bucket.get(key, { onlyIf: Headers|R2Conditional, range: R2Range|Headers })
//   returns R2ObjectBody, or an R2Object with NO body when a precondition fails,
//   or null when the key is missing. head(key) returns metadata only.
//   https://developers.cloudflare.com/r2/api/workers/workers-api-reference/

import { isReleaseId } from "./routes.js";
import { secureResponse, textResponse } from "./security.js";

const DEFAULT_POINTER_TTL_S = 30;
const MAX_POINTER_TTL_S = 300;

const pointerState = { at: 0, value: null };

export function resetBucketState() {
  pointerState.at = 0;
  pointerState.value = null;
}

function pointerTtlMs(env) {
  const n = Number(env.POINTER_TTL_SECONDS);
  const s = Number.isFinite(n) && n >= 0 ? Math.min(n, MAX_POINTER_TTL_S) : DEFAULT_POINTER_TTL_S;
  return s * 1000;
}

/**
 * The current release named by current.json, cached in this isolate for
 * POINTER_TTL_SECONDS (default 30). If a refresh fails, the last good value is
 * kept. Returns { release, publishedAt, boardCount } or null when nothing has
 * been published or the pointer is malformed.
 */
export async function getPointer(env, now = Date.now()) {
  if (pointerState.value && now - pointerState.at < pointerTtlMs(env)) return pointerState.value;
  try {
    const obj = await env.BOARD.get("current.json");
    if (!obj || typeof obj.json !== "function") return pointerState.value; // missing: keep last good, else null
    const body = await obj.json();
    if (!body || !isReleaseId(body.release)) return pointerState.value;
    pointerState.value = {
      release: body.release,
      publishedAt: typeof body.published_at === "string" ? body.published_at : null,
      boardCount: typeof body.board_count === "number" ? body.board_count : null,
    };
    pointerState.at = now;
  } catch (e) {
    /* keep the last good pointer */
  }
  return pointerState.value;
}

// ---------------------------------------------------------------------------
// Range and conditional headers

/**
 * Parse a single-range `Range: bytes=...` header into an R2Range.
 * Returns null when the header should be ignored (malformed, multi-range, or
 * end < start): RFC 9110 lets a server ignore Range and send the whole thing.
 */
export function parseRange(header) {
  const m = /^bytes=(\d*)-(\d*)$/.exec(String(header || "").trim());
  if (!m) return null;
  const [, a, b] = m;
  if (a === "" && b === "") return null;
  if (a === "") {
    const n = Number(b);
    return Number.isSafeInteger(n) ? { suffix: n } : null;
  }
  const start = Number(a);
  if (!Number.isSafeInteger(start)) return null;
  if (b === "") return { offset: start };
  const end = Number(b);
  if (!Number.isSafeInteger(end) || end < start) return null;
  return { offset: start, length: end - start + 1 };
}

/** A Headers carrying only the conditional headers R2 understands (If-Range excluded). */
function conditionalHeaders(reqHeaders) {
  const out = new Headers();
  let any = false;
  for (const name of ["if-match", "if-none-match", "if-modified-since", "if-unmodified-since"]) {
    const v = reqHeaders.get(name);
    if (v) {
      out.set(name, v);
      any = true;
    }
  }
  return any ? out : null;
}

function resolveRange(obj, size) {
  const r = obj.range;
  if (!r) return null;
  let offset;
  let length;
  if (r.suffix !== undefined) {
    length = Math.min(r.suffix, size);
    offset = size - length;
  } else {
    offset = r.offset ?? 0;
    length = r.length !== undefined ? Math.min(r.length, size - offset) : size - offset;
  }
  return { offset, length };
}

async function rangeNotSatisfiable(env, key, cacheControl) {
  const head = await env.BOARD.head(key);
  if (!head) return null;
  return secureResponse(null, {
    status: 416,
    headers: { "content-range": `bytes */${head.size}`, "cache-control": cacheControl, "accept-ranges": "bytes" },
  });
}

// ---------------------------------------------------------------------------
// Serving

/**
 * Stream one bucket object.
 *
 * @param {Request} request
 * @param {*} env
 * @param {string} key                R2 key
 * @param {{contentType: string, cacheControl: string, release?: string}} opts
 *
 * Never sets Content-Encoding: the .gz files are served as opaque
 * application/gzip bytes, which is what GitHub Pages serves today and what
 * dashboard.js sniffs for (bytes 1f 8b) and inflates itself.
 */
export async function serveObject(request, env, key, opts) {
  const { contentType, cacheControl, release } = opts;
  const tag = (h) => {
    if (release) h["x-release"] = release;
    return h;
  };

  if (request.method === "HEAD") {
    const head = await env.BOARD.head(key);
    if (!head) return notFound();
    return secureResponse(null, {
      status: 200,
      headers: tag({
        "content-type": contentType,
        "content-length": String(head.size),
        etag: head.httpEtag,
        "accept-ranges": "bytes",
        "cache-control": cacheControl,
      }),
    });
  }

  // Range: parsed here so an unsatisfiable one is a clean 416, never a 500.
  let range = parseRange(request.headers.get("range"));
  if (range && range.suffix === 0) {
    const r = await rangeNotSatisfiable(env, key, cacheControl);
    return r || notFound();
  }
  const ifRange = request.headers.get("if-range");
  if (range && ifRange) {
    // R2 does not evaluate If-Range, so do it here: only honour the range when
    // the validator is the object's current strong ETag; otherwise send it all.
    const head = await env.BOARD.head(key);
    if (!head) return notFound();
    if (ifRange.trim() !== head.httpEtag) range = null;
  }

  const options = {};
  const cond = conditionalHeaders(request.headers);
  if (cond) options.onlyIf = cond;
  if (range) options.range = range;

  let obj;
  try {
    obj = await env.BOARD.get(key, options);
  } catch (err) {
    if (range) {
      // R2 throws when the range starts past the end of the object.
      const head = await env.BOARD.head(key);
      if (head && range.offset !== undefined && range.offset >= head.size) {
        return await rangeNotSatisfiable(env, key, cacheControl);
      }
    }
    throw err;
  }
  if (!obj) return notFound();

  const base = tag({ etag: obj.httpEtag, "cache-control": cacheControl, "accept-ranges": "bytes" });

  // Precondition failed: R2 returns the object without a body.
  if (obj.body === undefined || obj.body === null) {
    const wantsValidation = request.headers.has("if-none-match") || request.headers.has("if-modified-since");
    return secureResponse(null, { status: wantsValidation ? 304 : 412, headers: base });
  }

  const headers = { ...base, "content-type": contentType };
  if (obj.uploaded instanceof Date) headers["last-modified"] = obj.uploaded.toUTCString();

  const r = range ? resolveRange(obj, obj.size) : null;
  if (r) {
    headers["content-range"] = `bytes ${r.offset}-${r.offset + r.length - 1}/${obj.size}`;
    return secureResponse(obj.body, { status: 206, headers });
  }
  return secureResponse(obj.body, { status: 200, headers });
}

export function notFound() {
  return textResponse(404, "Not found");
}
