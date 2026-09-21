// worker/src/routes.js
//
// Path classification and the ALLOWLIST. Pure functions, no I/O, no Workers
// globals, so it runs unchanged under node:test.
//
// Default is DENY. A path is served only if it matches one of:
//   - a fixed name in RELEASE_FILES or SHELL_FILES,
//   - listings_part_NNN.json.gz (the board, cut into parts; see PART_RE),
//   - detail_shards/NNNNN.json.gz,
//   - icons/<name>.(png|svg|ico),
//   - parcel_photos/[<one folder>/]<name>.(jpg|jpeg|png|webp),
//   - the three special endpoints /healthz, /robots.txt, /current.json.
//
// The names in RELEASE_FILES mirror OPTIONAL_FILES + REQUIRED_FILES in
// scripts/publish_private.sh; SHELL_FILES mirror worker/scripts/build_shell.mjs.
// Keep the three lists in step (worker/test/routes.test.mjs checks the first).

const JSON_UTF8 = "application/json; charset=utf-8";
const GZIP = "application/gzip"; // no Content-Encoding: see worker/README.md

/** Files that live inside releases/<id>/ in the bucket. Value = content type. */
export const RELEASE_FILES = new Map([
  // Legacy single-file board. Since the payload split (audit O1) the board is the numbered
  // parts matched by PART_RE below; this entry stays only so a rollback to the pre-split
  // dashboard.js keeps working against a release that still carries the file. Drop it, and the
  // matching line in scripts/publish_private.sh, when the rollback path is retired.
  ["/listings.json.gz", GZIP],
  ["/listings_slim.json.gz", GZIP],
  ["/listings_detail.json.gz", GZIP],
  ["/run_meta.json", JSON_UTF8],
  ["/run_health.json", JSON_UTF8],
  ["/multifamily.json", JSON_UTF8],
  ["/land_buyers.json", JSON_UTF8],
  ["/foreclosure_sold_pool.json", JSON_UTF8],
]);

/** Release files whose content must never be cached by the browser. */
export const VOLATILE_RELEASE_FILES = new Set(["/run_meta.json"]);

/** App shell, served from the Worker's static assets. Value = content type. */
export const SHELL_FILES = new Map([
  ["/", "text/html; charset=utf-8"],
  ["/index.html", "text/html; charset=utf-8"],
  ["/dashboard.js", "text/javascript; charset=utf-8"],
  ["/style.css", "text/css; charset=utf-8"],
  ["/premium.css", "text/css; charset=utf-8"],
  ["/manifest.json", "application/manifest+json; charset=utf-8"],
]);

const IMAGE_TYPES = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  svg: "image/svg+xml",
  ico: "image/x-icon",
};

// Only characters a real file name in this project uses. No %, no backslash,
// no spaces, no unicode, no "..", no "//". Anything else is refused before any
// lookup, so there is nothing to decode or normalise.
const SAFE_PATH = /^\/[A-Za-z0-9_./-]*$/;

// Defence in depth. The allowlist below is already exact; these exist so that
// a careless future edit to it still cannot expose the obvious dangerous names.
const DENY_EXT = /\.(?:md|env|csv|py|sh|sqlite|db|pem|key|map|log|ya?ml|toml|lock|txt|bak|orig|swp|zip|tar|tgz)$/i;
const DENY_UNCOMPRESSED_LISTINGS = /^\/listings[^/]*\.json$/i;
const DENY_NAME = /(?:crm|outreach|maillist|skiptrace|porsche|secret|credential|password|passwd)/i;

const SHARD_RE = /^\/detail_shards\/\d{5}\.json\.gz$/;
// The board, cut into independently gzipped JSON-array parts (audit O1): /listings_part_000.json.gz,
// /listings_part_001.json.gz, ... Each is under 24 MiB, so each fits Cloudflare's 25 MiB per-asset
// cap. Exactly three digits (the writer pads to 3 and only grows to 4 past part 999), nothing
// else: not the plain .json (DENY_UNCOMPRESSED_LISTINGS above denies that), not a suffix, not a
// directory. The list of parts and their checksums is in run_meta.json (board_parts).
const PART_RE = /^\/listings_part_\d{3,4}\.json\.gz$/;
const ICON_RE = /^\/icons\/[A-Za-z0-9_-]+\.(png|svg|ico)$/i;
const PHOTO_RE = /^\/parcel_photos\/(?:[A-Za-z0-9_-]+\/)?[A-Za-z0-9_][A-Za-z0-9_.-]*\.(jpe?g|png|webp)$/i;

