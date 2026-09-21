// worker/src/csp.js
//
// Loads csp-hashes.json from the Worker's own static assets (written by
// worker/scripts/build_shell.mjs in the same run that copies index.html, so the
// hashes always describe the index.html that shipped) and builds the CSP header
// for the HTML document. Cached per isolate.

import { buildHtmlCsp } from "./security.js";

const OK_TTL_MS = 60 * 60 * 1000;
const FAIL_TTL_MS = 60 * 1000;
const HASH_RE = /^sha256-[A-Za-z0-9+/]{43}=$/;

const state = { value: null, at: 0, ttl: 0 };

export function resetCspState() {
  state.value = null;
  state.at = 0;
  state.ttl = 0;
}

function validHashList(list) {
  return Array.isArray(list) && list.every((h) => typeof h === "string" && HASH_RE.test(h));
}

/**
 * @returns {Promise<{csp: string, mode: "hashed"|"relaxed"|"relaxed-no-hashes"}>}
 */
export async function getHtmlCsp(env, origin, now = Date.now()) {
  if (String(env.CSP_RELAXED || "").trim().toLowerCase() === "true") {
    return { csp: buildHtmlCsp(null, true), mode: "relaxed" };
  }
  if (state.value && now - state.at < state.ttl) return state.value;

  let value;
  try {
    const res = await env.ASSETS.fetch(new Request(new URL("/csp-hashes.json", origin)));
    if (res.status !== 200) throw new Error(`csp-hashes.json http ${res.status}`);
    const body = await res.json();
    if (!validHashList(body.scripts) || !validHashList(body.handlers || [])) throw new Error("csp-hashes.json malformed");
    value = { csp: buildHtmlCsp({ scripts: body.scripts, handlers: body.handlers || [] }, false), mode: "hashed" };
    state.ttl = OK_TTL_MS;
  } catch (e) {
    console.log(`csp hashes unavailable: ${e && e.message ? e.message : e}`);
    value = { csp: buildHtmlCsp(null, true), mode: "relaxed-no-hashes" };
    state.ttl = FAIL_TTL_MS;
  }
  state.value = value;
  state.at = now;
  return value;
}
