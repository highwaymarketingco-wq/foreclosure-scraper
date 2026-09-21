// worker/src/security.js
//
// Response headers and the Content-Security-Policy.
//
// What index.html needs (read from docs/index.html and docs/dashboard.js on
// 2026-09-21; re-derive with `node worker/scripts/build_shell.mjs --check`):
//   scripts   own dashboard.js; Leaflet from https://unpkg.com; inline <script>
//             blocks (theme bootstrap, theme toggle); one inline onclick handler
//             that dashboard.js writes into card markup
//   styles    own style.css and premium.css; Leaflet CSS from unpkg;
//             Google Fonts CSS; MANY inline style="" attributes and <style> blocks
//   fonts     https://fonts.gstatic.com
//   images    own parcel photos; OSM tiles and staticmap.openstreetmap.de;
//             listing-photo hosts that vary by scraper; data: icons
//   fetch     same origin only (every fetch() in dashboard.js is a relative URL)
//
// Inline scripts are allowed by SHA-256 hash, not by 'unsafe-inline', so an
// injected <script> from scraped text would not run. The hashes are produced by
// worker/scripts/build_shell.mjs into the shell as csp-hashes.json, so they are
// deployed atomically with the exact index.html they describe.
//
// REFERRER POLICY. The task brief asked for `no-referrer`. That is applied to
// every response EXCEPT the HTML document. OpenStreetMap's tile servers answer
// 403 "Access blocked" to requests that carry no Referer (their Tile Usage
// Policy says "Do not send no-referrer"), and the dashboard draws OSM tiles, so
// the document that makes those requests must send at least its origin. The
// document uses strict-origin-when-cross-origin, the browser default: the
// third-party hosts see the site origin, never a path or query.
// https://operations.osmfoundation.org/policies/tiles/

export const SCRIPT_CDN = "https://unpkg.com";

/** Fixed headers on every response. */
const BASE_HEADERS = {
  "x-content-type-options": "nosniff",
  "x-robots-tag": "noindex, nofollow, noarchive",
  "x-frame-options": "DENY",
  "permissions-policy": "geolocation=(), camera=(), microphone=(), payment=(), usb=(), interest-cohort=()",
  // Cloudflare's edge already forces HTTPS; this tells browsers to remember it.
  // No includeSubDomains/preload: this Worker does not own the parent domain.
  "strict-transport-security": "max-age=31536000",
};

/** CSP for everything that is not the HTML document: nothing may load or embed. */
export const DATA_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";

/**
 * CSP for the HTML document.
 * @param {{scripts?: string[], handlers?: string[]}|null} hashes  from csp-hashes.json
 * @param {boolean} relaxed  add 'unsafe-inline' for scripts (break-glass, CSP_RELAXED=true)
 */
export function buildHtmlCsp(hashes, relaxed = false) {
  const script = ["'self'", SCRIPT_CDN];
  const usable = hashes && Array.isArray(hashes.scripts) && !relaxed;
  if (usable) {
    for (const h of hashes.scripts) script.push(`'${h}'`);
    if (Array.isArray(hashes.handlers) && hashes.handlers.length) {
      script.push("'unsafe-hashes'");
      for (const h of hashes.handlers) script.push(`'${h}'`);
    }
  } else {
    // No hash list (or break-glass): still works, weaker. The x-csp-mode response header says which.
    script.push("'unsafe-inline'");
  }
  return [
    "default-src 'none'",
    `script-src ${script.join(" ")}`,
    // style="" attributes cannot be hashed in practice, so styles keep 'unsafe-inline'.
    `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com ${SCRIPT_CDN}`,
    "img-src 'self' data: blob: https:",
    "font-src https://fonts.gstatic.com",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/**
 * Build a fresh Response (never mutate one from fetch or ASSETS: their headers are
 * immutable) with the security headers applied. The fixed headers, the referrer
 * policy and the CSP are always set here and cannot be overridden by `opts.headers`,
 * which carries only the per-response ones (content-type, cache-control, etag).
 *
 * @param {BodyInit|null} body
 * @param {{status?: number, headers?: Headers|Record<string,string>, html?: boolean, csp?: string}} opts
 */
export function secureResponse(body, opts = {}) {
  const headers = new Headers(opts.headers || {});
  for (const [k, v] of Object.entries(BASE_HEADERS)) headers.set(k, v);
  headers.set("referrer-policy", opts.html ? "strict-origin-when-cross-origin" : "no-referrer");
  headers.set("content-security-policy", opts.html ? opts.csp || buildHtmlCsp(null, true) : DATA_CSP);
  return new Response(body, { status: opts.status || 200, headers });
}

export function textResponse(status, text, extra = {}) {
  return secureResponse(text, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

export function jsonResponse(status, obj, extra = {}) {
  return secureResponse(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}
