import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { classify, RELEASE_FILES, releaseIdFromRunTime, isReleaseId } from "../src/routes.js";

const here = path.dirname(fileURLToPath(import.meta.url));

test("allowlisted release, shell, photo and special paths classify correctly", () => {
  for (const name of RELEASE_FILES.keys()) assert.equal(classify(name).kind, "release", name);
  assert.equal(classify("/detail_shards/00000.json.gz").kind, "release");
  assert.equal(classify("/detail_shards/00170.json.gz").kind, "release");
  assert.equal(classify("/run_meta.json").volatile, true);
  assert.equal(classify("/listings_slim.json.gz").volatile, false);
  assert.equal(classify("/").kind, "shell");
  assert.equal(classify("/").html, true);
  assert.equal(classify("/index.html").assetPath, "/", "index.html is fetched as / to avoid the assets redirect");
  for (const p of ["/dashboard.js", "/style.css", "/premium.css", "/manifest.json", "/icons/icon-192.png", "/icons/icon.svg"]) {
    assert.equal(classify(p).kind, "shell", p);
  }
  assert.deepEqual(classify("/parcel_photos/buncombe_0605781823.jpg"), {
    kind: "photo",
    key: "parcel_photos/buncombe_0605781823.jpg",
    contentType: "image/jpeg",
  });
  assert.equal(classify("/parcel_photos/streetview/sc_spartanburg_7_16_05_046_00.jpg").kind, "photo");
  assert.equal(classify("/parcel_photos/x.JPG").kind, "photo", "uppercase extension, as publish_private.sh allows");
  assert.equal(classify("/parcel_photos/x.webp").contentType, "image/webp");
  assert.equal(classify("/healthz").kind, "healthz");
  assert.equal(classify("/robots.txt").kind, "robots");
  assert.equal(classify("/current.json").kind, "pointer");
});

test("everything not on the allowlist is denied", () => {
  const denied = [
    "/.env",
    "/.git/config",
    "/.secrets/cloudflare_api_token.txt",
    "/parcel_photos/.gitkeep",
    "/icons/.DS_Store",
    "/README.md",
    "/docs/HANDOFF.md",
    "/notes.md",
    "/crm.json",
    "/outreach_maillist.csv",
    "/skiptrace_worksheet.csv",
    "/porsche.json",
    "/listings.json",
    "/listings_slim.json",
    "/listings_detail.json",
    "/listings_sc_backfill.json",
    "/LISTINGS.JSON",
    "/source_health.json",
    "/wall_status.json",
    "/detail_shards/00000.json",
    "/detail_shards/0.json.gz",
    "/detail_shards/abcde.json.gz",
    "/detail_shards/00000.json.gz/extra",
    "/detail_shards/",
    "/parcel_photos/",
    "/parcel_photos/a/b/c.jpg",
    "/parcel_photos/x.gif",
    "/parcel_photos/x.jpg.txt",
    "/releases/20260921T141132Z/listings.json.gz",
    "/current.json.bak",
    "/wrangler.jsonc",
    "/src/index.js",
    "/csp-hashes.json",
    "/worker.js",
    "/scripts/deploy.sh",
    "/a.py",
    "/id.pem",
    "/x.sqlite",
    "/dashboard.js.map",
    "/config.yml",
  ];
  for (const p of denied) assert.equal(classify(p).kind, "denied", `${p} must be denied`);
});

test("path tricks are denied before any lookup", () => {
  const tricks = [
    "/parcel_photos/..%2f..%2fetc/passwd", // encoded slash
    "/%2e%2e/secret",
    "/%2E%2E%2Fsecret",
    "/parcel_photos/a%00.jpg",
    "/parcel_photos//x.jpg",
    "//parcel_photos/x.jpg",
    "/parcel_photos/..\\x.jpg",
    "/parcel_photos/a b.jpg",
    "/parcel_photos/é.jpg",
    "/./index.html",
    "/../index.html",
    "/icons/../.env",
    "/" + "a".repeat(300),
    "",
    "index.html",
  ];
  for (const p of tricks) assert.equal(classify(p).kind, "denied", JSON.stringify(p));
});

test("denial reasons name the rule that fired", () => {
  assert.equal(classify("/.env").reason, "dotfile");
  assert.equal(classify("/listings.json").reason, "uncompressed_listings");
  assert.equal(classify("/README.md").reason, "denied_extension");
  assert.equal(classify("/crm.json").reason, "sensitive_name");
  assert.equal(classify("/nothing.json").reason, "not_allowlisted");
});

test("release id from run_time matches scripts/publish_private.sh", () => {
  assert.equal(releaseIdFromRunTime("2026-09-21T14:11:32.810745Z"), "20260921T141132Z");
  // publish_private.sh: re.sub(non-alnum, "", rt.split(".")[0]) + "Z". Without a
  // fraction the trailing Z is kept and another is appended. Pinned on purpose.
  assert.equal(releaseIdFromRunTime("2026-09-21T14:11:32Z"), "20260921T141132ZZ");
  for (const bad of ["", null, undefined, "1758465092123", "2026-09-21", "2026-09-21T14:11:32+00:00", "../../etc", "2026-09-21T14:11:32.8Z/x", 5]) {
    assert.equal(releaseIdFromRunTime(bad), null, String(bad));
  }
  assert.equal(isReleaseId("20260921T141132Z"), true);
  assert.equal(isReleaseId("../x"), false);
  assert.equal(isReleaseId("short"), false);
});

test("RELEASE_FILES covers every file scripts/publish_private.sh uploads", () => {
  const script = fs.readFileSync(path.resolve(here, "../../scripts/publish_private.sh"), "utf8");
  const grab = (name) => {
    const m = new RegExp(`^${name}="([^"]+)"`, "m").exec(script);
    assert.ok(m, `${name} not found in publish_private.sh`);
    return m[1].split(/\s+/);
  };
  for (const f of [...grab("REQUIRED_FILES"), ...grab("OPTIONAL_FILES")]) {
    assert.ok(RELEASE_FILES.has("/" + f), `publish_private.sh uploads ${f} but the Worker would not serve it`);
  }
});