export const MAX_PATH_LENGTH = 200;

/**
 * Classify a URL pathname (already the raw `URL.pathname`, not decoded).
 * Returns one of:
 *   { kind: "denied", reason }
 *   { kind: "healthz" | "robots" | "pointer" }
 *   { kind: "release", name, contentType, volatile }
 *   { kind: "photo", key, contentType }
 *   { kind: "shell", assetPath, contentType, html }
 */
export function classify(pathname) {
  if (typeof pathname !== "string" || pathname.length === 0) return denied("empty");
  if (pathname.length > MAX_PATH_LENGTH) return denied("too_long");
  if (!SAFE_PATH.test(pathname)) return denied("bad_chars");
  if (pathname.includes("//")) return denied("double_slash");

  const segments = pathname.split("/").slice(1);
  for (const seg of segments) {
    if (seg.startsWith(".")) return denied("dotfile"); // also kills "." and ".."
  }

  // Special endpoints, all served by the Worker itself.
  if (pathname === "/healthz") return { kind: "healthz" };
  if (pathname === "/robots.txt") return { kind: "robots" };
  if (pathname === "/current.json") return { kind: "pointer" };

  if (DENY_UNCOMPRESSED_LISTINGS.test(pathname)) return denied("uncompressed_listings");
  if (DENY_EXT.test(pathname)) return denied("denied_extension");
  if (DENY_NAME.test(pathname)) return denied("sensitive_name");

  if (RELEASE_FILES.has(pathname)) {
    return {
      kind: "release",
      name: pathname,
      contentType: RELEASE_FILES.get(pathname),
      volatile: VOLATILE_RELEASE_FILES.has(pathname),
    };
  }
  if (SHARD_RE.test(pathname) || PART_RE.test(pathname)) {
    return { kind: "release", name: pathname, contentType: GZIP, volatile: false };
  }

  const photo = PHOTO_RE.exec(pathname);
  if (photo) {
    return { kind: "photo", key: pathname.slice(1), contentType: IMAGE_TYPES[photo[1].toLowerCase()] };
  }

  if (SHELL_FILES.has(pathname)) {
    return {
      kind: "shell",
      // index.html is fetched as "/" so the assets service never answers with
      // its trailing-slash redirect (html_handling default is auto-trailing-slash).
      assetPath: pathname === "/index.html" ? "/" : pathname,
      contentType: SHELL_FILES.get(pathname),
      html: pathname === "/" || pathname === "/index.html",
    };
  }
  const icon = ICON_RE.exec(pathname);
  if (icon) {
    return { kind: "shell", assetPath: pathname, contentType: IMAGE_TYPES[icon[1].toLowerCase()], html: false };
  }

  return denied("not_allowlisted");
}

function denied(reason) {
  return { kind: "denied", reason };
}

// ---------------------------------------------------------------------------
// Release selection from the dashboard's ?t=<run_time> cache-buster.
//
// dashboard.js fetches every payload file as `<name>?t=<run_time>`, where
// run_time is the value it just read from run_meta.json. publish_private.sh
// names the release folder from that same run_time, so the query string tells
// the Worker exactly which release the page is built from. Serving that release
// (and not "whatever is current now") is what stops a phone that opened the
// board before a publish from reading detail shards of the NEXT board: the
// dashboard joins board and shards by array index, so a mix shows another
// property's owner and phone on a card.

// e.g. 2026-09-21T14:11:32.810745Z  (optional fraction, always Z)
const RUN_TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/;
const RELEASE_ID_RE = /^[0-9A-Za-z_-]{8,40}$/;

export function isReleaseId(value) {
  return typeof value === "string" && RELEASE_ID_RE.test(value);
}

/**
 * Release id for a run_time string, or null when it is not a run_time.
 *
 * Bug-compatible with the python in scripts/publish_private.sh:
 *   re.sub(r"[^0-9A-Za-z]", "", rt.split(".")[0]) + "Z"
 * (so a fraction-less run_time yields an id ending "ZZ", exactly as the
 * publisher names it; test/routes.test.mjs pins both forms).
 */
export function releaseIdFromRunTime(t) {
  if (typeof t !== "string" || !RUN_TIME_RE.test(t)) return null;
  const id = t.split(".")[0].replace(/[^0-9A-Za-z]/g, "") + "Z";
  return isReleaseId(id) ? id : null;
}
