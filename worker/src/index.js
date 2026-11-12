// worker/src/index.js
//
// Private foreclosure dashboard Worker. Plain ES module, no build step.
//
//   Cloudflare Access (login) -> this Worker -> app shell from static assets
//                                            `-> big data from the private R2 bucket
//
// Read worker/README.md for the owner steps and docs/HOSTING_WORKER_2026-09-21.md
// for how it works. Design constraints:
//   - Workers Free: 10 ms CPU and 100,000 requests a day. No parsing or
//     compressing of big bodies; R2 streams pass straight through.
//   - Default deny: only names matched by src/routes.js are ever served.
//   - Every request, static assets included, must carry an Access token for this
//     application (src/access.js). That is why wrangler.jsonc sets
//     assets.run_worker_first = true: without it the platform would serve shell
//     files without running any Worker code, and so without this check.

import { authorize } from "./access.js";
import { classify, releaseIdFromRunTime } from "./routes.js";
import { getPointer, serveObject, notFound } from "./bucket.js";
import { getHtmlCsp } from "./csp.js";
import { secureResponse, textResponse, jsonResponse } from "./security.js";

const JSON_UTF8 = "application/json; charset=utf-8";
const IMMUTABLE = "private, max-age=31536000, immutable";
const REVALIDATE = "private, no-cache";

export default {
  async fetch(request, env, ctx) {
    try {
      return await handle(request, env, ctx);
    } catch (err) {
      console.log(`unhandled error: ${err && err.message ? err.message : err}`);
      return textResponse(500, "Server error");
    }
  },
};

async function handle(request, env, ctx) {
  const url = new URL(request.url);

  // 1. Gate. Everything below runs only for an authenticated request.
  const auth = await authorize(request, env, ctx, url.hostname);
  if (!auth.ok) {
    console.log(`deny ${auth.reason}`); // reason code only: no path, no identity
    const extra = String(env.AUTH_DEBUG || "").toLowerCase() === "true" ? { "x-auth-deny": auth.reason } : {};
    return textResponse(auth.status, auth.status === 503 ? "Service not configured" : "Forbidden", extra);
  }

  // 2. Read-only.
  if (request.method !== "GET" && request.method !== "HEAD") {
    return textResponse(405, "Method not allowed", { allow: "GET, HEAD" });
  }

  // 3. Allowlist.
  const route = classify(url.pathname);
  switch (route.kind) {
    case "denied":
      return notFound();
    case "robots":
      return textResponse(200, "User-agent: *\nDisallow: /\n", { "cache-control": "private, max-age=86400" });
    case "healthz":
      return healthz(env, auth);
    case "pointer":
      return serveObject(request, env, "current.json", { contentType: JSON_UTF8, cacheControl: "no-store" });
    case "photo":
      return serveObject(request, env, route.key, {
        contentType: route.contentType,
        cacheControl: "private, max-age=86400",
      });
    case "release":
      return serveRelease(request, env, route, url);
    case "shell":
      return serveShell(request, env, route, url);
    default:
      return notFound();
  }
}

async function healthz(env, auth) {
  const p = await getPointer(env);
  if (!p) return jsonResponse(503, { ok: false, release: null, error: "no release published" });
  return jsonResponse(200, {
    ok: true,
    release: p.release,
    published_at: p.publishedAt,
    board_count: p.boardCount,
    auth: auth.via,
  });
}

/**
 * Board payload files. Which release?
 *   - run_meta.json always comes from the CURRENT release (no-store), so a page
 *     load always learns the newest run_time.
 *   - every other file carries ?t=<run_time> from that run_meta, and is read from
 *     the release that run_time names, so a page never mixes two boards.
 *   - with no usable ?t=, the current release, revalidated on every use.
 */
async function serveRelease(request, env, route, url) {
  let releaseId = null;
  let versioned = false;
  if (!route.volatile) {
    releaseId = releaseIdFromRunTime(url.searchParams.get("t"));
    versioned = releaseId !== null;
  }
  if (!releaseId) {
    const p = await getPointer(env);
    if (!p) return textResponse(503, "No release published yet");
    releaseId = p.release;
  }
  const cacheControl = route.volatile ? "no-store" : versioned ? IMMUTABLE : REVALIDATE;
  return serveObject(request, env, `releases/${releaseId}${route.name}`, {
    contentType: route.contentType,
    cacheControl,
    release: releaseId,
  });
}

/** App shell from the Worker's static assets. */
async function serveShell(request, env, route, url) {
  // Forward only validators. Range is not forwarded: shell files are small.
  const fwd = new Headers();
  for (const name of ["if-none-match", "if-modified-since"]) {
    const v = request.headers.get(name);
    if (v) fwd.set(name, v);
  }
  const upstream = await env.ASSETS.fetch(
    new Request(new URL(route.assetPath, url.origin), { method: request.method, headers: fwd })
  );
  if (upstream.status !== 200 && upstream.status !== 304) return notFound();

  const versionedQuery = /\.(?:js|css)$/.test(route.assetPath) && (url.searchParams.get("v") || "") !== "";
  let cacheControl = REVALIDATE;
  if (route.assetPath.startsWith("/icons/")) cacheControl = "private, max-age=86400";
  else if (versionedQuery) cacheControl = "private, max-age=3600";

  const headers = { "cache-control": cacheControl };
  const etag = upstream.headers.get("etag");
  if (etag) headers.etag = etag;
  if (upstream.status === 304) return secureResponse(null, { status: 304, headers });

  headers["content-type"] = route.contentType;
  if (route.html) {
    const { csp, mode } = await getHtmlCsp(env, url.origin);
    headers["x-csp-mode"] = mode;
    return secureResponse(upstream.body, { status: 200, headers, html: true, csp });
  }
  return secureResponse(upstream.body, { status: 200, headers });
}
