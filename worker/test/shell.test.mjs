import test, { before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  assertShellCovered, buildCspManifest, cspHash, extractHandlers, extractInlineScripts, planShell, shellFileList,
} from "../scripts/shell_lib.mjs";
import { FakeAssets, call, makeEnv, makeJwtKit, resetAll, stubJwks } from "./helpers.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const workerDir = path.resolve(here, "..");
const realDocs = path.resolve(workerDir, "..", "docs");

test("cspHash is base64 SHA-256 and normalises CRLF", () => {
  const expected = "sha256-" + createHash("sha256").update("alert(1)").digest("base64");
  assert.equal(cspHash("alert(1)"), expected);
  assert.equal(cspHash("a\r\nb\rc"), cspHash("a\nb\nc"));
  assert.match(cspHash("x"), /^sha256-[A-Za-z0-9+/]{43}=$/);
});

test("extractInlineScripts: inline only, comments skipped, src and JSON ignored", () => {
  const html = `<!doctype html><head>
    <!-- a comment that mentions <script>var fake=1</script> must not count -->
    <script src="a.js"></script>
    <script>var one = 1;</script>
    <script type="application/json">{"not":"code"}</script>
    <script type="text/javascript">var two = "<!-- not a comment -->";</script>
    <script type="module">import x from "./x.js";</script>
    <script async src="b.js">ignored body</script>
    <script>   </script>
    </head><body><scriptx>nope</scriptx>
    <script>
      var three = 3;
    </script></body>`;
  const found = extractInlineScripts(html);
  assert.deepEqual(found, [
    "var one = 1;",
    'var two = "<!-- not a comment -->";',
    'import x from "./x.js";',
    "\n      var three = 3;\n    ",
  ]);
});

test("extractInlineScripts: attribute values containing > do not end the tag early", () => {
  const found = extractInlineScripts('<script data-x="a>b">go()</script>');
  assert.deepEqual(found, ["go()"]);
});

test("extractHandlers: literal handlers are hashed, interpolated ones are flagged", () => {
  const js = "`<a onclick=\"event.stopPropagation()\">` + '<b onmouseover=\\'x()\\'>' + `<i onclick=\"go(${id})\">`";
  const { literal, dynamic } = extractHandlers(js);
  assert.ok(literal.includes("event.stopPropagation()"));
  assert.deepEqual(dynamic, ["go(${id})"]);
  assert.deepEqual(extractHandlers('<a onclick="a(&quot;x&quot;)" onclick="a(&quot;x&quot;)">').literal, ['a("x")']);
  assert.deepEqual(extractHandlers("<div class=\"one\" data-on=\"x\">").literal, [], "data-on and class are not handlers");
});

test("buildCspManifest warns about handlers it cannot hash", () => {
  const m = buildCspManifest({ indexHtml: "<script>1</script>", dashboardJs: '`<a onclick="f(${x})">`' });
  assert.equal(m.scripts.length, 1);
  assert.equal(m.handlers.length, 0);
  assert.equal(m.warnings.length, 1);
});

test("assertShellCovered fails when a shell file would not be served", () => {
  assert.doesNotThrow(() => assertShellCovered(shellFileList(["icon-192.png"])));
  assert.throws(() => assertShellCovered(["index.html", "crm.json"]), /crm\.json/);
  assert.throws(() => assertShellCovered(["listings.json"]), /uncompressed_listings/);
});

// ---- planShell on a throwaway docs tree --------------------------------------

function fakeDocs(overrides = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "shell-docs-"));
  const files = {
    "index.html": '<html><link rel="manifest" href="manifest.json"><link rel="apple-touch-icon" href="icons/a.png"><script>x=1</script><script src="dashboard.js"></script></html>',
    "dashboard.js": "const a = 1;",
    "style.css": "a{}",
    "premium.css": "a{}",
    "manifest.json": JSON.stringify({ icons: [{ src: "icons/a.png" }] }),
    "icons/a.png": "png",
    ...overrides,
  };
  for (const [name, body] of Object.entries(files)) {
    if (body === null) continue;
    fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    fs.writeFileSync(path.join(dir, name), body);
  }
  return dir;
}

