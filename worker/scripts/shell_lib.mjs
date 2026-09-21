// worker/scripts/shell_lib.mjs
//
// Pure helpers for build_shell.mjs: which files make up the app shell, and the
// CSP hashes for the inline code in them. No I/O beyond reading what it is told
// to, so worker/test/shell.test.mjs can drive it with fixtures.

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { classify } from "../src/routes.js";

const MAX_ASSET_BYTES = 25 * 1024 * 1024;
const MAX_ASSET_FILES = 20000;

/** Base64 SHA-256 in CSP form, over the text as the browser will see it (LF newlines). */
export function cspHash(text) {
  const norm = String(text).replace(/\r\n?/g, "\n");
  return "sha256-" + createHash("sha256").update(norm, "utf8").digest("base64");
}

function findTagEnd(html, from) {
  let quote = "";
  for (let i = from; i < html.length; i++) {
    const c = html[i];
    if (quote) {
      if (c === quote) quote = "";
    } else if (c === '"' || c === "'") {
      quote = c;
    } else if (c === ">") {
      return i;
    }
  }
  return -1;
}

/**
 * Bodies of the executable inline <script> blocks in an HTML document.
 * Skips <!-- comments --> (index.html mentions "<style>" and friends in its
 * comments), scripts with a src, and non-JavaScript types such as JSON.
 */
export function extractInlineScripts(html) {
  const out = [];
  const lower = html.toLowerCase();
  let i = 0;
  while (i < html.length) {
    const c = lower.indexOf("<!--", i);
    const s = lower.indexOf("<script", i);
    if (s === -1 && c === -1) break;
    if (c !== -1 && (s === -1 || c < s)) {
      const end = html.indexOf("-->", c + 4);
      i = end === -1 ? html.length : end + 3;
      continue;
    }
    const after = html[s + 7];
    if (after !== undefined && !/[\s>/]/.test(after)) {
      i = s + 7;
      continue;
    }
    const tagEnd = findTagEnd(html, s + 7);
    if (tagEnd === -1) break;
    const attrs = " " + html.slice(s + 7, tagEnd);
    const close = lower.indexOf("</script", tagEnd + 1);
    if (close === -1) break;
    const body = html.slice(tagEnd + 1, close);
    const hasSrc = /\ssrc\s*=/i.test(attrs);
    const typeMatch = /\stype\s*=\s*["']?([^"'\s>]*)/i.exec(attrs);
    const type = typeMatch ? typeMatch[1].toLowerCase() : "";
    const isJs = type === "" || type === "text/javascript" || type === "application/javascript" || type === "module";
    if (!hasSrc && isJs && body.trim() !== "") out.push(body);
    i = close + 8;
  }
  return out;
}

function decodeAttr(s) {
  return s
    .replace(/&quot;/g, '"')
    .replace(/&#0*39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

/**
 * Inline event-handler attributes (onclick="...") in HTML or in the HTML that a
 * script writes. Returns { literal: string[], dynamic: string[] }: `dynamic`
 * handlers contain a template interpolation and cannot be hashed ahead of time.
 */
export function extractHandlers(text) {
  const literal = new Set();
  const dynamic = new Set();
  const re = /\son([a-z]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
  let m;
  while ((m = re.exec(text)) !== null) {
    const value = decodeAttr(m[2] !== undefined ? m[2] : m[3]);
    if (value.trim() === "") continue;
    if (value.includes("${") || value.includes("{{")) dynamic.add(value);
    else literal.add(value);
  }
  return { literal: [...literal], dynamic: [...dynamic] };
}

/**
 * Compute the CSP hash manifest from the shell sources.
 * @param {{indexHtml: string, dashboardJs: string}} src
 */
export function buildCspManifest({ indexHtml, dashboardJs }) {
  const scripts = extractInlineScripts(indexHtml).map(cspHash);
  const a = extractHandlers(indexHtml);
  const b = extractHandlers(dashboardJs);
  const handlerTexts = new Set([...a.literal, ...b.literal]);
  const dynamic = [...new Set([...a.dynamic, ...b.dynamic])];
  return {
    scripts: [...new Set(scripts)],
    handlers: [...handlerTexts].map(cspHash),
    warnings: dynamic.map(
      (d) => `inline handler with a template interpolation cannot be hashed and will be blocked: ${d.slice(0, 80)}`
    ),
  };
}

/** Names copied into the shell, relative to docs/. Everything must classify as "shell". */
export function shellFileList(iconNames) {
  const files = ["index.html", "dashboard.js", "style.css", "premium.css", "manifest.json"];
  for (const n of iconNames) files.push(`icons/${n}`);
  return files;
}

/** Throws unless every file would be served by the Worker as part of the shell. */
export function assertShellCovered(files) {
  const bad = [];
  for (const f of files) {
    const route = classify("/" + f);
    if (route.kind !== "shell") bad.push(`${f} -> ${route.kind}${route.reason ? " (" + route.reason + ")" : ""}`);
  }
  if (bad.length) {
    throw new Error("shell file(s) the Worker allowlist would not serve: " + bad.join("; "));
  }
}

/** Read docs/ and work out what goes in the shell, with sizes and CSP hashes. Throws on any problem. */
export function planShell(docs) {
  const iconDir = path.join(docs, "icons");
  const iconNames = fs.existsSync(iconDir)
    ? fs.readdirSync(iconDir).filter((n) => /^[A-Za-z0-9_-]+\.(png|svg|ico)$/i.test(n)).sort()
    : [];
  const files = shellFileList(iconNames);
  for (const f of files) {
    if (!fs.existsSync(path.join(docs, f))) throw new Error(`required shell file missing: docs/${f}`);
  }
  assertShellCovered(files);

  // Icons named by the page or the manifest must be in the shell.
  const manifest = JSON.parse(fs.readFileSync(path.join(docs, "manifest.json"), "utf8"));
  const html = fs.readFileSync(path.join(docs, "index.html"), "utf8");
  const referenced = new Set();
  for (const ic of manifest.icons || []) if (ic && typeof ic.src === "string") referenced.add(ic.src.replace(/^\.?\//, ""));
  for (const m of html.matchAll(/href="(icons\/[^"?#]+)/g)) referenced.add(m[1]);
  const missing = [...referenced].filter((r) => !files.includes(r));
  if (missing.length) throw new Error(`manifest/index.html reference icons that are not in the shell: ${missing.join(", ")}`);

  let total = 0;
  const sizes = [];
  for (const f of files) {
    const size = fs.statSync(path.join(docs, f)).size;
    if (size > MAX_ASSET_BYTES) throw new Error(`docs/${f} is ${size} bytes, over the 25 MiB static asset limit`);
    total += size;
    sizes.push([f, size]);
  }
  if (files.length + 1 > MAX_ASSET_FILES) throw new Error("too many static assets");

  const csp = buildCspManifest({
    indexHtml: html,
    dashboardJs: fs.readFileSync(path.join(docs, "dashboard.js"), "utf8"),
  });
  return { files, sizes, total, csp };
}
