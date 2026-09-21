// Tests for the lead-lifecycle logic in docs/dashboard.js (audit F2, F3, F13,
// F15, F19 in docs/audit_signal_logic_2026-09-21.md).
//
// The code under test is the code that ships: this file slices the stage
// constants, the LEAD-STATE region and the deadline/stage functions out of
// dashboard.js and runs them under node's vm with a pinned clock. Nothing is
// re-implemented here.
//
// Run:  node --test tests/js/lead_state.test.mjs
// (tests/test_dashboard_lead_state_js.py runs it under pytest when node exists.)
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.join(HERE, "..", "..", "docs");
const JS = fs.readFileSync(path.join(DOCS, "dashboard.js"), "utf8");
const HTML = fs.readFileSync(path.join(DOCS, "index.html"), "utf8");

// Contiguous slice: stage constants, LEAD-STATE, DEADLINES, clockOf, stageOf.
const START = JS.indexOf("const STAGE_REO =");
const END = JS.indexOf("function updateStageCounts");
assert.ok(START > 0 && END > START, "could not locate the lead-state slice in dashboard.js");
const SLICE = JS.slice(START, END);
assert.ok(SLICE.includes("BEGIN LEAD-STATE") && SLICE.includes("END LEAD-STATE"));

/** A fresh sandbox whose clock is pinned to `now` (local time). */
function load(now = new Date(2026, 8, 21, 15, 0, 0)) {   // 2026-09-21 15:00 local
  const FIXED = now.getTime();
  class FixedDate extends Date {
    constructor(...a) { if (a.length === 0) super(FIXED); else super(...a); }
    static now() { return FIXED; }
  }
  const sandbox = { Date: FixedDate, Math, Object, Array, String, Number, isNaN, isFinite, parseInt, parseFloat };
  vm.createContext(sandbox);
  const stub = `function _memo(l, key, value) {
    Object.defineProperty(l, key, { value, writable: true, enumerable: false, configurable: true });
    return value; }`;
  const exportNames = [
    "_dayNum", "_todayNum", "upsetBidState", "saleClock", "redemptionState", "presumedWithdrawn",
    "bankruptcyStay", "stayLines", "leadClock", "deadlineSortValue", "clockPill", "clockBadges",
    "clockSummary", "distressCategories", "stackSignals", "signalTipText", "nameMatchList",
    "equityView", "propertyAddress", "dataFreshness", "fmtAgeHours", "stageOf", "deadlineInfo",
    "clockOf", "CLOCK_SORT_HORIZON_DAYS", "UPSET_BID_EST_DAYS", "FRESHNESS_STALE_HOURS",
    "scoredEvent", "stackTooltip", "bankruptcyLapsed", "BK_TTL_DAYS_CH7", "BK_TTL_DAYS_OTHER",
    "FILING_DATE_SOURCES",
  ];
  const code = `"use strict";\n${stub}\n${SLICE}\n;({ ${exportNames.join(", ")} })`;
  return vm.runInContext(code, sandbox);
}

// Arrays and objects built inside the vm carry that realm's prototypes, which
// deepStrictEqual (rightly) refuses to call equal to host literals.
const plain = (v) => JSON.parse(JSON.stringify(v));

