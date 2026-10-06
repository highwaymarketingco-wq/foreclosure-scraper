# Operator manual: manual steps, verification coverage, and paywalls (2026-10-04)

One reference answering three linked questions: what you personally do by hand
for CAPTCHA-walled leads, what "100% verified" actually means and how much of
it is automated today, and what in this project is genuinely paywalled versus
some other kind of wall. Compiled by reading the actual current code and docs
listed under each section — not from memory notes, which this doc
cross-checked and in a few places corrects.

---

## 1. The manual CAPTCHA-verification walkthrough (step by step)

**What this is for:** two kinds of leads — `probate_notice`/`estate_lead` NC
rows (checking for undiscovered heirs, the "Boone St" pattern) and
`lis_pendens`/`foreclosure_sale`/`divorce_notice`/`sheriff_sale`/`auction` NC
rows (checking the underlying NC eCourts case) — where the one remaining fact
you'd want lives behind NC eCourts Smart Search's CAPTCHA or NC Secretary of
State's bot-check. Nothing in this codebase solves either challenge. This
tool queues the check, puts the real search in front of you, and waits.

**Built in:** `src/foreclosure_scraper/verification_human_lane.py` (the logic)
and `scripts/verify_lead_human_assisted.py` (what you actually run). Shipped
commit `60289671`, documented in `docs/HANDOFF.md` item 61. Scope is hard-
coded and will refuse anything else: NC rows only, and only the listing types
named above — a South Carolina row or any other `listing_type` gets an
"OUT OF SCOPE" message and a clean exit, not a guess.

### Prerequisites
- You're in the repo root (`~/foreclosure-scraper` or wherever it's checked
  out) with `uv` available (`uv run python ...` is how every command below is
  invoked — matches the script's own usage docstring).
- You know at least one identifying fact about the lead: its parcel ID, its
  `source_url`, its case number (plus county), or its street address. The
  tool refuses to run with zero identifiers rather than silently grabbing the
  first row on the board.
- A default web browser is configured on the machine (the tool calls
  `webbrowser.open()`).

### Step 1 — queue the check
Run, substituting whatever identifier you have (parcel ID shown here):

```
uv run python scripts/verify_lead_human_assisted.py \
    --parcel-id 9688199972 --county Buncombe
```

What happens:
1. It streams the published board (read-only, no mutation) looking for that
   one row. If nothing matches you get `ERROR: no board row matched those
   identifiers.` and exit code 1 — try a different identifier.
2. It prints what it found to your terminal: address, county/state, listing
   type, case number.
3. It works out exactly which NC eCourts category to use (Estate / Special
   Proceedings for probate, Family/Civil for divorce, Civil for lis
   pendens/foreclosure), and either a case number or a party name to search
   on — printed to your terminal as numbered instructions.
4. **Your browser opens automatically** to the real NC eCourts Smart Search
   portal (`portal-nc.tylertech.cloud`). If the defendant/owner reads as a
   business (an LLC, Inc., etc.), a **second** browser tab/window opens to
   the NC Secretary of State business search too.
5. It writes a placeholder record with `verdict: "wall"` — an honest "queued,
   not yet checked" marker, not a guess — to stdout (or wherever `--out`
   points).

### What you do in the browser (the human part — this tool will never do it)
1. On the NC eCourts page: if a CAPTCHA/image-grid challenge appears, **you
   solve it**. Nothing automated will.
2. Set the Case Category to the one printed in your terminal (Tyler's exact
   label may vary slightly — any close match is fine).
3. Search using whichever the terminal gave you — an exact case number is
   more precise than a name search when you have one.
4. **Click into the actual matching case** and wait for its full detail page
   to load. A bare hit-list row will not show the full party/heir list —
   you need the detail page.
5. Save that page: **Ctrl+S** (or File → Save Page As), choose **"Webpage,
   HTML only."** Note where you saved it — you'll need that exact path next.
6. If a second NC SOS tab opened: same idea — solve its bot-check yourself,
   search the business name shown, wait for the profile page to load, save
   it the same way.

### Step 2 — finish the check
Re-run the **identical** command, adding the path(s) to what you just saved:

