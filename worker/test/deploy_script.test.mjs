// Drives scripts/deploy_worker.sh with a FAKE wrangler (a shell stub that logs its
// arguments) against a temp copy of the repo skeleton, and drives --smoke-test
// against a local simulation of Cloudflare Access in front of the real Worker.
// No Cloudflare account, wrangler install, or network is involved.

import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import worker from "../src/index.js";
import { AUD, TEAM, makeEnv, makeJwtKit, resetAll, stubJwks } from "./helpers.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const script = path.join(repo, "scripts", "deploy_worker.sh");
const ACCOUNT = "0123456789abcdef0123456789abcdef";
const TOKEN_SECRET = "SUPERSECRETtokenVALUE123";

function run(args, { env = {}, cwd = repo } = {}) {
  return new Promise((resolve) => {
    execFile("sh", [script, ...args], { env: { PATH: process.env.PATH, HOME: os.homedir(), ...env }, cwd, timeout: 120000 }, (err, stdout, stderr) => {
      resolve({ code: err ? (typeof err.code === "number" ? err.code : 1) : 0, stdout, stderr, all: stdout + stderr });
    });
  });
}

/** A repo skeleton in a temp dir: worker/ sources, a fixture docs/, a fake wrangler. */
function skeleton() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "deploy-root-"));
  fs.cpSync(path.join(repo, "worker"), path.join(root, "worker"), {
    recursive: true,
    filter: (src) => !/[\\/](shell|node_modules|\.wrangler)$/.test(src) && !/wrangler\.rendered\.jsonc$/.test(src) && !/deploy\.conf$/.test(src),
  });
  const docs = path.join(root, "docs");
  fs.mkdirSync(path.join(docs, "icons"), { recursive: true });
  const w = (n, b) => fs.writeFileSync(path.join(docs, n), b);
  w("index.html", '<html><link rel="manifest" href="manifest.json"><script>x=1</script><script src="dashboard.js"></script></html>');
  w("dashboard.js", "1");
  w("style.css", "a{}");
  w("premium.css", "a{}");
  w("manifest.json", JSON.stringify({ icons: [{ src: "icons/a.png" }] }));
  w("icons/a.png", "png");
  const bin = path.join(root, "fake_wrangler.sh");
  const log = path.join(root, "wrangler.log");
  fs.writeFileSync(
    bin,
    `#!/bin/sh
echo "$PWD :: $*" >> "${log}"
case "$1" in
  whoami) if [ "\${FAKE_LOGGED_IN:-1}" = 1 ]; then echo "{\\"accounts\\":[{\\"id\\":\\"\${FAKE_ACCOUNT:-${ACCOUNT}}\\"}]}"; else echo "not logged in" >&2; exit 1; fi ;;
  deploy) echo "Deployed foreclosure-board (fake)";;
esac
`,
    { mode: 0o755 }
  );
  return { root, bin, log, calls: () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split("\n").filter(Boolean) : []) };
}

const okEnv = { CF_ACCOUNT_ID: ACCOUNT, URL_MODE: "workers-dev" };

// ---- deploy: dry run, refusals, apply --------------------------------------------

test("dry run: prints the plan, runs the tests, touches nothing", async () => {
  const s = skeleton();
  const r = await run(["--root", s.root, "--skip-tests"], { env: { ...okEnv, WRANGLER: s.bin } });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /DRY RUN/);
  assert.match(r.all, /shell check/);
  assert.match(r.all, /"run_worker_first": true/);
  assert.match(r.all, /"workers_dev": true/);
  assert.match(r.all, /Dry run complete\. Nothing was deployed/);
  assert.match(r.all, /answers 503 to\s+every request/);
  assert.deepEqual(s.calls(), [], "wrangler was never called");
  assert.equal(fs.existsSync(path.join(s.root, "worker", "shell")), false, "no shell folder written");
  assert.equal(fs.existsSync(path.join(s.root, "worker", "wrangler.rendered.jsonc")), false);
});

test("dry run with the real repo: the worker's own tests are run and reported", async () => {
  // Real repo, real tests. This re-enters `node --test` once; that is fine, the
  // script's test run does not include this file's spawn of itself because
  // deploy_script.test.mjs only runs scripts with --skip-tests or against a skeleton.
  const r = await run(["--skip-tests"], { env: okEnv });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /tests\s+: skipped/);
  assert.match(r.all, /inline scripts\s+: \d+ hashed/);
});

