import test, { before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { authorize, verifyAccessJwt, readAccessConfig, isLocalHost, resetAccessState } from "../src/access.js";
import { AUD, TEAM, TEAM_ORIGIN, makeJwtKit, stubJwks } from "./helpers.mjs";

let kit;
let stub;
const cfg = () => readAccessConfig({ ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD });
// Tokens that stay valid across the simulated hours in the cache tests.
const long = (over = {}) => ({ exp: Math.floor(Date.now() / 1000) + 5 * 3600, ...over });

before(async () => {
  kit = await makeJwtKit("kid-1");
});
beforeEach(() => {
  resetAccessState();
  stub = stubJwks(kit);
});
afterEach(() => stub.restore());

test("config: team domain forms, AUD list, placeholders, bad host", () => {
  for (const form of [TEAM, `${TEAM}.cloudflareaccess.com`, `https://${TEAM}.cloudflareaccess.com/`]) {
    assert.equal(readAccessConfig({ ACCESS_TEAM_DOMAIN: form, ACCESS_AUD: AUD }).teamOrigin, TEAM_ORIGIN, form);
  }
  assert.deepEqual(readAccessConfig({ ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: `${AUD}, ${"b".repeat(64)}` }).auds, [AUD, "b".repeat(64)]);
  assert.equal(readAccessConfig({ ACCESS_TEAM_DOMAIN: "REPLACE_WITH_TEAM.cloudflareaccess.com", ACCESS_AUD: AUD }).ok, false);
  assert.equal(readAccessConfig({ ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: "REPLACE_WITH_ACCESS_APPLICATION_AUD_TAG" }).ok, false);
  assert.equal(readAccessConfig({ ACCESS_TEAM_DOMAIN: TEAM }).ok, false);
  assert.equal(readAccessConfig({}).ok, false);
  // The certs URL is built from this value, so it must not be steerable elsewhere.
  for (const evil of ["evil.com", "evil.com/x", "a.cloudflareaccess.com.evil.com", "https://evil.com/.cloudflareaccess.com"]) {
    assert.equal(readAccessConfig({ ACCESS_TEAM_DOMAIN: evil, ACCESS_AUD: AUD }).ok, false, evil);
  }
  assert.equal(readAccessConfig({ ACCESS_ENFORCE: "false" }).ok, true);
  assert.equal(readAccessConfig({ ACCESS_ENFORCE: "FALSE" }).enforce, false);
});

test("accepts a correctly signed token and reads the identity", async () => {
  const r = await verifyAccessJwt(await kit.token(), cfg());
  assert.equal(r.ok, true);
  assert.equal(r.identity.who, "cash@example.com");
  assert.equal(r.identity.kind, "user");
  assert.equal(stub.urls[0], `${TEAM_ORIGIN}/cdn-cgi/access/certs`);
});

test("accepts a service token (common_name, no email)", async () => {
  const t = await kit.token({ email: undefined, common_name: "abc123.access", sub: "" });
  const r = await verifyAccessJwt(t, cfg());
  assert.equal(r.ok, true);
  assert.equal(r.identity.kind, "service_token");
});

test("accepts aud as a bare string and as one of several tags", async () => {
  assert.equal((await verifyAccessJwt(await kit.token({ aud: AUD }), cfg())).ok, true);
  assert.equal((await verifyAccessJwt(await kit.token({ aud: ["x".repeat(64), AUD] }), cfg())).ok, true);
});

test("rejects: wrong audience, issuer, expired, not yet valid, no identity", async () => {
  const cases = [
    [{ aud: ["c".repeat(64)] }, "bad_audience"],
    [{ aud: [] }, "bad_audience"],
    [{ aud: undefined }, "bad_audience"],
    [{ iss: "https://other.cloudflareaccess.com" }, "bad_issuer"],
    [{ iss: undefined }, "bad_issuer"],
    [{ exp: Math.floor(Date.now() / 1000) - 3600 }, "expired"],
    [{ exp: undefined }, "expired"],
    [{ nbf: Math.floor(Date.now() / 1000) + 3600 }, "not_yet_valid"],
    [{ email: undefined }, "no_identity"],
    [{ email: "" }, "no_identity"],
  ];
  for (const [over, reason] of cases) {
    const r = await verifyAccessJwt(await kit.token(over), cfg());
    assert.deepEqual([r.ok, r.reason], [false, reason], JSON.stringify(over));
  }
});

test("rejects a token signed by a different key even with the right kid", async () => {
  const attacker = await makeJwtKit("kid-1"); // same kid, different key pair
  const r = await verifyAccessJwt(await attacker.token(), cfg());
  assert.deepEqual([r.ok, r.reason], [false, "bad_signature"]);
});

test("rejects a tampered payload", async () => {
  const good = await kit.token({ email: "cash@example.com" });
  const [h, , s] = good.split(".");
  const forged = Buffer.from(JSON.stringify(kit.claims({ email: "attacker@example.com" }))).toString("base64url");
  const r = await verifyAccessJwt(`${h}.${forged}.${s}`, cfg());
  assert.deepEqual([r.ok, r.reason], [false, "bad_signature"]);
});

test("rejects alg none, HS256 and other downgrades", async () => {
  const h = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const p = h(kit.claims());
  for (const alg of ["none", "HS256", "RS512", "ES256"]) {
    const r = await verifyAccessJwt(`${h({ alg, kid: "kid-1" })}.${p}.`, cfg());
    assert.deepEqual([r.ok, r.reason], [false, "bad_alg"], alg);
  }
  // alg=none with an empty signature and no kid
  assert.equal((await verifyAccessJwt(`${h({ alg: "none" })}.${p}.`, cfg())).ok, false);
});

test("rejects malformed tokens without throwing", async () => {
  for (const bad of ["", "abc", "a.b", "a.b.c.d", "....", "!!!.???.***", `${"x".repeat(9000)}`, null, undefined, 42]) {
    const r = await verifyAccessJwt(bad, cfg());
    assert.equal(r.ok, false, String(bad).slice(0, 20));
  }
  const noKid = await kit.token({}, { header: { kid: undefined } });
  assert.equal((await verifyAccessJwt(noKid, cfg())).reason, "no_kid");
});

test("unknown kid: refetches keys once, then refuses; refetches are rate limited", async () => {
  const stray = await kit.token({}, { kid: "kid-unknown" });
  assert.equal((await verifyAccessJwt(stray, cfg())).ok, false);
  const afterFirst = stub.calls;
  assert.equal(afterFirst, 1, "the first request fetches the key set; a kid missing from a fresh set does not refetch");
  // Within a minute another unknown kid must NOT trigger another fetch: an attacker
  // sending random kids could otherwise hammer the certs endpoint through us.
  for (let i = 0; i < 5; i++) await verifyAccessJwt(await kit.token({}, { kid: `kid-x-${i}` }), cfg());
  assert.equal(stub.calls, afterFirst);
});

test("key rotation: a new kid appearing after the minute window is picked up", async () => {
  const t0 = Date.now();
  assert.equal((await verifyAccessJwt(await kit.token(), cfg(), t0)).ok, true);
  const next = await makeJwtKit("kid-2");
  stub.restore();
  stub = stubJwks([kit, next]); // Cloudflare now publishes both keys
  const tok = await next.token();
  const r = await verifyAccessJwt(tok, cfg(), t0 + 2 * 60 * 1000);
  assert.equal(r.ok, true, "kid-2 verifies after a forced refresh");
});

test("keys are cached for an hour, then refetched", async () => {
  const t0 = Date.now();
  await verifyAccessJwt(await kit.token(), cfg(), t0);
  await verifyAccessJwt(await kit.token(long({ sub: "2" })), cfg(), t0 + 1000);
  await verifyAccessJwt(await kit.token(long({ sub: "3" })), cfg(), t0 + 59 * 60 * 1000);
  assert.equal(stub.calls, 1, "three tokens inside the hour share one certs fetch");
  await verifyAccessJwt(await kit.token(long({ sub: "4" })), cfg(), t0 + 61 * 60 * 1000);
  assert.equal(stub.calls, 2, "after an hour the certs are fetched again");
});

test("certs endpoint down: cached keys keep working, no keys means refuse", async () => {
  const t0 = Date.now();
  assert.equal((await verifyAccessJwt(await kit.token(), cfg(), t0)).ok, true);
  stub.fail = true;
  const later = t0 + 2 * 60 * 60 * 1000;
  const ok = await verifyAccessJwt(await kit.token(long({ sub: "z" })), cfg(), later);
  assert.equal(ok.ok, true, "stale keys are used for up to a day when the fetch fails");
  resetAccessState();
  const none = await verifyAccessJwt(await kit.token(long()), cfg(), later);
  assert.deepEqual([none.ok, none.reason], [false, "jwks_unavailable"]);
});

test("a verified token is remembered (no second signature check needed)", async () => {
  const tok = await kit.token();
  const a = await verifyAccessJwt(tok, cfg());
  const b = await verifyAccessJwt(tok, cfg());
  assert.equal(a.ok && b.ok, true);
  assert.equal(b.cached, true);
  // Remembered only until it expires.
  const later = Date.now() + 2 * 60 * 60 * 1000;
  const c = await verifyAccessJwt(tok, cfg(), later);
  assert.equal(c.ok, false);
});

test("timing: cold verify and cached verify (informational)", async () => {
  const tok = await kit.token();
  const t0 = performance.now();
  await verifyAccessJwt(tok, cfg());
  const cold = performance.now() - t0;
  const t1 = performance.now();
  for (let i = 0; i < 200; i++) await verifyAccessJwt(tok, cfg());
  const warm = (performance.now() - t1) / 200;
  console.log(`# node timing, not workerd: cold verify ${cold.toFixed(2)} ms (includes key import), cached ${warm.toFixed(4)} ms`);
  assert.ok(cold < 100 && warm < 5, "pathologically slow");
});

// ---- authorize(): the request gate ----------------------------------------

const req = (headers = {}) => new Request("https://board.example.com/", { headers });
const env = (o = {}) => ({ ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, ...o });

test("authorize: missing header is refused", async () => {
  const r = await authorize(req(), env(), {}, "board.example.com");
  assert.deepEqual([r.ok, r.status, r.reason], [false, 403, "missing_jwt"]);
});

test("authorize: valid token passes, invalid token is refused with its reason", async () => {
  const good = await authorize(req({ "cf-access-jwt-assertion": await kit.token() }), env(), {}, "board.example.com");
  assert.deepEqual([good.ok, good.via], [true, "jwt"]);
  const bad = await authorize(req({ "cf-access-jwt-assertion": await kit.token({ aud: ["z".repeat(64)] }) }), env(), {}, "board.example.com");
  assert.deepEqual([bad.ok, bad.status, bad.reason], [false, 403, "bad_audience"]);
});

test("authorize: unconfigured Access fails closed with 503, even with a token", async () => {
  const r = await authorize(req({ "cf-access-jwt-assertion": await kit.token() }), { ACCESS_TEAM_DOMAIN: "REPLACE_ME", ACCESS_AUD: "REPLACE_ME" }, {}, "board.example.com");
  assert.deepEqual([r.ok, r.status, r.reason], [false, 503, "not_configured"]);
  const r2 = await authorize(req(), {}, {}, "board.example.com");
  assert.equal(r2.status, 503);
});

test("authorize: ctx.access (platform-authenticated) is accepted, and only for our AUD", async () => {
  const viaCtx = await authorize(req(), env(), { access: { aud: AUD } }, "board.example.com");
  assert.deepEqual([viaCtx.ok, viaCtx.via], [true, "ctx"]);
  const noAud = await authorize(req(), env(), { access: {} }, "board.example.com");
  assert.equal(noAud.ok, true, "runtime says Access authenticated it and names no application");
  const wrong = await authorize(req(), env(), { access: { aud: "d".repeat(64) } }, "board.example.com");
  assert.deepEqual([wrong.ok, wrong.reason], [false, "ctx_bad_audience"]);
  const off = await authorize(req(), env({ ACCESS_ACCEPT_CTX: "false" }), { access: { aud: AUD } }, "board.example.com");
  assert.equal(off.ok, false, "ACCESS_ACCEPT_CTX=false requires the header");
});

test("authorize: ACCESS_ENFORCE=false is honoured on localhost only", async () => {
  for (const h of ["localhost", "127.0.0.1", "[::1]"]) {
    assert.deepEqual((await authorize(req(), env({ ACCESS_ENFORCE: "false" }), {}, h)).via, "bypass-dev", h);
  }
  const pub = await authorize(req(), env({ ACCESS_ENFORCE: "false" }), {}, "board.example.com");
  assert.deepEqual([pub.ok, pub.status, pub.reason], [false, 500, "enforce_off_on_public_host"]);
  assert.equal(isLocalHost("localhost.evil.com"), false);
  assert.equal(isLocalHost("127.0.0.1.evil.com"), false);
});