```
uv run python scripts/verify_lead_human_assisted.py \
    --parcel-id 9688199972 --county Buncombe \
    --saved-ecourts-page ~/Downloads/case_detail.html \
    --out /tmp/verification_result.json
```

(Add `--saved-sos-page ~/Downloads/sos_profile.html` too if an SOS search
was also queued.)

This time it parses what you saved — reusing the same parser
`scripts/ingest_saved.sh` already runs for every other saved NC eCourts page,
and the same parser the live SOS-lookup lane already uses — and emits a real
`confirmed` / `refuted` / `unconfirmed` verdict (never fabricates a status
the saved page doesn't actually show). For a probate/heir lead specifically,
any party name on the saved page that the board didn't already know about
gets **automatically** run through NC's free voter-file liveness check (no
CAPTCHA on that step — real network I/O, done for you) — this is the "is the
9th heir still alive" check, closing the Boone St pattern end to end.

### What this does NOT do
- It never writes anything back to the live board. The JSON output includes
  a `patch_previews` block showing exactly what a follow-up write script
  *would* apply — nobody has built or run that write step yet. Treat the
  output as a report to read, not something that updates the dashboard.
- It never attempts, solves, or bypasses the CAPTCHA/bot-check under any
  circumstance, confirmed by reading the code: the only thing it does on its
  own initiative besides reading the board is `webbrowser.open(url)` (a bare
  navigation) and the free NC voter-file liveness lookup.

This matches the architecture `docs/validation_2026-10-02/VERIFICATION_PIPELINE_SPEC.md`
section 4 lays out ("option 2," a per-lead on-demand lane, explicitly never a
bulk/background sweep) — confirmed by reading that section directly.

---

## 2. What "100% per listing" means, and what's automated vs. gated vs. missing

**Two separate things are easy to conflate — keep them apart:**

1. **Ordinary scoring/extraction accuracy** — is the `tax_lien`/`divorce`/etc.
   flag on a row actually true. Several of these had real bugs found and
   partly fixed this week (presence-check inflation, name-matching without
   middle-name corroboration, stale statuses). That work is real but it is
   **not** what this section is about.
2. **The `raw.verification` architecture** — a *separate*, far more
   rigorous effort: a live, per-row, re-checkable record
   (`{signal, checked_at, verdict, evidence, source, verifier_version}`)
   proving a specific claim against its real authoritative source, the way
   the "Boone St" lead was manually checked. This is what `VERIFICATION_PIPELINE_SPEC.md`
   defines and what "100% per listing" refers to.

**Update 2026-10-06:** this is no longer true for `tax_lien` (Buncombe): `raw.verification` is
live through `scripts/verification_sweep.py` (Mac) and the VM's apply step, SC divorce is
labelled `wall`, and the human lane writes its verdicts into the same ledger. See
`docs/HANDOFF.md` item 66. The paragraph below describes 2026-10-04.

**Current state of (2), stated plainly: it is not wired into production for
any signal type yet.** The `raw.verification` field does not exist on live
board rows. What exists instead, per signal type, is either (a) a one-off
validator script in `docs/validation_2026-10-02/scripts/` or
`docs/validation_2026-10-03/scripts/` that proved the live endpoint, parsing,
and matching logic work — ready to "evolve" into a `verify_one(row)`
function per the spec's own section 2, but not yet done — or (b), for exactly
two signal families, real importable production code
(`verification_human_lane.py`) that is built but still not wired to board
writes (Section 1 above). Nothing here runs on a schedule, nothing updates
the dashboard yet.

