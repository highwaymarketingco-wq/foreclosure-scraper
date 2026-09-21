#!/usr/bin/env node
// worker/scripts/render_config.mjs
//
//   node worker/scripts/render_config.mjs [--out FILE] [--print]
//         [--name N] [--account ID] [--team T] [--aud TAG] [--bucket B]
//         [--url-mode workers-dev|custom-domain] [--hostname H]
//         [--csp-relaxed true|false] [--auth-debug true|false]
//
// Renders worker/wrangler.jsonc plus your values into worker/wrangler.rendered.jsonc.
// No network, and it reads only worker/wrangler.jsonc. Called by
// scripts/deploy_worker.sh; usable on its own to see exactly what would deploy.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseJsonc, renderConfig } from "./config_lib.mjs";

const workerDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const opt = {};
let printOnly = false;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--print") printOnly = true;
  else if (a.startsWith("--")) opt[a.slice(2)] = args[++i];
  else {
    console.error(`unexpected argument: ${a}`);
    process.exit(2);
  }
}

try {
  const base = parseJsonc(fs.readFileSync(path.join(workerDir, "wrangler.jsonc"), "utf8"));
  const cfg = renderConfig(base, {
    name: opt.name,
    account: opt.account,
    team: opt.team,
    aud: opt.aud,
    bucket: opt.bucket,
    urlMode: opt["url-mode"],
    hostname: opt.hostname,
    cspRelaxed: opt["csp-relaxed"],
    authDebug: opt["auth-debug"],
  });
  const text = JSON.stringify(cfg, null, 2) + "\n";
  if (printOnly) {
    process.stdout.write(text);
  } else {
    const wanted = path.resolve(opt.out || path.join(workerDir, "wrangler.rendered.jsonc"));
    // Compare real paths so a symlinked parent (macOS /var -> /private/var) cannot fool or fail the check.
    const out = path.join(fs.realpathSync(path.dirname(wanted)), path.basename(wanted));
    if (!out.startsWith(fs.realpathSync(workerDir) + path.sep)) throw new Error("--out must be inside worker/");
    fs.writeFileSync(out, text);
    console.log(`rendered ${path.relative(process.cwd(), out) || out}`);
  }
} catch (e) {
  console.error(`render_config: ${e.message}`);
  process.exit(1);
}
