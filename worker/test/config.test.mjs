import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseJsonc, renderConfig } from "../scripts/config_lib.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const template = () => parseJsonc(fs.readFileSync(path.resolve(here, "..", "wrangler.jsonc"), "utf8"));

const ACCOUNT = "0123456789abcdef0123456789abcdef";
const AUD = "f".repeat(64);

test("parseJsonc: comments, trailing commas, and // inside strings", () => {
  const v = parseJsonc(`{
    // line comment
    "url": "https://example.com/a//b", /* block */
    "list": [1, 2,],
    "s": "a \\" // not a comment",
  }`);
  assert.deepEqual(v, { url: "https://example.com/a//b", list: [1, 2], s: 'a " // not a comment' });
});

test("template: the shipped wrangler.jsonc is what the Worker expects", () => {
  const t = template();
  assert.equal(t.workers_dev, false, "workers.dev is not exposed by default");
  assert.equal(t.preview_urls, false);
  assert.equal(t.assets.run_worker_first, true, "required so the Access check also covers static assets");
  assert.equal(t.assets.binding, "ASSETS");
  assert.equal(t.assets.directory, "./shell");
  assert.deepEqual(t.r2_buckets, [{ binding: "BOARD", bucket_name: "foreclosure-board" }]);
  assert.equal(t.main, "src/index.js");
  assert.equal(t.vars.ACCESS_ENFORCE, "true");
  assert.match(t.vars.ACCESS_AUD, /REPLACE/, "placeholders keep an undeployed template failing closed");
  assert.match(t.vars.ACCESS_TEAM_DOMAIN, /REPLACE/);
  assert.equal(t.routes, undefined, "the custom domain route is a commented placeholder");
  assert.match(t.compatibility_date, /^\d{4}-\d{2}-\d{2}$/);
  assert.ok(new Date(t.compatibility_date) <= new Date(), "a future compatibility_date is rejected by wrangler");
  assert.equal(t.observability.enabled, true);
  assert.ok(t.observability.head_sampling_rate <= 0.5);
});

test("renderConfig: workers-dev mode", () => {
  const c = renderConfig(template(), { account: ACCOUNT, team: "acme", aud: AUD, urlMode: "workers-dev" });
  assert.equal(c.account_id, ACCOUNT);
  assert.equal(c.workers_dev, true);
  assert.equal(c.preview_urls, false);
  assert.equal(c.routes, undefined);
  assert.equal(c.vars.ACCESS_TEAM_DOMAIN, "acme");
  assert.equal(c.vars.ACCESS_AUD, AUD);
  assert.equal(c.assets.run_worker_first, true);
});

test("renderConfig: custom-domain mode", () => {
  const c = renderConfig(template(), { urlMode: "custom-domain", hostname: "board.example.com" });
  assert.equal(c.workers_dev, false);
  assert.deepEqual(c.routes, [{ pattern: "board.example.com", custom_domain: true }]);
  assert.throws(() => renderConfig(template(), { urlMode: "custom-domain" }), /WORKER_HOSTNAME/);
});

test("renderConfig: no URL mode keeps the Worker off the internet", () => {
  const c = renderConfig(template(), { account: ACCOUNT });
  assert.equal(c.workers_dev, false);
  assert.equal(c.routes, undefined);
});

test("renderConfig: the template object is not mutated, and bad values are rejected", () => {
  const base = template();
  const before = JSON.stringify(base);
  renderConfig(base, { account: ACCOUNT, urlMode: "workers-dev" });
  assert.equal(JSON.stringify(base), before);
  for (const bad of [
    { account: "123" }, { account: ACCOUNT.toUpperCase() }, { aud: "short" }, { team: "evil.com" },
    { team: "a b" }, { bucket: "UPPER" }, { name: "-x" }, { urlMode: "custom-domain", hostname: "not a host" },
    { urlMode: "custom-domain", hostname: "https://x.com" }, { urlMode: "elsewhere" },
  ]) {
    assert.throws(() => renderConfig(template(), bad), undefined, JSON.stringify(bad));
  }
  assert.equal(renderConfig(template(), { team: "acme.cloudflareaccess.com" }).vars.ACCESS_TEAM_DOMAIN, "acme.cloudflareaccess.com");
  assert.equal(renderConfig(template(), { bucket: "my-bucket-2" }).r2_buckets[0].bucket_name, "my-bucket-2");
});

test("renderConfig: break-glass and debug switches are passed through and validated", () => {
  const c = renderConfig(template(), { cspRelaxed: "true", authDebug: "true" });
  assert.equal(c.vars.CSP_RELAXED, "true");
  assert.equal(c.vars.AUTH_DEBUG, "true");
  const d = renderConfig(template(), {});
  assert.equal(d.vars.CSP_RELAXED, "false");
  assert.equal(d.vars.AUTH_DEBUG, "false");
  assert.throws(() => renderConfig(template(), { cspRelaxed: "yes" }));
  assert.throws(() => renderConfig(template(), { authDebug: "1" }));
});