test("planShell: builds a plan, and refuses missing files or unshipped icons", () => {
  const ok = planShell(fakeDocs());
  assert.deepEqual(ok.files, ["index.html", "dashboard.js", "style.css", "premium.css", "manifest.json", "icons/a.png"]);
  assert.equal(ok.csp.scripts.length, 1);
  assert.throws(() => planShell(fakeDocs({ "premium.css": null })), /premium\.css/);
  assert.throws(
    () => planShell(fakeDocs({ "manifest.json": JSON.stringify({ icons: [{ src: "icons/missing-512.png" }] }) })),
    /icons\/missing-512\.png/
  );
});

test("planShell: an oversize asset is refused (25 MiB Workers static asset cap)", () => {
  const dir = fakeDocs();
  fs.writeFileSync(path.join(dir, "dashboard.js"), Buffer.alloc(25 * 1024 * 1024 + 1));
  assert.throws(() => planShell(dir), /25 MiB/);
});

// ---- the real docs/, structural checks only -------------------------------------

const haveDocs = fs.existsSync(path.join(realDocs, "index.html"));

test("real docs: plan is valid and inline scripts are found by two independent parsers", { skip: !haveDocs }, () => {
  const plan = planShell(realDocs);
  assert.ok(plan.total < 2 * 1024 * 1024, "the shell is small; the board is not in it");
  for (const f of plan.files) assert.ok(fs.statSync(path.join(realDocs, f)).size < 25 * 1024 * 1024, f);
  const html = fs.readFileSync(path.join(realDocs, "index.html"), "utf8");
  // Independent parser: drop comments with a regex, then match script elements.
  const noComments = html.replace(/<!--[\s\S]*?-->/g, "");
  const viaRegex = [...noComments.matchAll(/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
    .map((m) => m[1])
    .filter((b) => b.trim() !== "")
    .map(cspHash);
  assert.deepEqual([...new Set(viaRegex)].sort(), [...plan.csp.scripts].sort());
  assert.ok(plan.csp.scripts.length >= 1);
});

// ---- the CLI, and the CSP it emits, end to end with the Worker -------------------

let kit;
let stub;
before(async () => {
  kit = await makeJwtKit("kid-1");
});
beforeEach(() => {
  resetAll();
  stub = stubJwks(kit);
});
afterEach(() => stub.restore());

test("build_shell.mjs writes a shell that the Worker serves with a CSP covering every inline script", { skip: !haveDocs }, async () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "shell-out-"));
  const run = spawnSync(process.execPath, [path.join(workerDir, "scripts", "build_shell.mjs"), "--out", out], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr + run.stdout);
  const cspFile = JSON.parse(fs.readFileSync(path.join(out, "csp-hashes.json"), "utf8"));
  assert.ok(cspFile.scripts.length >= 1);

  // Serve the built folder through the Worker via a directory-backed assets fake.
  const files = {};
  const walk = (d, rel = "") => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p, `${rel}/${e.name}`);
      else files[`${rel}/${e.name}`] = fs.readFileSync(p);
    }
  };
  walk(out);
  assert.ok(files["/index.html"] && files["/dashboard.js"] && files["/csp-hashes.json"]);
  assert.equal(files["/.env"], undefined);
  assert.ok(!Object.keys(files).some((f) => /listings|crm|outreach|\.csv|\.md$/i.test(f)), "no data files in the shell");

  const env = makeEnv({ ASSETS: new FakeAssets(files) });
  const res = await call(env, "/", { token: await kit.token() });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("x-csp-mode"), "hashed");
  const csp = res.headers.get("content-security-policy");
  for (const h of cspFile.scripts) assert.ok(csp.includes(`'${h}'`), `CSP is missing ${h}`);
  // The served HTML is the real index.html, byte for byte.
  const served = Buffer.from(await res.arrayBuffer());
  assert.ok(served.equals(fs.readFileSync(path.join(realDocs, "index.html"))));
  // And it does not serve the hash list itself.
  assert.equal((await call(env, "/csp-hashes.json", { token: await kit.token() })).status, 404);
});

test("build_shell.mjs refuses to write outside worker/ or the temp dir", () => {
  const run = spawnSync(process.execPath, [path.join(workerDir, "scripts", "build_shell.mjs"), "--out", path.join(os.homedir(), "Desktop", "should-not-exist")], { encoding: "utf8" });
  assert.equal(run.status, 1);
  assert.match(run.stderr, /refusing to write/);
  assert.equal(fs.existsSync(path.join(os.homedir(), "Desktop", "should-not-exist")), false);
});