const NOW = new Date(2026, 8, 21, 15, 0, 0);
const day = (offset) => {                                  // ISO date `offset` days from NOW
  const d = new Date(2026, 8, 21 + offset);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T00:00:00`;
};
const lead = (o = {}) => ({ listing_type: "foreclosure_sale", source: "law_firms.x", state: "NC", raw: {}, ...o });

// ---------------------------------------------------------------------------
test("_dayNum reads calendar days from ISO, datetime and MM/DD/YYYY, and refuses garbage", () => {
  const S = load();
  assert.equal(S._dayNum("2026-09-25"), S._dayNum("2026-09-25T23:59:59"));
  assert.equal(S._dayNum("09/25/2026"), S._dayNum("2026-09-25"));
  assert.equal(S._dayNum("9/25/26"), S._dayNum("2026-09-25"));
  assert.equal(S._dayNum(null), null);
  assert.equal(S._dayNum(""), null);
  assert.equal(S._dayNum("not a date"), null);
  assert.equal(S._dayNum("2026-13-40"), null);
  assert.equal(S._dayNum("2026-09-25") - S._todayNum(NOW.getTime()), 4);
});

// ---------------------------------------------------------------------------
// F2 + F15: a closed window is not an open window, and the counters are not read.
test("F2: an upset_bid block with in_window true but a deadline 19 days behind us is CLOSED", () => {
  const S = load();
  // The exact shape found on the slim board: {in_window: true, days_remaining: 8}
  // beside upset_bid_deadline 2026-09-02, read on 2026-09-21.
  const l = lead({ raw: { upset_bid: { in_window: true, days_remaining: 8 } }, upset_bid_deadline: "2026-09-02T00:00:00" });
  const u = S.upsetBidState(l, NOW.getTime());
  assert.equal(u.open, false);
  assert.equal(u.closed, true);
  assert.equal(u.days, -19);
});

test("F2: in_window false closes the window even when the deadline is still in the future", () => {
  const S = load();
  const l = lead({ raw: { upset_bid: { in_window: false, days_remaining: 0 } }, upset_bid_deadline: day(5) });
  assert.equal(S.upsetBidState(l, NOW.getTime()).open, false);
});

test("F2: an empty upset_bid block (what slim emits when no sub-key survives) is not open", () => {
  const S = load();
  const u = S.upsetBidState(lead({ raw: { upset_bid: {} }, upset_bid_deadline: day(5) }), NOW.getTime());
  assert.equal(u.open, false);
  assert.equal(u.tagged, true);
});

test("F15: open is decided from the deadline against today, not from days_remaining", () => {
  const S = load();
  const l = lead({ raw: { upset_bid: { in_window: true, days_remaining: 999 } }, upset_bid_deadline: day(3) });
  const u = S.upsetBidState(l, NOW.getTime());
  assert.equal(u.open, true);
  assert.equal(u.days, 3);                       // not 999
  // The deadline day itself is still open.
  assert.equal(S.upsetBidState(lead({ raw: { upset_bid: { in_window: true } }, upset_bid_deadline: day(0) }), NOW.getTime()).open, true);
  assert.equal(S.upsetBidState(lead({ raw: { upset_bid: { in_window: true } }, upset_bid_deadline: day(-1) }), NOW.getTime()).open, false);
});

test("a tagged window with no published deadline falls back to sale date + 14 days, labelled estimated", () => {
  const S = load();
  const u = S.upsetBidState(lead({ raw: { upset_bid: { in_window: true } }, sale_date: day(-4) }), NOW.getTime());
  assert.equal(u.open, true);
  assert.equal(u.days, S.UPSET_BID_EST_DAYS - 4);
  assert.equal(u.basis, "sale_date");
  const gone = S.upsetBidState(lead({ raw: { upset_bid: { in_window: true } }, sale_date: day(-20) }), NOW.getTime());
  assert.equal(gone.open, false);
  assert.equal(gone.closed, true);
  const none = S.upsetBidState(lead({ raw: { upset_bid: { in_window: true } } }), NOW.getTime());
  assert.equal(none.open, true);
  assert.equal(none.unverified, true);
});

test("an untagged NC lead sold this week is an estimate only; SC gets none", () => {
  const S = load();
  const nc = S.upsetBidState(lead({ sale_date: day(-3) }), NOW.getTime());
  assert.equal(nc.open, false);
  assert.equal(nc.estimatedOpen, true);
  assert.equal(S.upsetBidState(lead({ state: "SC", sale_date: day(-3) }), NOW.getTime()).estimatedOpen, false);
});

test("F2: stageOf does not put a lead with a closed window in the foreclosure stage", () => {
  const S = load();
  const base = { listing_type: "tax_sale", source: "counties_nc.some_tax", state: "NC" };
  const closedFlag = { ...base, raw: { upset_bid: { in_window: false } }, upset_bid_deadline: day(4) };
  const stale = { ...base, raw: { upset_bid: { in_window: true, days_remaining: 8 } }, upset_bid_deadline: day(-19) };
  const open = { ...base, raw: { upset_bid: { in_window: true } }, upset_bid_deadline: day(4) };
  assert.equal(S.stageOf(closedFlag), "outbound");
  assert.equal(S.stageOf(stale), "outbound");
  assert.equal(S.stageOf(open), "foreclosure");
});

// ---------------------------------------------------------------------------
// Sale date passed, presumed withdrawn, redemption: text from the dates.
test("sale date passed N days ago comes from sale_date, not from raw.sale_date_passed_days", () => {
  const S = load();
  const l = lead({ sale_date: day(-12), state: "SC", raw: { sale_date_passed: true, sale_date_passed_days: 3 } });
  const ck = S.leadClock(l, NOW.getTime());
  assert.equal(ck.salePassed, true);
  assert.equal(ck.passedDays, 12);
  const texts = S.clockBadges(l, ck, NOW.getTime()).map((b) => b.text);
  assert.ok(texts.includes("sale date passed 12 days ago"), texts.join(" | "));
  assert.equal(S.clockBadges(lead({ sale_date: day(-1), state: "SC" }), S.leadClock(lead({ sale_date: day(-1), state: "SC" }), NOW.getTime()), NOW.getTime())[0].text,
    "sale date passed 1 day ago");
});

test("window closed / redemption text", () => {
  const S = load();
  const l = lead({ state: "SC", raw: { upset_bid: { in_window: false } }, upset_bid_deadline: day(-19), redemption_deadline: "2026-12-31T00:00:00" });
  const t = S.clockBadges(l, S.leadClock(l, NOW.getTime()), NOW.getTime()).map((b) => b.text);
  assert.ok(t.some((x) => x.startsWith("window closed")), t.join(" | "));
  assert.ok(t.includes("redemption ends Dec 31"), t.join(" | "));
  const ended = lead({ redemption_deadline: "2026-01-15T00:00:00" });
  const t2 = S.clockBadges(ended, S.leadClock(ended, NOW.getTime()), NOW.getTime()).map((b) => b.text);
  assert.ok(t2.includes("redemption ended Jan 15"), t2.join(" | "));
});

test("presumed withdrawn is read from pulled_sale, auction_status and stale_case", () => {
  const S = load();
  assert.equal(S.presumedWithdrawn(lead({ raw: { pulled_sale: { presumed_withdrawn: true } } })), true);
  assert.equal(S.presumedWithdrawn(lead({ auction_status: "presumed_withdrawn" })), true);
  assert.equal(S.presumedWithdrawn(lead({ raw: { stale_case: true } })), true);
  assert.equal(S.presumedWithdrawn(lead({ raw: { pulled_sale: { presumed_withdrawn: false } } })), false);
  assert.equal(S.presumedWithdrawn(lead()), false);
  // A withdrawn lead has no live deadline: its old sale date is not a clock.
  const l = lead({ sale_date: day(5), raw: { pulled_sale: { presumed_withdrawn: true } } });
  const ck = S.leadClock(l, NOW.getTime());
  assert.equal(ck.live, null);
  assert.equal(S.deadlineInfo(l), null);
  assert.ok(S.clockBadges(l, ck, NOW.getTime()).some((b) => b.kind === "withdrawn"));
});

test("the live deadline is the soonest of upset close, sale and redemption", () => {
  const S = load();
  const l = lead({ state: "SC", sale_date: day(9), redemption_deadline: day(40), raw: {} });
  assert.equal(S.leadClock(l, NOW.getTime()).live.kind, "sale");
  assert.equal(S.leadClock(l, NOW.getTime()).live.days, 9);
  const l2 = lead({ raw: { upset_bid: { in_window: true } }, upset_bid_deadline: day(2), sale_date: day(-8) });
  const c2 = S.leadClock(l2, NOW.getTime());
  assert.equal(c2.live.kind, "upset");
  assert.equal(S.clockPill(c2.live).strip, "UPSET BID CLOSES IN 2 DAYS");
  assert.equal(S.clockPill(S.leadClock(lead({ sale_date: day(0) }), NOW.getTime()).live).txt, "TODAY");
  assert.equal(S.clockPill(S.leadClock(lead({ sale_date: day(0) }), NOW.getTime()).live).strip, "SALE TODAY");
  assert.equal(S.clockPill(S.leadClock(lead({ sale_date: day(1) }), NOW.getTime()).live).strip, "SALE IN 1 DAY");
});

// ---------------------------------------------------------------------------
// Sort: deadline first, then tier; demoted leads at the bottom.
test("deadline-first sort: live deadline soonest, then tier, then grade; demoted last", () => {
  const S = load();
  const mk = (name, o, tier, grade = 50) => ({ name, l: lead({ state: "SC", ...o }), tier, grade });
  const items = [
    mk("hot-no-date", {}, "HOT", 70),
    mk("cold-sale-3d", { sale_date: day(3) }, "COLD", 10),
    mk("hot-sale-10d", { sale_date: day(10) }, "HOT", 90),
    mk("hot-passed-12d", { sale_date: day(-12) }, "HOT", 90),
    mk("hot-withdrawn-future-sale", { sale_date: day(6), raw: { pulled_sale: { presumed_withdrawn: true } } }, "HOT", 90),
    mk("warm-stayed-2d", { sale_date: day(2), raw: { bankruptcy: { chapter: "13", date_filed: "2026-03-01" } } }, "WARM", 60),
    mk("cold-redemption-200d", { redemption_deadline: day(200) }, "COLD", 30),
    mk("cold-sale-3d-tiebreak-hot", { sale_date: day(3) }, "HOT", 5),
    mk("warm-no-date", {}, "WARM", 80),
  ];
  const val = (it) => S.deadlineSortValue(S.leadClock(it.l, NOW.getTime()), it.tier, it.grade);
  const order = items.slice().sort((a, b) => val(b) - val(a)).map((i) => i.name);
  assert.deepEqual(order, [
    "cold-sale-3d-tiebreak-hot",   // 3 days, HOT beats the COLD one on the same day
    "cold-sale-3d",
    "hot-sale-10d",
    "hot-no-date",                 // group 2: no live deadline in the horizon, by tier then grade
    "warm-no-date",
    "warm-stayed-2d",              // a stayed sale cannot lead the queue
    "cold-redemption-200d",
    // group 1: demoted, whatever the tier
    order[7], order[8],
  ]);
  assert.deepEqual(order.slice(7).sort(), ["hot-passed-12d", "hot-withdrawn-future-sale"]);
});

// ---------------------------------------------------------------------------
// F3: bankruptcy stay
test("F3: a stayed foreclosure says SALE STAYED with the chapter, from the stored block", () => {
  const S = load();
  const l = lead({ sale_date: day(5), raw: {
    bankruptcy: { chapter: "13", date_filed: "2025-11-01" },
    bankruptcy_stay: { status: "stayed", chapter: "13", date_filed: "2025-11-01", months_since_filing: 2, resume_risk: "moderate", note: "n" },
  } });
  const st = S.bankruptcyStay(l, NOW.getTime());
  assert.equal(st.label, "SALE STAYED (bankruptcy chapter 13)");
  assert.equal(st.fromStored, true);
  assert.equal(st.resumeRisk, "elevated");                  // filed ~10.7 months before 2026-09-21: recomputed, not the stored 2
  const lines = S.stayLines(st, NOW.getTime()).join(" ");
  assert.match(lines, /automatic stay/);
  assert.match(lines, /Resume risk: elevated/);
  assert.match(lines, /name match/);
  const ck = S.leadClock(l, NOW.getTime());
  assert.equal(ck.group, 2);                                // not group 3 despite 5 days to sale
  assert.ok(S.clockBadges(l, ck, NOW.getTime()).some((b) => b.text === "SALE STAYED (bankruptcy chapter 13)"));
});

test("F3: slim carries raw.bankruptcy but not bankruptcy_stay; the stay is derived and labelled", () => {
  const S = load();
  const l = lead({ listing_type: "lis_pendens", raw: { bankruptcy: { chapter: "7", date_filed: "2026-08-01" } } });
  const st = S.bankruptcyStay(l, NOW.getTime());
  assert.equal(st.label, "SALE STAYED (bankruptcy chapter 7)");
  assert.equal(st.fromStored, false);
  assert.equal(st.resumeRisk, "high");
  assert.match(S.stayLines(st, NOW.getTime()).join(" "), /stay record itself has not loaded/);
  assert.equal(S.bankruptcyStay(lead({ listing_type: "?", raw: { bankruptcy: { chapter: "?" } } }), NOW.getTime()), null);
});

test("F3: a bankruptcy on a non-foreclosure lead, or the bankruptcy source itself, is not a stay", () => {
  const S = load();
  assert.equal(S.bankruptcyStay(lead({ listing_type: "probate_notice", raw: { bankruptcy: { chapter: "13" } } }), NOW.getTime()), null);
  assert.equal(S.bankruptcyStay(lead({ source: "national.courtlistener_bankruptcy", listing_type: "bankruptcy", raw: { bankruptcy: { chapter: "13" } } }), NOW.getTime()), null);
  assert.equal(S.bankruptcyStay(lead(), NOW.getTime()), null);
});

// ---------------------------------------------------------------------------
// F13
test("F13: the signal chip counts distinct categories, never facet synonyms", () => {
  const S = load();
  // One tax delinquency reads as three signal names but ONE category.
  const one = lead({ raw: { distress_stack: { stack: 1, categories: ["FINANCIAL"], signals: ["recorded_debt", "tax_lien", "tax_sale"] }, signal_stack: { count: 3 } } });
  assert.equal(S.distressCategories(one).n, 1);
  const two = lead({ raw: { distress_stack: { stack: 2, categories: ["FINANCIAL", "PROPERTY"], signals: ["tax_lien", "code_enforcement"] } } });
  assert.equal(S.distressCategories(two).n, 2);
  assert.deepEqual(plain(S.distressCategories(two).cats), ["FINANCIAL", "PROPERTY"]);
  // Duplicates in the categories array do not inflate it.
  assert.equal(S.distressCategories(lead({ raw: { distress_stack: { categories: ["FINANCIAL", "FINANCIAL"] } } })).n, 1);
  // No categories array: fold signal names onto categories, then fall back to stack.
  assert.equal(S.distressCategories(lead({ raw: { distress_stack: { signals: ["tax_lien", "tax_sale", "recorded_debt", "probate"] } } })).n, 2);
  assert.equal(S.distressCategories(lead({ raw: { distress_stack: { stack: 3 } } })).n, 3);
  assert.equal(S.distressCategories(lead()).n, 0);
});

test("F6/F13: signals carry their evidence class, and name matches are labelled as such", () => {
  const S = load();
  const ds = { signals: ["foreclosure_sale", "incarceration", "bankruptcy", "probate"] };
  const sigs = S.stackSignals(ds, {});
  assert.equal(sigs.find((s) => s.name === "incarceration").kind, "name_only");
  assert.equal(sigs.find((s) => s.name === "bankruptcy").kind, "name_only");
  // The scorer stores only the exceptions: an absent evidence entry means record.
  assert.equal(sigs.find((s) => s.name === "foreclosure_sale").kind, "record");
  assert.equal(sigs.find((s) => s.name === "foreclosure_sale").carried, false);
  assert.match(S.signalTipText(sigs), /incarceration \(name match\)/);
  assert.match(S.signalTipText(sigs), /foreclosure sale \(record\)/);
  // Object-shaped signals with an evidence field, and an evidence map on the stack.
  const carried = S.stackSignals({ signals: [
    { name: "foreclosure_sale", category: "FINANCIAL", weight: 30, evidence: "record" },
    { name: "probate", evidence_class: "name-joined" },
  ] }, {});
  assert.equal(carried[0].kind, "record");
  assert.equal(carried[0].carried, true);
  assert.equal(carried[1].kind, "name_joined");
  assert.match(S.signalTipText(carried), /probate \(name match\)/);           // name_joined reads as a name match
  const mapped = S.stackSignals({ signals: ["divorce"], evidence: { divorce: "name_only" } }, {});
  assert.equal(mapped[0].kind, "name_only");
  assert.match(S.signalTipText(carried), /foreclosure sale \(record\)/);
  // Array-shaped [name, category, weight] entries still work.
  assert.equal(S.stackSignals({ signals: [["tax_lien", "FINANCIAL", 20]] }, {})[0].weight, 20);
  // Court divorce is only called a name match when the court block is there.
  assert.equal(S.stackSignals({ signals: ["divorce"] }, {})[0].kind, "record");
  assert.equal(S.stackSignals({ signals: ["divorce"] }, { divorce: { case_count: 1 } })[0].kind, "name_only");
});

test("name matches are listed wherever a lead leans on one, and only then", () => {
  const S = load();
  const l = lead({ raw: {
    bankruptcy: { chapter: "13" }, incarceration: { name: "x" },
    divorce: { case_count: 2, match: "unverified" }, name_resolution: { matched_owner: "DOE JOHN", method: "owner_search" },
  } });
  const keys = plain(S.nameMatchList(l).map((m) => m.key));
  assert.deepEqual(keys.sort(), ["bankruptcy", "divorce", "incarceration", "name_resolved"]);
  for (const m of S.nameMatchList(l)) assert.match(m.short + " " + m.detail, /name|owner/i);
  // Slim: only the stack's signal names are there.
  const slim = lead({ raw: { distress_stack: { signals: ["incarceration", "tax_lien"] } } });
  assert.deepEqual(plain(S.nameMatchList(slim).map((m) => m.key)), ["incarceration"]);
  assert.deepEqual(plain(S.nameMatchList(lead({ raw: { distress_stack: { signals: ["tax_lien"] } } }))), []);
  // The bankruptcy SOURCE lead is the filing itself, not a name match onto a property.
  assert.deepEqual(plain(S.nameMatchList(lead({ source: "national.courtlistener_bankruptcy", raw: { bankruptcy: { chapter: "7" } } }))), []);
});

// ---------------------------------------------------------------------------
// F19
test("F19: equity carries its basis and is hidden when the trust gate refuses", () => {
  const S = load();
  const eq = (o) => lead({ raw: { equity: { value: 80000, pct: 0.4, ...o } } });
  const recorded = S.equityView(eq({ payoff_source: "recorded_deed_of_trust", confidence: "high" }), { level: "ok" });
  assert.equal(recorded.shown, true);
  assert.equal(recorded.basis, "recorded");
  assert.equal(recorded.label, "from recorded debt, high confidence");
  const judgment = S.equityView(eq({ payoff_source: "amount_owed:judgment", confidence: "medium" }), { level: "ok" });
  assert.equal(judgment.basis, "recorded");
  const est = S.equityView(eq({ payoff_source: "assessed_value_estimate", confidence: "low" }), { level: "ok" });
  assert.equal(est.basis, "estimated");
  assert.equal(est.label, "estimated, low confidence");
  assert.equal(S.equityView(eq({ payoff_source: "foreclosure_proxy:opening_bid", confidence: "low" }), { level: "weak" }).basis, "estimated");
  // Trust gate.
  assert.equal(S.equityView(eq({ payoff_source: "recorded_deed_of_trust" }), { level: "bad" }).shown, false);
  assert.equal(S.equityView(eq({ payoff_source: "recorded_deed_of_trust" }), { level: "bad" }).why, "arv_trust");
  assert.equal(S.equityView(eq({ payoff_source: "x" }), { level: "ok", absent: "withheld" }).shown, false);
  // A withheld block carries no value.
  const w = S.equityView(lead({ raw: { equity: { withheld: true, withheld_reason: "why" } } }), { level: "ok" });
  assert.equal(w.shown, false);
  assert.equal(w.reason, "why");
  assert.equal(S.equityView(lead(), { level: "ok" }).shown, false);
});

// ---------------------------------------------------------------------------
// F8
test("F8: property address says so plainly when there is none", () => {
  const S = load();
  assert.deepEqual({ ...S.propertyAddress(lead({ street_address: "12 Oak St", city: "Boiling Springs", state: "SC", zip_code: "29316" })) },
    { has: true, text: "12 Oak St, Boiling Springs, SC, 29316", fallback: "" });
  const none = S.propertyAddress(lead({ street_address: "  ", county: "Cherokee", state: "SC", parcel_id: "123-4" }));
  assert.equal(none.has, false);
  assert.equal(none.text, "no property address");
  assert.equal(none.fallback, "Cherokee County · SC · parcel 123-4");
  assert.equal(S.propertyAddress(lead({ street_address: null })).text, "no property address");
});

// ---------------------------------------------------------------------------
// Freshness banner
test("freshness: absent fields degrade gracefully, and over 48 hours is stale", () => {
  const S = load();
  const now = NOW.getTime();
  const iso = (hoursAgo) => new Date(now - hoursAgo * 3600000).toISOString();
  // Nothing at all.
  const none = S.dataFreshness({}, now);
  assert.equal(none.known, false);
  assert.equal(none.stale, false);
  assert.equal(S.dataFreshness(null, now).known, false);
  // Board fresh, no health fields: not stale, health unknown.
  const a = S.dataFreshness({ run_time: iso(3) }, now);
  assert.equal(a.known, true);
  assert.equal(a.stale, false);
  assert.equal(a.health, null);
  assert.ok(Math.abs(a.board.ageHours - 3) < 0.01);
  // health_as_of drives health.
  const b = S.dataFreshness({ run_time: iso(1), health_as_of: iso(50) }, now);
  assert.equal(b.health.source, "health_as_of");
  assert.equal(b.stale, true);
  assert.match(b.reasons.join(" "), /source health is 2\.1 days old/);
  // health_age_hours is frozen at write time, so time since run_time is added.
  const c = S.dataFreshness({ run_time: iso(30), health_age_hours: 20 }, now);
  assert.equal(c.health.source, "health_age_hours");
  assert.ok(Math.abs(c.health.ageHours - 50) < 0.01);
  assert.equal(c.stale, true);
  const d = S.dataFreshness({ run_time: iso(2), health_age_hours: 10 }, now);
  assert.equal(d.stale, false);
  // health_carried_from is the field that exists today.
  const e = S.dataFreshness({ run_time: iso(1), health_carried_from: iso(60) }, now);
  assert.equal(e.health.source, "health_carried_from");
  assert.equal(e.stale, true);
  // The board itself being old is stale too, and microsecond timestamps parse.
  const f = S.dataFreshness({ run_time: "2026-09-10T14:11:32.810745Z" }, now);
  assert.equal(f.stale, true);
  assert.match(f.reasons.join(" "), /the board was built/);
  assert.equal(S.fmtAgeHours(0.2), "under 1h");
  assert.equal(S.fmtAgeHours(5), "5h");
  assert.equal(S.fmtAgeHours(72), "3.0 days");
  assert.equal(S.fmtAgeHours(NaN), "unknown age");
});

// ---------------------------------------------------------------------------
// Static wiring: things that must stay true of the shipped files.
const codeOnly = (src) => src.split("\n").filter((ln) => !/^\s*(\/\/|\*|\/\*)/.test(ln)).join("\n");

test("no code reads the frozen counters (F15); only the slim allowlist names them", () => {
  const code = codeOnly(JS);
  assert.equal((code.match(/\.days_remaining\b/g) || []).length, 0, "a .days_remaining read is back");
  assert.equal((code.match(/\.sale_date_passed(_days)?\b/g) || []).length, 0, "a stored sale_date_passed counter is read again");
  // The one legal .in_window read is the veto inside upsetBidState.
  assert.equal((code.match(/\.in_window\b/g) || []).length, 1);
  assert.match(code, /ub\.in_window !== true/);
});

test("stageOf no longer keys off the mere presence of raw.upset_bid", () => {
  const body = JS.slice(JS.indexOf("function stageOf"), JS.indexOf("function updateStageCounts"));
  assert.doesNotMatch(body, /\(l\.raw && l\.raw\.upset_bid\)\) return/);
  assert.match(body, /upsetBidState\(l, Date\.now\(\)\)\.open/);
});

test("the slim allowlist is untouched (tests/test_board_slim.py pins it against web_artifact.py)", () => {
  for (const name of ["_LEAN_TOP", "_LEAN_RAW", "_LEAN_RAW_SCALARS"]) assert.ok(JS.includes(`const ${name} = `), name);
});

test("index.html: cache-bust bumped, banner, clock panel and deadline sort are wired", () => {
  const m = /dashboard\.js\?v=(\d+[a-z]?)/.exec(HTML);
  assert.ok(m, "dashboard.js has no ?v= cache-bust");
  assert.notEqual(m[1], "20260913a", "the ?v= was not bumped");
  assert.ok(/id="freshness-banner"/.test(HTML));
  assert.ok(/id="d-clock"/.test(HTML));
  assert.ok(/<option value="_deadline">Deadline first<\/option>/.test(HTML));
  assert.match(JS, /let sortKey = "_deadline"/);
});

test("the legacy high_equity chip is gated behind the vetted equity block", () => {
  assert.match(JS, /f !== "high_equity" \|\| \(_evGate\.shown && _evGate\.basis === "recorded"\)/);
  // ...and the bottom flags list uses the same filtered array, not raw `flags`.
  assert.match(JS, /\$\("d-flags"\)\.innerHTML = _flagsShown/);
});

// ---------------------------------------------------------------------------
test("a filing date is not a sale: liensnc and nc_sos_ucc rows never count as a sale date that passed", () => {
  // ingest_all maps the lien FILING date into sale_date so the row survives the dateless filter.
  // 46,989 liensnc rows would otherwise all read "sale date passed" and drop to the bottom.
  const S = load();
  const l = lead({ listing_type: "tax_lien", source: "counties_generic.liensnc", sale_date: day(-31) });
  const ck = S.leadClock(l, NOW.getTime());
  assert.equal(ck.sale.has, false);
  assert.equal(ck.salePassed, false);
  assert.equal(S.leadClock(lead({ source: "national.nc_sos_ucc", sale_date: day(-40) }), NOW.getTime()).salePassed, false);
  // a real foreclosure sale in the past still passes
  assert.equal(S.leadClock(lead({ sale_date: day(-5) }), NOW.getTime()).salePassed, true);
});

// ---------------------------------------------------------------------------
// Scorer handoff (docs/handoff_scorer_to_others_2026-09-21.md section 3)
test("handoff 2: the tier tooltip reports every field the scorer adds to distress_stack", () => {
  const S = load();
  const NOWMS = NOW.getTime();
  const full = lead({ raw: { distress_stack: {
    tier: "WARM", score: 44, signals: ["foreclosure_sale", "incarceration", "probate", "price_cut"],
    evidence: { incarceration: "name_only", probate: "name_joined", price_cut: "inferred" },
    stale_reason: "tax_sale: sale date 2026-01-02 passed 262 days ago, no open upset-bid window or redemption",
    stay: { status: "stayed", chapter: "13", resume_risk: "moderate", case: "25-1" },
    lane: "foreclosure", days_to_event: 5, bidder: true, title_status: "junior_risk",
    equity_evidenced: false, uncounted_categories: ["LEGAL", "LIFE_EVENT"],
  } } });
  const lines = S.stackTooltip(full, NOWMS, null).split("\n");
  assert.equal(lines[0], "foreclosure sale (record), incarceration (name match), probate (name match), price cut (inferred); score 44");
  assert.ok(lines.includes("event ended: tax_sale: sale date 2026-01-02 passed 262 days ago, no open upset-bid window or redemption"));
  assert.ok(lines.includes("foreclosure stayed by Chapter 13 bankruptcy, resume risk moderate"));
  assert.ok(lines.includes("foreclosure lane: sale in 5 days"));
  assert.ok(lines.includes("title: junior-lien risk, a senior lien may survive the sale"));
  assert.ok(lines.includes("equity estimated"));
  assert.ok(lines.includes("legal, life-event not counted toward the stack"));
});

test("handoff 2: nothing is shown for a field the stack does not carry", () => {
  const S = load();
  const plain = lead({ raw: { distress_stack: { tier: "WARM", score: 30, signals: ["tax_lien"] } } });
  assert.equal(S.stackTooltip(plain, NOW.getTime(), null), "tax lien (record); score 30");
  assert.equal(S.stackTooltip(lead(), NOW.getTime(), null), "");
  // equity_evidenced true, or absent, says nothing; title_status only on a bidder lead
  const l = lead({ raw: { distress_stack: { signals: ["tax_lien"], score: 1, equity_evidenced: true, title_status: "missing" } } });
  assert.equal(S.stackTooltip(l, NOW.getTime(), null), "tax lien (record); score 1");
  const b = lead({ raw: { distress_stack: { signals: ["foreclosure_sale"], score: 30, bidder: true, title_status: "clean" } } });
  assert.match(S.stackTooltip(b, NOW.getTime(), null), /title: the foreclosing lien is senior/);
  const m = lead({ raw: { distress_stack: { signals: ["foreclosure_sale"], score: 30, bidder: true, title_status: "missing" } } });
  assert.match(S.stackTooltip(m, NOW.getTime(), null), /title: not checked/);
  // a stay without a chapter, and a lane lead with the event today
  const st = lead({ raw: { distress_stack: { signals: ["foreclosure_sale"], score: 1, stay: { status: "stayed", chapter: "?" }, lane: "foreclosure", days_to_event: 0 } } });
  const t = S.stackTooltip(st, NOW.getTime(), null);
  assert.match(t, /foreclosure stayed by a bankruptcy$/m);
  assert.match(t, /foreclosure lane: sale today/);
});

test("handoff 2: days_to_event is aged by the days since the board was scored, and dropped when past", () => {
  const S = load();
  const NOWMS = NOW.getTime();
  const twoDaysAgo = new Date(2026, 8, 19, 3, 0, 0).getTime();
  const l = lead({ raw: { distress_stack: { signals: ["foreclosure_sale"], score: 1, lane: "foreclosure", days_to_event: 5 } } });
  assert.match(S.stackTooltip(l, NOWMS, twoDaysAgo), /foreclosure lane: sale in 3 days/);
  assert.match(S.stackTooltip(l, NOWMS, new Date(2026, 8, 16).getTime()), /^foreclosure lane: sale today$/m);       // exactly 5 days ago
  assert.doesNotMatch(S.stackTooltip(l, NOWMS, new Date(2026, 8, 10).getTime()), /foreclosure lane/);              // it has passed
  // not in the lane: days_to_event is a next-event note, not "sale"
  const d = lead({ raw: { distress_stack: { signals: ["tax_lien"], score: 1, days_to_event: 9 } } });
  assert.match(S.stackTooltip(d, NOWMS, null), /next event in 9 days/);
});

test("handoff 4: a foreclosure-lane lead sorts by the scorer's days_to_event when its dates say nothing", () => {
  const S = load();
  const NOWMS = NOW.getTime();
  const lane = (n, extra = {}) => lead({ state: "SC", ...extra, raw: { distress_stack: { tier: "WARM", lane: "foreclosure", days_to_event: n }, ...(extra.raw || {}) } });
  const a = S.leadClock(lane(4), NOWMS);
  assert.equal(a.live.kind, "event");
  assert.equal(a.live.days, 4);
  assert.equal(a.group, 3);
  assert.equal(S.clockPill(a.live).strip, "SALE EVENT IN 4 DAYS");
  assert.equal(a.live.date, "2026-09-25T00:00:00");
  // aged to today: scored two days ago, so 2 left; scored six days ago, so it has passed
  assert.equal(S.leadClock(lane(4), NOWMS, new Date(2026, 8, 19).getTime()).live.days, 2);
  assert.equal(S.leadClock(lane(4), NOWMS, new Date(2026, 8, 15).getTime()).live, null);
  // the soonest of the candidates wins: a sale in 10 days and an event in 4
  const both = S.leadClock(lane(4, { sale_date: day(10) }), NOWMS);
  assert.equal(both.live.kind, "event");
  const sooner = S.leadClock(lane(9, { sale_date: day(3) }), NOWMS);
  assert.equal(sooner.live.kind, "sale");
  // fullmer carries the same two fields
  const fm = S.leadClock(lead({ state: "SC", raw: { fullmer: { lane: "foreclosure", days_to_event: 7 } } }), NOWMS);
  assert.equal(fm.live.days, 7);
  // NOT the foreclosure lane: days_to_event is ignored
  assert.equal(S.leadClock(lead({ state: "SC", raw: { distress_stack: { days_to_event: 3 } } }), NOWMS).live, null);
  assert.equal(S.leadClock(lead({ state: "SC", raw: { distress_stack: { lane: "distressed", days_to_event: 3 } } }), NOWMS).live, null);
  // a presumed-withdrawn lead has no clock, scorer's or not
  assert.equal(S.leadClock(lane(4, { auction_status: "presumed_withdrawn" }), NOWMS).live, null);
  // the pill and the sort use it: lane leads order by days ascending, ahead of a lead with no clock
  const val = (l) => S.deadlineSortValue(S.leadClock(l, NOWMS), "WARM", 50);
  const order = [lane(20), lane(2), lead({ state: "SC", raw: { distress_stack: { tier: "HOT" } } }), lane(9)]
    .map((l, i) => [i, val(l)]).sort((x, y) => y[1] - x[1]).map((x) => x[0]);
  assert.deepEqual(order, [1, 3, 0, 2]);
});

test("handoff 3: the stay ends at the filing TTL (270 days chapter 7, 1,095 otherwise): no banner when lapsed", () => {
  const S = load();
  const NOWMS = NOW.getTime();
  const filed = (ago) => { const d = new Date(2026, 8, 21 - ago); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const mk = (chapter, ago, extra = {}) => lead({ sale_date: day(5), raw: { bankruptcy: { chapter, date_filed: filed(ago) }, ...extra } });
  assert.equal(S.bankruptcyStay(mk("7", 200), NOWMS).resumeRisk, "high");
  assert.equal(S.bankruptcyStay(mk("7", 271), NOWMS), null);                 // 270 days: lapsed
  assert.equal(S.bankruptcyStay(mk("7", 270), NOWMS).chapter, "7");          // day 270 itself is still in force
  assert.equal(S.bankruptcyStay(mk("13", 1000), NOWMS).chapter, "13");
  assert.equal(S.bankruptcyStay(mk("13", 1096), NOWMS), null);
  assert.equal(S.bankruptcyStay(mk("", 1096), NOWMS), null);                 // chapter unknown uses the long TTL
  assert.equal(S.bankruptcyStay(mk("", 900), NOWMS).chapter, "");
  assert.equal(S.BK_TTL_DAYS_CH7, 270);
  assert.equal(S.BK_TTL_DAYS_OTHER, 1095);
  // a stored stay block lapses too, and a lapsed one leaves the sale a live, un-demoted lead
  const stored = mk("7", 400, { bankruptcy_stay: { status: "stayed", chapter: "7", date_filed: filed(400), resume_risk: "high" } });
  assert.equal(S.bankruptcyStay(stored, NOWMS), null);
  const ck = S.leadClock(stored, NOWMS);
  assert.equal(ck.stay, null);
  assert.equal(ck.group, 3);
  assert.ok(!S.clockBadges(stored, ck, NOWMS).some((b) => b.kind === "stay"));
  // no filing date to measure: not lapsed
  assert.equal(S.bankruptcyLapsed({ chapter: "7" }, NOWMS), false);
  assert.equal(S.bankruptcyLapsed(null, NOWMS), false);
  assert.equal(S.bankruptcyLapsed({ date_filed: "garbage", chapter: "7" }, NOWMS), false);
});

test("handoff 3: slim carries distress_stack.stay, so the stay shows with its resume risk without the stay block", () => {
  const S = load();
  const NOWMS = NOW.getTime();
  const l = lead({ sale_date: day(5), raw: {
    bankruptcy: { chapter: "13", date_filed: "2026-03-01" },                     // slim projection of the filing
    distress_stack: { tier: "WARM", stay: { status: "stayed", chapter: "13", resume_risk: "moderate", case: "26-1" } },
  } });
  const st = S.bankruptcyStay(l, NOWMS);
  assert.equal(st.source, "scorer");
  assert.equal(st.fromStored, true);
  assert.equal(st.label, "SALE STAYED (bankruptcy chapter 13)");
  assert.equal(st.resumeRisk, "moderate");                                       // 6.7 months: not yet elevated
  assert.match(S.stayLines(st, NOWMS).join(" "), /scorer's own/);
  // the scorer's stay with no filing date on the row still shows (nothing to lapse)
  const nodate = lead({ raw: { distress_stack: { stay: { status: "stayed", chapter: "7", resume_risk: "high" } } } });
  assert.equal(S.bankruptcyStay(nodate, NOWMS).resumeRisk, "high");
  // the stay block outranks it, and the scorer's stay is not consulted on a non-stayed block
  assert.equal(S.bankruptcyStay(lead({ raw: { bankruptcy_stay: { status: "stayed", chapter: "7", date_filed: "2026-08-01" }, distress_stack: { stay: { chapter: "13" } } } }), NOWMS).source, "stay_block");
});

test("evidence-driven name-match chips: a scorer name_only / name_joined signal is listed, once", () => {
  const S = load();
  const l = lead({ raw: { distress_stack: { signals: ["probate", "incarceration", "tax_lien"], evidence: { probate: "name_joined", incarceration: "name_only" } } } });
  const keys = plain(S.nameMatchList(l).map((m) => m.key));
  assert.deepEqual(keys.sort(), ["incarceration", "signal:probate"]);
  assert.match(S.nameMatchList(l).find((m) => m.key === "signal:probate").short, /probate · name match/);
  // an inferred signal is not a name match
  assert.deepEqual(plain(S.nameMatchList(lead({ raw: { distress_stack: { signals: ["price_cut"], evidence: { price_cut: "inferred" } } } }))), []);
});

test("liensnc / nc_sos_ucc sale_date is a FILING date: never a sale that passed, never a sale-stage lead", () => {
  const S = load();
  const NOWMS = NOW.getTime();
  for (const source of ["liensnc", "counties_generic.liensnc", "national.nc_sos_ucc"]) {
    const l = lead({ source, listing_type: "tax_lien", sale_date: day(-40) });
    assert.equal(S.saleClock(l, NOWMS).has, false, source);
    const ck = S.leadClock(l, NOWMS);
    assert.equal(ck.salePassed, false, source);
    assert.ok(!S.clockBadges(l, ck, NOWMS).some((b) => b.kind === "sale_passed"), source);
    // a filing yesterday is not a sale in the last two weeks, so not the foreclosure stage
    assert.equal(S.stageOf(lead({ source, listing_type: "tax_lien", sale_date: day(-1) })), "outbound", source);
  }
  // a real source with the same dates still is
  assert.equal(S.saleClock(lead({ sale_date: day(-40) }), NOWMS).passed, true);
  assert.equal(S.stageOf(lead({ listing_type: "tax_lien", source: "counties_nc.some_tax", sale_date: day(-1) })), "foreclosure");
});

test("wiring: chip text, badge tooltip and panel use the new pieces", () => {
  assert.match(JS, /🔥 \$\{dc\.n\} distress categories<\/span>/);
  assert.doesNotMatch(JS, /signal types<\/span>/);
  assert.match(JS, /function stackTipText\(l\) \{ return stackTooltip\(l, Date\.now\(\), _scoredAtMs\(\)\); \}/);
  assert.match(JS, /distressBadge\(ds, l\)/);
  assert.match(JS, /leadClock\(l, now, _scoredAtMs\(\)\)/);
  assert.match(JS, /class="stack-notes"/);
  assert.match(JS, /stay lapsed/);
  assert.match(HTML, /Min distress categories/);
});