| Signal type | Real-source verifier proven? | Needs the human-CAPTCHA step? | Verdict |
|---|---|---|---|
| `tax_lien` / `two_year_delinquent` | Yes — `validate_tax_lien_buncombe.py` against `tax.buncombenc.gov`, no CAPTCHA. Found only 11.9% real, plus a 1.78x value-bug | No | **(a)** fully automatable, no CAPTCHA anywhere in the path — not yet wired as a live `raw.verification` writer; needs the per-NC/SC-tax-vendor adapter work to go statewide |
| `bankruptcy_stay` | Yes — CourtListener JSON search, no CAPTCHA. Full census (234 rows): only 56% strong name match | No | **(a)** fully automatable — `name_normalize.party_middle_verdict()` is ready to wire into the matching step; not yet a live writer |
| `code_enforcement` / `vacancy` | Yes — county ArcGIS/CityView feeds (Henderson, Gastonia, Asheville checked), no CAPTCHA | No | **(a)** fully automatable per county, but each new county needs its own category taxonomy live-verified first (same work Henderson/Gastonia already got) |
| `builder_distress` | Yes — Buncombe ROD (Cott v4), no CAPTCHA. Replicated **0% real** at N=50 — the underlying signal definition is wrong (Appointment-of-Lien-Agent notices, not actual liens) | No | **(a)** automatable, but pointless to wire as-is — fix or drop the signal definition first; the verifier isn't the gap |
| `jail_booking` | Yes — 10 county jail rosters, no CAPTCHA anywhere. 85.4% still in custody; 12.9% of checkable matches are a different person | No | **(a)** fully automatable; `party_middle_verdict()` not yet wired into the matcher |
| `elderly_disabled` | Yes — tax record + NC voter lookup, no CAPTCHA | No | **(a)** fully automatable; `nc_voter_lookup()` already shipped as reusable code, not yet wired into scoring as a filter |
| `divorce` (SC) | Yes — SC Public Index, no CAPTCHA (58 live searches, 8 counties, zero blocked) | No | **(a)** automatable, but the sampled real-hit rate was **0.0%** — the case-type/attachment logic upstream is wrong, not the access path |
| `divorce` / `lis_pendens` underlying NC case (the Tyler ROA/case-detail page) | No free verifier exists | **Yes** | **(b)** — this is exactly the two-part NC eCourts/SOS wall `verification_human_lane.py` covers (Section 1) |
| `lis_pendens` / `foreclosure_sale` (ROD-level corroboration) | Yes — Buncombe ROD legacy ASP.NET WebForms, no CAPTCHA token enforced. Only 39.4% show real corroboration; 93.9% have a same-surname collision risk | No for the ROD check itself | **(a)** for the ROD corroboration step; **(b)** for the underlying eCourts case status, same as above |
| `probate` / `heir_estate` (death record + transfer pattern + named-heir liveness) | Yes — ROD DEATHS index + NC voter lookup, no CAPTCHA. 81.8% confirmed real death record; 66.7% of named individuals confirmed active/locatable | No for these three checks | **(a)** for death record / transfer-pattern / already-named-heir liveness |
| `probate` / `heir_estate` (discovering an heir the board didn't already know about) | No free verifier — this is the "Boone St" step itself | **Yes** | **(b)** — exactly what `verification_human_lane.py` is scoped to |
| `comps` | Yes — Spatialest record card + ArcGIS live attributes, no CAPTCHA. Already the most accurate signal measured: 83.8–87.5% price-verified, mean delta only 3% | No | **(a)** fully automatable, and already the lowest-priority to re-verify continuously per the spec (it's already good) |

**Net honest answer:** every signal type above either has a proven, no-CAPTCHA
path to a real verifier (nine of ten), or is explicitly scoped into the one
human-assisted lane that exists (`probate`/`heir_estate` heir-discovery and
the `lis_pendens`/`divorce` underlying NC case). None of the nine
no-CAPTCHA ones are actually live as `raw.verification` writers on the board
today — "proven in a sampling script" and "wired into the pipeline" are two
different states, and only the first is true right now for any of them. The
spec is explicit that turning each proven script into pipeline code, with
TTL/incremental/politeness design, belongs to whoever owns `main.py` next —
it is real, scoped, bounded work, not a mystery gap.

---

## 3. What's actually paywalled, and would paying close the gap

A genuine **paywall** means a specific vendor charges money for specific
data. CAPTCHA, login-without-a-public-signup-path, ToS prohibitions, and
"the data structurally doesn't exist" are different kinds of wall and are
called out as such below — several things on the owner's original candidate
list turned out to be one of those instead of a paywall.

### Confirmed genuine paywalls (money would get you something real)

| Source | Wall type | Cost (as documented in this repo) | What paying unlocks | Separate ceiling underneath? |
|---|---|---|---|---|
| **SC Secretary of State — UCC lien search** | Paywall (distinct from SC SoS's *business-entity* search, which is CAPTCHA-walled, not paywalled) | **$5/search** (`docs/HANDOFF.md`, logged 2026-08-20, not re-verified live this pass) | Per-search UCC filing lookups (entity liens) | None known — this would genuinely work if paid per-search |
| **Cott RecordRoom — Rutherford & Polk NC ROD** | Subscriber login (no public free tier) | Not published in this repo's docs | Full ROD index search for those 2 counties | Re-confirmed **PERMANENT, live-verified 2026-09-30** (`docs/HANDOFF.md` item 58) — no free tenant exists, no alternate free path found. Paying would genuinely open these 2 counties' ROD. |
| **Cherokee SC ROD — document images** (Harris AcclaimWeb) | Subscriber/login wall on the *image* tier specifically | Not published in this repo's docs | Scanned deed-of-trust/lien images for Cherokee | The underlying **index** (party names, doc type, dates) may be reachable free via qPublic per `docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md`; only the image view is paywalled. Note AcclaimWeb images generally do not carry sale price as a structured field either way (per user's own prior deed-OCR finding) — paying gets you the scanned page, not necessarily the number you want. |
| **NC Secretary of State — Federal Tax Lien bulk access** | Paywall + ToS (the live search page states scripted/automated searches "are not permitted... use our Data Subscription Services") | Not published anywhere in this repo (no quote on file) | Bulk federal-tax-lien data without the per-search Cloudflare wall | Narrow signal (entity/LLC federal liens only) even if bought — low leverage for this project's scope |
| **PACER** (federal court records) | Paywall | Not quoted in this repo (standard PACER per-page fee, not independently re-verified here) | Full federal docket/document access | **Moot for this project** — CourtListener already provides a free substitute for the bankruptcy signal this would otherwise serve (`docs/HANDOFF.md`) |
| **MLS access** (Canopy / MLS Grid / Upstate SC board, via CoreLogic Trestle) | Paywall **plus a licensing wall** — not purchasable by just paying; requires being a licensed real-estate agent/broker with board membership | `docs/path_to_100.md` (2026-07-02, flagged "verify" throughout): Trestle API **$100–250/mo** + separate per-MLS data-license fees, broker feed **$30/mo** | Live MLS comps, closed-sale price, expired/withdrawn/short-sale listings — genuinely not published anywhere else | Even fully paid, this only reaches properties that pass through MLS — rural/off-market distressed sales still may not be in it |

### Explored paid-vendor options for the big structural gaps (from `docs/path_to_100.md`, dated 2026-07-02 — a cost/ROI analysis the owner commissioned, not something re-verified live in this pass; every price in it carries the source doc's own "(as of 2026, verify)" flag)

This is a different kind of thing than the confirmed walls above: not a wall
the engine hit and got blocked by, but the owner's own standing analysis of
"if we paid for X, what would it buy." Current project policy
(`docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md` rule 1, `docs/HERMES.md`): the
**automated engine stays free-and-public-only, by hard rule** — "the operator
may buy data as a business decision, but the engine does not." So none of
this is wired in or planned to be; it exists purely so the owner can decide.

| Gap | Paid option(s) documented | Cost (per `path_to_100.md`) | Would it reach 100%? |
|---|---|---|---|
| SC heated sqft / beds/baths (free GIS blanks this for many counties) | Realie, ATTOM bulk | Realie Tier 1 **$50/mo** → Tier 3 **$350/mo**; ATTOM bulk backfill **$1,500–5,000 one-time** | **No — hard ceiling even paid.** Four SC counties' qPublic cards (the only place with real sqft) are Cloudflare-walled for bulk; a vendor closes most of the gap but the doc itself says free routes hit ~60-70% and a paid vendor "closes the last third," not literally all of it |
| ARV / comps for low-comp markets (raw land, mobile homes, thin rural markets) | RentCast Growth **$199/mo** / Scale **$449/mo**, HouseCanary BPO ~$5/report | ~$200–450/mo blended | **No.** The doc is explicit: "raw land, mobile homes, and micro-markets with <3 nearby arms-length sales have no comp basis at *any* price" — RentCast/ATTOM/HouseCanary all thin out there too. Legitimately stays MEDIUM/LOW confidence regardless of spend |
| Personal phone / skip-trace (free ceiling ~21%) | BatchData, PropertyRadar, Melissa, PropStream | BatchData Growth **$1,000/mo**; PropStream Pro **$199/mo** | **Partial at best.** Gets you to a realistic ~70–75% reachable, per the doc's own estimate — not 100%, and several vendors (TLO/Accurint) are themselves credentialing-gated (DPPA/GLBA permissible-purpose), not just priced |
| Open liens / mortgage principal / payoff | CoreLogic Involuntary Lien API ($11.50/call), ATTOM (~$500/mo), DataTree/First American | Varies, see table above | **No for true payoff.** Even paid vendors return *origination* balance or an *estimated* open lien, never the live servicer payoff figure — that's PII the servicer alone holds, genuinely absent from every vendor, paid or not |
| SC sale price on exempt deeds | ATTOM (pulls SC price from deed recorders, not the assessor) | ATTOM entry ~$95–500/mo | **No, not for the exempt-deed slice specifically.** SC §12-24-70 means an exempt deed (foreclosure, deed-in-lieu, estate — exactly this project's targets) legally records **no consideration at all**. ATTOM can't buy a number that was never recorded. The doc states this outright: "true 100% on the *distressed* SC slice is structurally impossible." |

### The genuinely non-paywall ceilings (payment of any kind would not help)

Confirmed current across `docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md` section
4 ("ABSENT") and `docs/HERMES.md` section 12 — these are **not** paywalls:

- **SC deed sale price on exempt deeds** — SC §12-24-70 states no value;
  statutory, not a vendor's business decision.
- **NC power-of-sale debt $** — the statute governing the Notice of Sale
  only requires terms/deposit/upset bid, never the underlying debt figure.
  No recorder, free or paid, has ever been given this number to sell.
- **SC magistrate eviction rosters** — no free *or* paid bulk feed exists;
  the only routes are a FOIA to the Chief Magistrate or an LSC data-share.
- **Live mortgage payoff balance** — servicer-held PII, not sold by anyone.
- **SC Family Court divorce** — a separate access-restricted court system,
  not on the public portal at all; paid court-data vendors (UniCourt,
  Trellis) are the only route this repo has found, and that's a licensing
  relationship, not a simple per-record purchase.
- **Structured investor buy-box feed** — doesn't exist as a feed, free or
  paid, anywhere; has to be built by hand as a curated registry (already
  done, per the user's own memory notes).

### Re-checked live (as requested) and found to have *changed* since older notes

- **SCDOT `SC_Parcels`** — still token-walled (re-confirmed 2026-09-30,
  `docs/walls_register.md`), but this is **not a conventional paywall at
  all**: it's an ArcGIS Enterprise Portal restricted to SCDOT's own internal
  sign-in, with no public self-service signup path found. There may be no
  product to buy here even if the owner wanted to pay — the workaround
  already in production is free county-native GIS layers, now covering 8 of
  11 in-scope SC counties directly.
- **PublicIndex (SC courts)** — a ToS + CAPTCHA wall on *bulk/automated*
  querying, not a cost wall. The portal itself is free to use by hand
  (Rule 610 governs it, not a subscription fee); the manual per-case save
  lane already in production is the correct and sufficient answer, not a
  reason to pay anyone.
- **AcclaimWeb** — confirmed to be two different things depending on
  county/tier: a free index in some places, a paid image tier in others
  (Cherokee specifically); not a blanket paywall across the platform.

### Bottom line on question 3

Paying for something would close a small number of specific, real gaps (2 NC
ROD counties via Cott RecordRoom being the clearest one; SC SoS UCC search at
$5/hit being the cheapest one). It would **meaningfully narrow but not close**
the big structural gaps (phone/skip-trace, SC sqft, comps in thin markets,
open liens) — the project's own cost analysis says so in its own numbers.
And for a specific, named set of data points (SC exempt-deed price, NC
power-of-sale debt, live mortgage payoff, SC magistrate evictions, SC family
court divorce, a structured buy-box feed), **no amount of money buys them**
because the data either was never recorded by statute, is held as PII by a
party that doesn't sell it, or sits in a system no vendor has licensed.
"100%" is not purchasable; the project's own engineering notes already say
this plainly, and this review found nothing to contradict it.
