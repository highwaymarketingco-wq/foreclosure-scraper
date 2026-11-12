// worker/scripts/config_lib.mjs
//
// Reads worker/wrangler.jsonc (JSON with comments) and produces the rendered
// config that scripts/deploy_worker.sh deploys. Pure, no I/O, so it is tested
// in worker/test/config.test.mjs.

/** Parse JSON with // and /* comments and trailing commas. Strings are respected. */
export function parseJsonc(text) {
  let out = "";
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (c === '"') {
      let j = i + 1;
      while (j < n && text[j] !== '"') j += text[j] === "\\" ? 2 : 1;
      out += text.slice(i, j + 1);
      i = j + 1;
    } else if (c === "/" && text[i + 1] === "/") {
      while (i < n && text[i] !== "\n") i++;
    } else if (c === "/" && text[i + 1] === "*") {
      const end = text.indexOf("*/", i + 2);
      i = end === -1 ? n : end + 2;
    } else {
      out += c;
      i++;
    }
  }
  out = out.replace(/,(\s*[}\]])/g, "$1");
  return JSON.parse(out);
}

const RE = {
  account: /^[0-9a-f]{32}$/,
  aud: /^[0-9a-f]{64}$/,
  team: /^[a-z0-9][a-z0-9-]{0,62}(?:\.cloudflareaccess\.com)?$/,
  hostname: /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/,
  bucket: /^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/,
  name: /^[a-z0-9][a-z0-9-]{0,52}[a-z0-9]$/,
  bool: /^(true|false)$/,
};

export function validateSetting(kind, value) {
  if (!RE[kind].test(String(value))) throw new Error(`invalid ${kind}: ${JSON.stringify(value)}`);
  return String(value);
}

/**
 * @param {object} base   parsed template
 * @param {{name?, account?, team?, aud?, bucket?, urlMode?: "workers-dev"|"custom-domain"|"", hostname?,
 *          cspRelaxed?: "true"|"false", authDebug?: "true"|"false"}} s
 * @returns {object} config to write as wrangler.rendered.jsonc
 */
export function renderConfig(base, s = {}) {
  const cfg = JSON.parse(JSON.stringify(base));
  if (s.name) cfg.name = validateSetting("name", s.name);
  if (s.account) cfg.account_id = validateSetting("account", s.account);
  if (s.bucket) cfg.r2_buckets[0].bucket_name = validateSetting("bucket", s.bucket);
  if (s.team) cfg.vars.ACCESS_TEAM_DOMAIN = validateSetting("team", s.team);
  if (s.aud) cfg.vars.ACCESS_AUD = validateSetting("aud", s.aud);
  if (s.cspRelaxed) cfg.vars.CSP_RELAXED = validateSetting("bool", s.cspRelaxed);
  if (s.authDebug) cfg.vars.AUTH_DEBUG = validateSetting("bool", s.authDebug);

  const mode = s.urlMode || "";
  cfg.preview_urls = false;
  if (mode === "workers-dev") {
    cfg.workers_dev = true;
    delete cfg.routes;
  } else if (mode === "custom-domain") {
    if (!s.hostname) throw new Error("URL_MODE=custom-domain needs WORKER_HOSTNAME");
    cfg.workers_dev = false;
    cfg.routes = [{ pattern: validateSetting("hostname", s.hostname), custom_domain: true }];
  } else if (mode === "") {
    cfg.workers_dev = false;
    delete cfg.routes;
  } else {
    throw new Error(`unknown URL_MODE ${JSON.stringify(mode)} (use workers-dev or custom-domain)`);
  }
  return cfg;
}