test("bad settings are rejected before anything else", async () => {
  const s = skeleton();
  const bads = [
    { CF_ACCOUNT_ID: "nope" }, { URL_MODE: "elsewhere" }, { URL_MODE: "custom-domain" },
    { ACCESS_AUD: "short" }, { ACCESS_TEAM_DOMAIN: "evil.com" }, { WORKER_HOSTNAME: "x.example.com", URL_MODE: "workers-dev" },
  ];
  for (const b of bads) {
    const r = await run(["--root", s.root, "--skip-tests"], { env: { ...okEnv, ...b, WRANGLER: s.bin } });
    assert.equal(r.code, 1, JSON.stringify(b) + r.all);
    assert.match(r.all, /BAD SETTING/);
  }
  assert.deepEqual(s.calls(), []);
});

test("--apply refuses without an account, without a URL mode, and without wrangler", async () => {
  const s = skeleton();
  let r = await run(["--root", s.root, "--skip-tests", "--apply"], { env: { URL_MODE: "workers-dev", WRANGLER: s.bin } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /no account configured/);
  r = await run(["--root", s.root, "--skip-tests", "--apply"], { env: { CF_ACCOUNT_ID: ACCOUNT, WRANGLER: s.bin } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /no URL mode/);
  r = await run(["--root", s.root, "--skip-tests", "--apply"], { env: { ...okEnv, WRANGLER: "/nonexistent/wrangler" } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /not on PATH/);
  assert.deepEqual(s.calls(), []);
  assert.equal(fs.existsSync(path.join(s.root, "worker", "shell")), false, "refusals happen before the shell is built");
});

test("--apply refuses when wrangler is not logged in, or logged in to another account", async () => {
  const s = skeleton();
  let r = await run(["--root", s.root, "--skip-tests", "--apply"], { env: { ...okEnv, WRANGLER: s.bin, FAKE_LOGGED_IN: "0" } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /not logged in/);
  r = await run(["--root", s.root, "--skip-tests", "--apply"], { env: { ...okEnv, WRANGLER: s.bin, FAKE_ACCOUNT: "f".repeat(32) } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /not to an account with id/);
  assert.ok(!s.calls().some((c) => c.includes(" deploy")), "deploy never ran");
  r = await run(["--root", s.root, "--skip-tests", "--apply", "--skip-account-check"], { env: { ...okEnv, WRANGLER: s.bin, FAKE_ACCOUNT: "f".repeat(32) } });
  assert.equal(r.code, 0, r.all);
});

test("--apply happy path: build, render, whoami, then deploy from worker/ with the rendered config", async () => {
  const s = skeleton();
  const r = await run(["--root", s.root, "--skip-tests", "--apply"], {
    env: { ...okEnv, WRANGLER: s.bin, CLOUDFLARE_API_TOKEN: TOKEN_SECRET },
  });
  assert.equal(r.code, 0, r.all);
  const calls = s.calls();
  assert.equal(calls.length, 2, calls.join("\n"));
  assert.match(calls[0], /whoami --json$/);
  assert.match(calls[1], /worker :: deploy --config wrangler\.rendered\.jsonc$/, "deploys from inside worker/");
  const rendered = JSON.parse(fs.readFileSync(path.join(s.root, "worker", "wrangler.rendered.jsonc"), "utf8"));
  assert.equal(rendered.account_id, ACCOUNT);
  assert.equal(rendered.workers_dev, true);
  assert.equal(rendered.assets.run_worker_first, true);
  const shell = path.join(s.root, "worker", "shell");
  assert.ok(fs.existsSync(path.join(shell, "index.html")) && fs.existsSync(path.join(shell, "csp-hashes.json")));
  assert.match(r.all, /answering 503 to everything until you finish checklist Part 7/);
  assert.ok(!r.all.includes(TOKEN_SECRET), "the API token is never echoed");
});

test("--apply with Access values set deploys them, and points at the smoke test", async () => {
  const s = skeleton();
  const r = await run(["--root", s.root, "--skip-tests", "--apply"], {
    env: { CF_ACCOUNT_ID: ACCOUNT, URL_MODE: "custom-domain", WORKER_HOSTNAME: "board.example.com", ACCESS_TEAM_DOMAIN: "acme", ACCESS_AUD: "9".repeat(64), WRANGLER: s.bin },
  });
  assert.equal(r.code, 0, r.all);
  const rendered = JSON.parse(fs.readFileSync(path.join(s.root, "worker", "wrangler.rendered.jsonc"), "utf8"));
  assert.deepEqual(rendered.routes, [{ pattern: "board.example.com", custom_domain: true }]);
  assert.equal(rendered.workers_dev, false);
  assert.equal(rendered.vars.ACCESS_AUD, "9".repeat(64));
  assert.match(r.all, /--smoke-test/);
});

test("settings come from deploy.conf, environment wins, unknown keys are refused", async () => {
  const s = skeleton();
  const conf = path.join(s.root, "deploy.conf");
  fs.writeFileSync(conf, `# comment\n  CF_ACCOUNT_ID = "${ACCOUNT}"  \nURL_MODE=workers-dev\nACCESS_TEAM_DOMAIN=fromfile\n`);
  let r = await run(["--root", s.root, "--skip-tests", "--conf", conf], { env: { WRANGLER: s.bin, ACCESS_TEAM_DOMAIN: "fromenv" } });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, new RegExp(`account\\s+: ${ACCOUNT}`));
  assert.match(r.all, /"ACCESS_TEAM_DOMAIN": "fromenv"/);
  fs.writeFileSync(conf, "CLOUDFLARE_API_TOKEN=abc\n");
  r = await run(["--root", s.root, "--skip-tests", "--conf", conf], { env: { WRANGLER: s.bin } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /unknown setting/);
});

test("CSP_RELAXED and AUTH_DEBUG are visible in the plan, reach the rendered config, and are validated", async () => {
  const s = skeleton();
  let r = await run(["--root", s.root, "--skip-tests"], { env: { ...okEnv, WRANGLER: s.bin, CSP_RELAXED: "true", AUTH_DEBUG: "true" } });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /CSP\s+: RELAXED/);
  assert.match(r.all, /auth debug\s+: ON/);
  assert.match(r.all, /"CSP_RELAXED": "true"/);
  r = await run(["--root", s.root, "--skip-tests"], { env: { ...okEnv, WRANGLER: s.bin, CSP_RELAXED: "maybe" } });
  assert.equal(r.code, 1);
  assert.match(r.all, /CSP_RELAXED is not valid/);
});

test("the script never opens .env or .secrets", () => {
  const src = fs.readFileSync(script, "utf8");
  const code = src.split("\n").filter((l) => !l.trim().startsWith("#")).join("\n");
  // The smoke test asks the Worker for the URL path /.env and expects 404; that is a
  // request, not a file read. What must not appear is any path to a real secrets file.
  assert.ok(!/\.secrets/.test(code), "no reference to .secrets outside comments");
  assert.ok(!/(?:\$ROOT|\$WORKER|\$HOME|~|\.\.)\/\.env/.test(code), "no path to a repo .env");
  assert.ok(!/(?:^|\s)(?:source|\.)\s+\S*\.env/m.test(code), "no sourcing of an .env file");
});

// ---- rollback ---------------------------------------------------------------------

test("--rollback-release: dry run prints the steps, validates the id, --apply needs rclone", async () => {
  const s = skeleton();
  let r = await run(["--root", s.root, "--rollback-release", "20260920T101010Z"], { env: {} });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /DRY RUN/);
  assert.match(r.all, /rclone rcat r2:foreclosure-board\/current\.json/);
  r = await run(["--root", s.root, "--rollback-release", "../etc"], { env: {} });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /release id must look like/);
  r = await run(["--root", s.root, "--rollback-release", "20260920T101010Z", "--smoke-test", "https://x.example.com"], { env: {} });
  assert.equal(r.code, 2);
  // Apply against a stub rclone that has the release and a run_meta with a count.
  const rc = path.join(s.root, "rclone");
  const state = path.join(s.root, "pointer.json");
  fs.writeFileSync(
    rc,
    `#!/bin/sh
case "$1" in
  listremotes) echo "r2:";;
  lsf) echo "20260920T101010Z/"; echo "20260921T141132Z/";;
  cat) case "$2" in
         */run_meta.json) echo '{"run_time":"x","board":{"count":170066}}';;
         */current.json) cat "${state}";;
       esac;;
  rcat) cat > "${state}";;
esac
`,
    { mode: 0o755 }
  );
  r = await run(["--root", s.root, "--rollback-release", "20260920T101010Z", "--apply"], { env: { PATH: `${s.root}:${process.env.PATH}` } });
  assert.equal(r.code, 0, r.all);
  const pointer = JSON.parse(fs.readFileSync(state, "utf8"));
  assert.equal(pointer.release, "20260920T101010Z");
  assert.equal(pointer.board_count, 170066);
  assert.match(pointer.published_at, /^\d{4}-\d\d-\d\dT/);
  r = await run(["--root", s.root, "--rollback-release", "20200101T000000Z", "--apply"], { env: { PATH: `${s.root}:${process.env.PATH}` } });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /no folder releases\/20200101T000000Z/);
  assert.equal(JSON.parse(fs.readFileSync(state, "utf8")).release, "20260920T101010Z", "a refused rollback leaves the pointer alone");
});

// ---- smoke test against a local Access simulation ------------------------------------

let kit;
let stub;
let server;
let port;
let mode = "access"; // access | worker-only | open

before(async () => {
  resetAll();
  kit = await makeJwtKit("kid-1");
  stub = stubJwks(kit);
  const sharedEnv = makeEnv({ POINTER_TTL_SECONDS: "0" });
  server = http.createServer(async (req, res) => {
    try {
      const headers = new Headers();
      for (const [k, v] of Object.entries(req.headers)) if (typeof v === "string") headers.set(k, v);
      const id = headers.get("cf-access-client-id");
      const secret = headers.get("cf-access-client-secret");
      if (mode === "access") {
        if (id === "svc.access" && secret === TOKEN_SECRET) {
          headers.delete("cf-access-client-id");
          headers.delete("cf-access-client-secret");
          headers.set("cf-access-jwt-assertion", await kit.token({ email: undefined, common_name: "svc.access", sub: "" }));
        } else {
          res.writeHead(302, { location: `https://${TEAM}.cloudflareaccess.com/cdn-cgi/access/login/board.example.com` });
          return res.end();
        }
      }
      // "open" simulates the worst case: no Access AND the Worker's own gate switched off (localhost only).
      sharedEnv.ACCESS_ENFORCE = mode === "open" ? "false" : "true";
      const request = new Request(`http://localhost:${port}${req.url}`, { method: req.method, headers });
      const response = await worker.fetch(request, sharedEnv, { waitUntil() {}, passThroughOnException() {} });
      const h = {};
      response.headers.forEach((v, k) => { h[k] = v; });
      res.writeHead(response.status, h);
      if (response.body) Readable.fromWeb(response.body).pipe(res);
      else res.end();
    } catch (e) {
      res.writeHead(500);
      res.end(String(e));
    }
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  port = server.address().port;
});
after(() => {
  stub.restore();
  server.close();
});

const smokeEnv = { CF_ACCESS_CLIENT_ID: "svc.access", CF_ACCESS_CLIENT_SECRET: TOKEN_SECRET };

test("smoke test, dry run: lists the checks and sends nothing", async () => {
  const r = await run(["--smoke-test", `http://localhost:${port}`], { env: smokeEnv });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /DRY RUN \(no request is made\)/);
  assert.match(r.all, /values not shown/);
  assert.ok(!r.all.includes(TOKEN_SECRET));
});

test("smoke test refuses plain http to anything but localhost, and odd URLs", async () => {
  for (const u of ["http://board.example.com", "ftp://x", "https://a.example.com/path", "https://a b.com"]) {
    const r = await run(["--smoke-test", u, "--apply"], { env: {} });
    assert.equal(r.code, 1, u);
  }
});

test("smoke test with Access in front and a service token: everything passes", async () => {
  mode = "access";
  const r = await run(["--smoke-test", `http://localhost:${port}`, "--apply"], { env: smokeEnv });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /GET \/ redirects to the Access login/);
  assert.match(r.all, /Worker authenticated the call via: jwt/);
  assert.match(r.all, /first bytes 1f8b/);
  assert.match(r.all, /no Content-Encoding/);
  assert.match(r.all, /If-None-Match on run_meta\.json -> 304/);
  assert.match(r.all, /smoke test: \d+ passed, 0 failed/);
  assert.ok(!r.all.includes(TOKEN_SECRET), "the service token secret is never printed");
});

test("smoke test without a token runs the front-door checks only", async () => {
  mode = "access";
  const r = await run(["--smoke-test", `http://localhost:${port}`, "--apply"], { env: {} });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /SKIPPED/);
  assert.match(r.all, /GET \/listings_slim\.json\.gz refused/);
});

test("smoke test with a wrong service token is refused at the door and fails the token checks", async () => {
  mode = "access";
  const r = await run(["--smoke-test", `http://localhost:${port}`, "--apply"], { env: { CF_ACCESS_CLIENT_ID: "svc.access", CF_ACCESS_CLIENT_SECRET: "wrongwrong" } });
  assert.equal(r.code, 1, r.all);
  assert.match(r.all, /FAIL\s+healthz with the token/);
});

test("smoke test with Access bypassed: the Worker's own gate still refuses (defence in depth)", async () => {
  mode = "worker-only";
  const r = await run(["--smoke-test", `http://localhost:${port}`, "--apply"], { env: {} });
  assert.equal(r.code, 0, r.all);
  assert.match(r.all, /the Worker refused it: defence in depth is active/);
});

test("smoke test against a PUBLIC site fails loudly", async () => {
  mode = "open"; // Access absent AND the Worker's enforcement off, on localhost
  const r = await run(["--smoke-test", `http://localhost:${port}`, "--apply"], { env: {} });
  assert.equal(r.code, 1, r.all);
  assert.match(r.all, /THE SITE IS PUBLIC/);
  assert.match(r.all, /DATA IS PUBLIC/);
  mode = "access";
});
