#!/usr/bin/env node
// worker/scripts/build_shell.mjs
//
// Assembles worker/shell/ (the Worker's static assets) from docs/, using an
// explicit allowlist, and writes shell/csp-hashes.json next to it.
//
//   node worker/scripts/build_shell.mjs --check     verify only, write nothing
//   node worker/scripts/build_shell.mjs             build worker/shell/
//   node worker/scripts/build_shell.mjs --strict    fail on CSP warnings too
//   options: --docs DIR  --out DIR
//
// Reads only files under docs/ that are named in the allowlist. Never reads
// .env or .secrets, never touches the network.
//
// Cloudflare limits checked (Workers Free): 20,000 files per version and 25 MiB
// per static asset (https://developers.cloudflare.com/workers/platform/limits/).
// The shell is about 0.45 MiB; the 84 MiB board is NOT here, it comes from R2.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { planShell } from "./shell_lib.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const workerDir = path.resolve(here, "..");

function parseArgs(argv) {
  const opts = {
    check: false,
    strict: false,
    docs: path.resolve(workerDir, "..", "docs"),
    out: path.resolve(workerDir, "shell"),
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--check") opts.check = true;
    else if (a === "--strict") opts.strict = true;
    else if (a === "--docs") opts.docs = path.resolve(argv[++i] || "");
    else if (a === "--out") opts.out = path.resolve(argv[++i] || "");
    else if (a === "-h" || a === "--help") {
      console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1, 15).map((l) => l.replace(/^\/\/ ?/, "")).join("\n"));
      process.exit(0);
    } else {
      console.error(`unknown option: ${a}`);
      process.exit(2);
    }
  }
  return opts;
}

function fail(msg) {
  console.error(`build_shell: ${msg}`);
  process.exit(1);
}

/** realpath of the deepest existing ancestor plus the rest, so /var/... and /private/var/... compare equal. */
function realpathLoose(p) {
  let head = path.resolve(p);
  const rest = [];
  while (!fs.existsSync(head)) {
    rest.unshift(path.basename(head));
    const up = path.dirname(head);
    if (up === head) break;
    head = up;
  }
  return path.join(fs.realpathSync(head), ...rest);
}

/** Only ever delete a folder we own: inside worker/ or the system temp dir, never their roots. */
function assertSafeOut(out) {
  const target = realpathLoose(out);
  const roots = [fs.realpathSync(workerDir), fs.realpathSync(os.tmpdir())];
  const ok = roots.some((r) => target.startsWith(r + path.sep) && target !== r);
  if (!ok) fail(`refusing to write to ${out}: output must be a folder inside ${workerDir} or the temp dir`);
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  let plan;
  try {
    plan = planShell(opts.docs);
  } catch (e) {
    fail(e.message);
  }
  const kib = (n) => (n / 1024).toFixed(1) + " KiB";
  console.log(`shell source     : ${opts.docs}`);
  console.log(`files            : ${plan.files.length} (+ csp-hashes.json), ${kib(plan.total)} total`);
  for (const [f, s] of plan.sizes) console.log(`  ${kib(s).padStart(10)}  ${f}`);
  console.log(`inline scripts   : ${plan.csp.scripts.length} hashed`);
  console.log(`inline handlers  : ${plan.csp.handlers.length} hashed`);
  for (const w of plan.csp.warnings) console.log(`WARNING          : ${w}`);
  if (plan.csp.warnings.length && opts.strict) fail("CSP warnings present and --strict was given");

  if (opts.check) {
    console.log("check only: nothing written");
    return;
  }
  assertSafeOut(opts.out);
  fs.rmSync(opts.out, { recursive: true, force: true });
  for (const f of plan.files) {
    const dest = path.join(opts.out, f);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(opts.docs, f), dest);
  }
  fs.writeFileSync(
    path.join(opts.out, "csp-hashes.json"),
    JSON.stringify({ scripts: plan.csp.scripts, handlers: plan.csp.handlers, warnings: plan.csp.warnings }, null, 2) + "\n"
  );
  console.log(`built            : ${opts.out}`);
}

main();
