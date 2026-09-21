// ownerPhoneBlock() in docs/dashboard.js mirrors
// src/foreclosure_scraper/enrichment_sc_phone.owner_phone_block_reason. These are the
// same cases as tests/test_sc_phone_gate.py::
// test_block_reason_covers_every_lane_and_fails_closed_on_an_unstamped_xref_phone,
// so the two stay in step. The code under test is sliced out of dashboard.js.
//
// Run:  node --test tests/js/phone_gate.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.join(HERE, "..", "..", "docs");
const JS = fs.readFileSync(path.join(DOCS, "dashboard.js"), "utf8");

const a = JS.indexOf("// ---- BEGIN PHONE-GATE");
const b = JS.indexOf("// ---- END PHONE-GATE");
assert.ok(a > 0 && b > a, "PHONE-GATE region not found in dashboard.js");

const sandbox = { Object, Array, String };
vm.createContext(sandbox);
const G = vm.runInContext(`"use strict";\n${JS.slice(a, b)}\n;({ ownerPhoneBlock, phoneBlockText })`, sandbox);

const FMT = "(919) 555-0100";
const WALLED_REASON = "people_search_walled";        // enrichment_sc_phone.WALLED_REASON

test("block reason covers every lane and fails closed on an unstamped xref phone", () => {
  const r = G.ownerPhoneBlock;
  assert.equal(r({ phone: FMT, source: "liensnc_filing" }), null);
  assert.equal(r({ phone: FMT, source: "ncsbe_voter", match: "name+address" }), null);
  assert.equal(r({ phone: FMT, source: "buncombe_accela", county_published: true }), null);
  assert.equal(r({ phone: FMT }), null);
  assert.equal(r({ phone: FMT, source: "ncsbe_voter_xref" }), "sc_xref_identity_unchecked");      // never stamped
  assert.equal(r({ phone: FMT, source: "ncsbe_voter_xref", identity_check: "corroborated" }), null);
  assert.equal(r({ phone: FMT, source: "ncsbe_voter_xref", identity_check: "corroborated", do_not_dial: true }), "do_not_dial");
  assert.equal(r({ phone: FMT, source: "free_people_search" }), WALLED_REASON);
  assert.equal(r({ phone: FMT, source: "homeharvest_agent" }), "agent_contact");
  assert.equal(r({ phone: FMT, source: "raw.description" }), "agent_contact");
  assert.equal(r({ phone: FMT, source: "liensnc_filing", role: "agent" }), null);                  // the owner's own number
  assert.equal(r(null), "no_phone");
  assert.equal(r({ source: "liensnc_filing" }), "no_phone");
});

test("the rest of the gate: stamped reasons, other xref verdicts, walled and agent variants", () => {
  const r = G.ownerPhoneBlock;
  assert.equal(r({ phone: FMT, source: "sc_voter_xref" }), "sc_xref_identity_unchecked");
  assert.equal(r({ phone: FMT, source: "sc_voter_xref", identity_check: "unverified" }), "sc_xref_identity_unverified");
  assert.equal(r({ phone: FMT, source: "sc_voter_xref", identity_check: "contradicted" }), "sc_xref_identity_contradicted");
  // a stamped flag wins, with its own reason, and falls back to the generic one
  assert.equal(r({ phone: FMT, source: "sc_voter_xref", do_not_dial: true, do_not_dial_reason: "sc_xref_identity_unverified" }), "sc_xref_identity_unverified");
  assert.equal(r({ phone: FMT, source: "ncsbe_voter", do_not_dial: true }), "do_not_dial");
  // every walled spelling, case-insensitively
  for (const src of ["free_phones", "enrichment_free_phones", "FREE_PEOPLE_SEARCH", "truepeoplesearch", "fastpeoplesearch", "x_peoplesearch_y"]) {
    assert.equal(r({ phone: FMT, source: src }), WALLED_REASON, src);
  }
  // every agent lane: source, role, and the match values
  for (const src of ["homeharvest_agent", "homeharvest_office", "notice_contact_attorney", "ocr_legal_notice", "raw.notice"]) {
    assert.equal(r({ phone: FMT, source: src }), "agent_contact", src);
  }
  assert.equal(r({ phone: FMT, source: "ncsbe_voter", role: "agent" }), "agent_contact");
  for (const m of ["attorney", "attorney_in_notice", "trustee", "listing_agent", "Attorney"]) {
    assert.equal(r({ phone: FMT, source: "ncsbe_voter", match: m }), "agent_contact", m);
  }
  assert.equal(r({ phone: FMT, source: "ncsbe_voter", match: "name+address" }), null);
  // the walled and agent checks come before the xref check, as in Python
  assert.equal(r({ phone: FMT, source: "free_people_search", identity_check: "corroborated" }), WALLED_REASON);
  // junk shapes are "no phone", never a crash
  assert.equal(r([]), "no_phone");
  assert.equal(r("9195550100"), "no_phone");
  assert.equal(r(undefined), "no_phone");
  assert.equal(r({ phone: "" }), "no_phone");
});

test("the badge text: agent lines read as agent lines, every reason has words", () => {
  assert.equal(G.phoneBlockText("agent_contact"), "Listing agent / attorney line, not the owner");
  assert.match(G.phoneBlockText("people_search_walled"), /people-search/);
  assert.match(G.phoneBlockText("sc_xref_identity_unchecked"), /not corroborated.*unchecked/);
  assert.match(G.phoneBlockText("sc_xref_identity_unverified"), /not corroborated.*unverified/);
  assert.match(G.phoneBlockText("sc_xref_identity_contradicted"), /contradicts this owner/);
  assert.equal(G.phoneBlockText("do_not_dial"), "flagged do not dial");
  assert.equal(G.phoneBlockText("some_custom_reason"), "some custom reason");
});

test("dashboard.js uses the gate in the filters, the detail card and the CSV", () => {
  assert.match(JS, /contact === "phone" && ownerPhoneBlock\(r\.owner_phone\)/);
  assert.match(JS, /contact === "contactable" && !\(!ownerPhoneBlock\(r\.owner_phone\) \|\|/);
  assert.doesNotMatch(JS, /contact === "phone" && !r\.owner_phone/);
  // detail card: struck through, DO NOT DIAL badge, reason in words
  assert.match(JS, /<s>\$\{_txt\(_phone\)\}<\/s>/);
  assert.match(JS, /DO NOT DIAL: \$\{_txt\(phoneBlockText\(_pblock\)\)\}/);
  // CSV: owner_phone blank when blocked, and the reason column appended last
  assert.match(JS, /owner_phone: ownerPhoneBlock\(op\) \? "" : \(op\.phone \|\| ""\)/);
  const cols = JS.slice(JS.indexOf("const cols = ["), JS.indexOf("const rows = [cols.join"));
  assert.match(cols, /"clock_status",\s*(\/\/[^\n]*\n\s*)*"phone_block_reason",\s*\]/);
  assert.match(JS, /phone_block_reason: \(\(\) =>/);
});

test("_LEAN_RAW.owner_phone carries the gate's keys, in the order _SLIM_RAW must match", () => {
  const m = /owner_phone: \[([^\]]*)\]/.exec(JS.slice(JS.indexOf("const _LEAN_RAW = {"), JS.indexOf("const _LEAN_RAW_KEYS")));
  assert.ok(m, "owner_phone entry not found in _LEAN_RAW");
  const keys = m[1].split(",").map((k) => k.trim().replace(/"/g, ""));
  assert.deepEqual(keys, ["phone", "source", "needs_dnc_scrub", "do_not_dial", "do_not_dial_reason", "identity_check", "role"]);
});
