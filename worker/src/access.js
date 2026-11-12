// worker/src/access.js
//
// Defence in depth behind Cloudflare Access. No dependencies, WebCrypto only.
//
// Cloudflare Access is the real gate: an unauthenticated visitor never reaches
// the Worker. This module exists so that if Access is ever misconfigured, or a
// hostname is added to the Worker without being covered by the Access
// application, the Worker still refuses every request that does not carry a
// valid Access token for THIS application.
//
// Sources (Cloudflare docs, read 2026-09-21):
//   - the token arrives in the `Cf-Access-Jwt-Assertion` request header
//   - signed RS256; public keys at https://<team>.cloudflareaccess.com/cdn-cgi/access/certs
//     (JSON with a `keys` array of JWKs: kid, kty, alg, use, e, n)
//   - claims: aud (array of application AUD tags), iss = https://<team>.cloudflareaccess.com,
//     email (people) or common_name (service tokens), exp, nbf, iat
//   - keys rotate every 6 weeks; the previous key stays valid 7 days, so two are live
//   https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
//
// CPU budget (Workers Free = 10 ms per request): one RSA verify is well under a
// millisecond, and a verified token is remembered for up to 5 minutes, so the
// steady state is a Map lookup. Waiting on the certs fetch is I/O, not CPU.

const JWKS_TTL_MS = 60 * 60 * 1000; // "cache the keys in the Worker for an hour"
const JWKS_STALE_OK_MS = 24 * 60 * 60 * 1000; // keep using old keys if the certs URL is down
const JWKS_FORCE_REFRESH_MIN_MS = 60 * 1000; // unknown kid: refetch, at most once a minute
const TOKEN_CACHE_MAX_MS = 5 * 60 * 1000;
const TOKEN_CACHE_MAX_ENTRIES = 256;
const CLOCK_SKEW_S = 30;
const MAX_TOKEN_CHARS = 8192;

const TEAM_HOST_RE = /^[a-z0-9][a-z0-9-]{0,62}\.cloudflareaccess\.com$/;
const PLACEHOLDER_RE = /replace/i;

const encoder = new TextEncoder();

// Module state lives per isolate. resetAccessState() is for tests only.
const state = {
  teamOrigin: "",
  keys: null, // Map kid -> JWK
  fetchedAt: 0,
  lastForcedAt: 0,
  inflight: null,
  cryptoKeys: new Map(), // kid -> CryptoKey
  tokens: new Map(), // `${cfgKey}|${token}` -> expiry ms
};

export function resetAccessState() {
  state.teamOrigin = "";
  state.keys = null;
  state.fetchedAt = 0;
  state.lastForcedAt = 0;
  state.inflight = null;
  state.cryptoKeys = new Map();
  state.tokens = new Map();
}

// ---------------------------------------------------------------------------
// Configuration

function isUnset(value) {
  return value === undefined || value === null || String(value).trim() === "" || PLACEHOLDER_RE.test(String(value));
}

/**
 * Read the wrangler vars.
 *   ACCESS_TEAM_DOMAIN  "myteam", "myteam.cloudflareaccess.com" or with https://
 *   ACCESS_AUD          the application AUD tag; comma separated for more than one
 *   ACCESS_ENFORCE      "false" disables the check, and only on localhost (dev)
 *   ACCESS_ACCEPT_CTX   "false" ignores ctx.access and requires the JWT header
 * Returns { enforce, acceptCtx, ok, problem, teamOrigin, auds }.
 */
export function readAccessConfig(env) {
  const enforce = String(env.ACCESS_ENFORCE ?? "true").trim().toLowerCase() !== "false";
  const acceptCtx = String(env.ACCESS_ACCEPT_CTX ?? "true").trim().toLowerCase() !== "false";
  const cfg = { enforce, acceptCtx, ok: false, problem: "", teamOrigin: "", auds: [] };
  if (!enforce) {
    cfg.ok = true;
    return cfg;
  }

  if (isUnset(env.ACCESS_TEAM_DOMAIN)) {
    cfg.problem = "ACCESS_TEAM_DOMAIN is not set";
    return cfg;
  }
  let host = String(env.ACCESS_TEAM_DOMAIN).trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  if (!host.includes(".")) host += ".cloudflareaccess.com";
  if (!TEAM_HOST_RE.test(host)) {
    cfg.problem = "ACCESS_TEAM_DOMAIN must be <team>.cloudflareaccess.com";
    return cfg;
  }
  cfg.teamOrigin = `https://${host}`;

  if (isUnset(env.ACCESS_AUD)) {
    cfg.problem = "ACCESS_AUD is not set";
    return cfg;
  }
  cfg.auds = String(env.ACCESS_AUD)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (cfg.auds.length === 0) {
    cfg.problem = "ACCESS_AUD is empty";
    return cfg;
  }
  cfg.ok = true;
  return cfg;
}

/** wrangler dev binds to localhost; the ACCESS_ENFORCE=false bypass is only honoured there. */
export function isLocalHost(hostname) {
  const h = String(hostname || "").toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "[::1]" || h === "::1";
}

// ---------------------------------------------------------------------------
// base64url

function b64urlToBytes(s) {
  if (!/^[A-Za-z0-9_-]*$/.test(s)) throw new Error("bad base64url");
  let b = s.replace(/-/g, "+").replace(/_/g, "/");
  while (b.length % 4) b += "=";
  const bin = atob(b);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function decodeJsonPart(s) {
  return JSON.parse(new TextDecoder().decode(b64urlToBytes(s)));
}

// ---------------------------------------------------------------------------
// Public keys

async function refreshKeys(teamOrigin, now) {
  if (state.inflight) return state.inflight;
  state.inflight = (async () => {
    try {
      const res = await globalThis.fetch(`${teamOrigin}/cdn-cgi/access/certs`, {
        headers: { accept: "application/json" },
      });
      if (!res.ok) throw new Error(`certs http ${res.status}`);
      const body = await res.json();
      const map = new Map();
      for (const jwk of Array.isArray(body && body.keys) ? body.keys : []) {
        if (jwk && jwk.kty === "RSA" && typeof jwk.kid === "string" && jwk.n && jwk.e) map.set(jwk.kid, jwk);
      }
      if (map.size === 0) throw new Error("certs had no RSA keys");
      state.keys = map;
      state.fetchedAt = now;
      state.cryptoKeys = new Map(); // rotated keys must be re-imported
      return true;
    } finally {
      state.inflight = null;
    }
  })();
  return state.inflight;
}

/** Returns a CryptoKey for `kid`, refreshing the cached key set when needed, or null. */
async function keyFor(kid, teamOrigin, now) {
  if (state.teamOrigin !== teamOrigin) {
    resetAccessState();
    state.teamOrigin = teamOrigin;
  }
  const stale = !state.keys || now - state.fetchedAt >= JWKS_TTL_MS;
  if (stale) {
    try {
      await refreshKeys(teamOrigin, now);
    } catch (e) {
      // Certs endpoint unreachable: keep using what we have, for up to a day.
      if (!state.keys || now - state.fetchedAt >= JWKS_STALE_OK_MS) throw e;
    }
  }
  if (!state.keys.has(kid) && now - state.lastForcedAt >= JWKS_FORCE_REFRESH_MIN_MS && now - state.fetchedAt >= JWKS_FORCE_REFRESH_MIN_MS) {
    state.lastForcedAt = now;
    try {
      await refreshKeys(teamOrigin, now);
    } catch (e) {
      /* keep the old set */
    }
  }
  const jwk = state.keys && state.keys.get(kid);
  if (!jwk) return null;
  let key = state.cryptoKeys.get(kid);
  if (!key) {
    key = await crypto.subtle.importKey(
      "jwk",
      { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"]
    );
    state.cryptoKeys.set(kid, key);
  }
  return key;
}

// ---------------------------------------------------------------------------
// Verification

/**
 * Verify an Access JWT. Never throws.
 * Returns { ok: true, identity } or { ok: false, reason } where reason is one of
 * malformed, bad_alg, no_kid, jwks_unavailable, unknown_kid, bad_signature,
 * expired, not_yet_valid, bad_issuer, bad_audience, no_identity.
 */
export async function verifyAccessJwt(token, cfg, now = Date.now()) {
  try {
    if (typeof token !== "string" || token.length === 0 || token.length > MAX_TOKEN_CHARS) return fail("malformed");
    const cacheKey = `${cfg.teamOrigin}|${cfg.auds.join(",")}|${token}`;
    const cached = state.tokens.get(cacheKey);
    if (cached !== undefined) {
      if (cached.until > now) return { ok: true, identity: cached.identity, cached: true };
      state.tokens.delete(cacheKey);
    }

    const parts = token.split(".");
    if (parts.length !== 3) return fail("malformed");
    let header;
    let payload;
    try {
      header = decodeJsonPart(parts[0]);
      payload = decodeJsonPart(parts[1]);
    } catch (e) {
      return fail("malformed");
    }
    if (!header || typeof header !== "object" || !payload || typeof payload !== "object") return fail("malformed");
    if (header.alg !== "RS256") return fail("bad_alg"); // rejects "none" and HS256 downgrade
    if (typeof header.kid !== "string" || header.kid === "") return fail("no_kid");

    let key;
    try {
      key = await keyFor(header.kid, cfg.teamOrigin, now);
    } catch (e) {
      return fail("jwks_unavailable");
    }
    if (!key) return fail("unknown_kid");

    let sig;
    try {
      sig = b64urlToBytes(parts[2]);
    } catch (e) {
      return fail("malformed");
    }
    const signed = encoder.encode(`${parts[0]}.${parts[1]}`);
    const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, sig, signed);
    if (!valid) return fail("bad_signature");

    // Signature good; now the claims.
    const nowS = Math.floor(now / 1000);
    if (typeof payload.exp !== "number" || payload.exp + CLOCK_SKEW_S < nowS) return fail("expired");
    if (typeof payload.nbf === "number" && payload.nbf - CLOCK_SKEW_S > nowS) return fail("not_yet_valid");
    if (typeof payload.iss !== "string" || payload.iss.replace(/\/+$/, "") !== cfg.teamOrigin) return fail("bad_issuer");
    const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
    if (!auds.some((a) => typeof a === "string" && cfg.auds.includes(a))) return fail("bad_audience");
    const who =
      (typeof payload.email === "string" && payload.email) ||
      (typeof payload.common_name === "string" && payload.common_name) ||
      "";
    if (!who) return fail("no_identity");

    const identity = { who, kind: typeof payload.email === "string" && payload.email ? "user" : "service_token" };
    const until = Math.min(payload.exp * 1000, now + TOKEN_CACHE_MAX_MS);
    if (state.tokens.size >= TOKEN_CACHE_MAX_ENTRIES) {
      state.tokens.delete(state.tokens.keys().next().value); // drop the oldest
    }
    state.tokens.set(cacheKey, { until, identity });
    return { ok: true, identity };
  } catch (e) {
    return fail("malformed");
  }
}

function fail(reason) {
  return { ok: false, reason };
}

// ---------------------------------------------------------------------------
// Request gate

/**
 * Decide whether a request may proceed.
 *
 * Accepts, in order:
 *   1. a valid Cf-Access-Jwt-Assertion header for this team and AUD;
 *   2. ctx.access, which the Workers runtime sets only when Access itself
 *      authenticated the request (undocumented whether the JWT header is also
 *      forwarded when Access is attached directly to a Worker, so both paths
 *      are accepted; set ACCESS_ACCEPT_CTX=false to require the header);
 *   3. nothing, when ACCESS_ENFORCE=false AND the host is localhost.
 *
 * Fails closed: enforcing with no team domain or AUD configured returns 503, so
 * a first deploy made before Access exists serves nothing.
 *
 * Returns { ok: true, via } or { ok: false, status, reason }.
 */
export async function authorize(request, env, ctx, hostname, now = Date.now()) {
  const cfg = readAccessConfig(env);

  if (!cfg.enforce) {
    if (isLocalHost(hostname)) return { ok: true, via: "bypass-dev" };
    return { ok: false, status: 500, reason: "enforce_off_on_public_host" };
  }
  if (!cfg.ok) return { ok: false, status: 503, reason: "not_configured" };

  const token = request.headers.get("cf-access-jwt-assertion");
  let reason = "missing_jwt";
  if (token) {
    const r = await verifyAccessJwt(token, cfg, now);
    if (r.ok) return { ok: true, via: "jwt", identity: r.identity };
    reason = r.reason;
  }

  if (cfg.acceptCtx && ctx && ctx.access) {
    const a = ctx.access.aud;
    const audsFromCtx = Array.isArray(a) ? a : a === undefined || a === null ? [] : [a];
    // When the runtime tells us which application authenticated the request,
    // it must be ours. If it tells us nothing, the platform assertion alone stands.
    if (audsFromCtx.length === 0 || audsFromCtx.some((x) => cfg.auds.includes(String(x)))) {
      return { ok: true, via: "ctx" };
    }
    reason = "ctx_bad_audience";
  }
  return { ok: false, status: 403, reason };
}
