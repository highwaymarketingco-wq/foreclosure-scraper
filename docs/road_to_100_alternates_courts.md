# Road to 100 — free/manual alternates for the COURT-DATA walls

The hypothesis this doc tests, per wall: *a walled court portal usually exposes
the same filing through a free public side channel.* For NC and SC that side
channel is the **statutorily-mandated legal notice** — foreclosure, estate and
tax filings must be PUBLISHED in a newspaper, and both state press associations
aggregate those notices into a free, county-filterable search. Divorce is the
one filing that is not published, and it is the one wall with no free alternate.

Written 2026-08-12. Liveness probed the same day. No board writes; read-only +
two-probe liveness checks only. This maps each wall to its alternate; it does
not re-derive the walls (see `gap_ledger.md`, `case_type_code_map.md`,
`SOURCE_REGISTER.md`, `ROD_PORTAL_ACCESS.md`).

Legend: **LIVE** = probed 2026-08-12, responds and carries the signal ·
**BUILT** = a wired scraper already produces rows · **MANUAL** = operator
save-and-ingest, no compliant scraper · **WALL** = no free path found, reason
stated.

---

## The two anchor portals (both fill multiple walls)

### ncnotices.com — NC Press Association public notices — LIVE + BUILT
- **URL:** `https://www.ncnotices.com/Search.aspx`
- **Access:** ASP.NET WebForms grid, cookieless `/(S(id))/` session. **Grid
  (Search.aspx) is free, no challenge.** Keyword box (All/Any/Exact) + **county
  checkbox list (all 100 NC counties)** + city + publication + 12-month window.
  Must be driven in a browser (AJAX UpdatePanel; bare httpx postback 500s).
- **Probed 2026-08-12:** loads; "Foreclosure" is a listed popular category; all
  100 counties present alphabetically; 12-month window confirmed.
- **Carries:** foreclosure sale / substitute-trustee / tax-foreclosure notices,
  NCGS 105-369 tax-lien advertisements (annual, ~Mar-Jun), and estate
  notice-to-creditors (keyword `notice to creditors` / `executor` /
  `administrator`).
- **Wired as:** `public_notices.nc_notices_counties` (393 rows, county-checkbox
  method) and older `public_notices.ncnotices` (42 rows, statewide keyword).
- **CEILING — read this before trusting a field:** `Details.aspx` (full notice
  body) is behind an "I Agree" interstitial **+ reCAPTCHA**. The wired scraper
  parses only the **~300-char grid preview**, which reliably carries caption,
  case number, county and party name but **truncates before property ADDRESS,
  PARCEL and SALE DATE**. These are name+case leads for the resolver, not
  address-complete listings. The full body is reachable only by the MANUAL-SAVE
  lane below.

### scpublicnotices.com — SC Press Association public notices — LIVE + BUILT
- **URL:** `https://www.scpublicnotices.com/Search.aspx`
- **Access:** same ASP.NET WebForms pattern. **Grid is free, no challenge**
  (robots allows a generic agent). County filter (all 46), city, publication,
  **date-range**, keyword (All/Any/Exact), and a `ddlPopularSearches` category
  menu.
- **Probed 2026-08-12:** loads; category menu explicitly lists **Foreclosures,
  Notice to Creditors, Probate Notices, Tax Sales, Delinquent Taxes,
  Forfeitures/Seizure** — i.e. every non-divorce court signal in one place.
- **Wired as:** `counties_sc.sc_public_notices` (349 rows; Cherokee 116,
  Laurens 62, Oconee 57 lead the footprint).
- **Query one county at a time:** the row's `County:`/`City:` div is the
  PUBLICATION county, not the notice's subject county; the FILTER county is the
  property county (15-0 in a live check). The div only populates once a filter
  is in force, so an empty-county page is a silently-failed filter — discard it.
- **CEILING:** `Details.aspx` is Cloudflare Turnstile + reCAPTCHA. Same
  consequence as NC — preview only (~270-340 chars), so legal description, bid
  terms and most addresses are unavailable except via MANUAL-SAVE.

### The MANUAL-SAVE lane that lifts both from name+case to address-complete
Because the notice BODY is CAPTCHA-gated on both portals, the operator path is:
open the grid (free), click into a specific notice, solve the one "I Agree" /
CAPTCHA in a real browser, save the full-text page, and drop it into the offline
parser folder (mirror of the existing `scripts/ingest_saved.sh` court lane). The
saved body carries the property address, legal description, sale date/time and
opening-bid terms the grid preview cuts off. Reserve it for HOT/A-grade leads —
it is one CAPTCHA per notice, not a bulk path.

---

## Wall 1 — NC eCourts Smart Search / Search Hearings (AWS-WAF)

Holds NC **SP foreclosure**, **EST estates**, and **raw CVD divorce**. The open
NC Judgment Search JSON does NOT index SP or EST (structural, not a code gap).

| Sub-filing | Free / manual alternate | Access | Counties | Fills | Flag |
|---|---|---|---|---|---|
| **SP power-of-sale foreclosure** | **ncnotices.com** "Foreclosure" + county filter. NCGS 45-21.17 mandates the notice of sale be published, so every SP sale surfaces here ~weeks before the sale. | free grid GET-style (browser postback); reCAPTCHA only on body | all 14 NC core + 5 coastal | foreclosure_sale, party name, case#, county (address via manual-save) | LIVE + BUILT |
| SP foreclosure (upstream signal) | **ROD substitution-of-trustee** — the S/T recording that STARTS the case, earlier than the notice. | free click-through, no CAPTCHA | Clay, Haywood, Yancey (The Lookup) + Cleveland/Burke Logan/CCHS | foreclosure start, grantor name, book/page | BUILT (`wnc_rod_foreclosure_starts`, `nc_rod_substitute_trustee`) |
| SP foreclosure (trustee-side) | **Law-firm sale lists** (Brock & Scott, Hutchens, Shapiro Ingle, Kania, Aldridge Pite, etc.) — the substitute trustees publish their own dockets. | free HTML/PowerBI | statewide NC | sale date, address, opening bid | BUILT (`law_firms.*`) |
| **EST estate / notice to creditors** | **ncnotices.com** keyword `notice to creditors` + **Column legal-notice API** (already the compliant NC estate lane). NCGS 28A-14-1 mandates publication. | free | all NC footprint | decedent, executor/administrator name, sometimes mailing addr | BUILT (`column_legal_notices`, `nc_notices_counties`) |
| EST estate (death signal) | **Gannett obituaries + funeral-home RSS** — name-only, feeds the GIS owner index. | free RSS/HTML | 8 Gannett papers over footprint | decedent name | BUILT |
| **Raw CVD divorce filing** | **No newspaper lane** — divorce complaints are not advertised in NC (only a service-by-publication summons appears, and only when a spouse cannot be located: a thin sliver on ncnotices). GRANTED divorces come free from the Judgment Search JSON (`FAM - Divorce`). Raw filings stay in Smart Search. | — | — | — | **WALL** (raw filing); Judgment-JSON covers granted |

**Net:** NC SP foreclosure and EST estates both have a solid free alternate (the
press-notice lane + Column + ROD + law firms). Only the RAW CVD divorce filing
is walled, and granted divorces are already recoverable free.

---

## Wall 2 — SC PublicIndex Family Court / FCCMS (Rule 610 ToS) — divorce

- **Free alternate: NONE.** SC divorce is NOT a published legal notice — there
  is no statutory publication requirement, so scpublicnotices.com yields ~0
  divorce rows. (Only a rare service-by-publication summons, when a defendant
  spouse cannot be found, appears — negligible and not a reliable feed.)
- **Manual lane:** operator accepts the FCCMS disclaimer in a real browser,
  searches Family cases per county (case types FD/ID/CD/ED/SA — never 50B),
  saves result pages to the offline parser. ToS forbids automation; manual only.
- **Flag: WALL** (structural — the data is not published anywhere free; ToS
  blocks the only index). This is the one court wall with no free alternate.

---

## Wall 3 — SC PublicIndex estates / probate (Rule 610 ToS)

This wall is effectively SOLVED by the notice lane, and the newspaper route is
STRONGER than the docket because it carries the PR mailing address (contact).

| Alternate | Access | Counties covered | Fills | Flag |
|---|---|---|---|---|
| **`counties_sc.sc_probate_notices`** — SCPC 62-3-801 Notice to Creditors, parsed from newspaper legals. County derived from the 2-digit code in the ES case number, not the paper. | free | Pickens 516, Cherokee 245, Laurens 125 (886 estates) — reaches the two biggest counties southcarolinaprobate.net MISSES | decedent, **PR name + mailing address** (884/886), case#, county | **BUILT** |
| **scpublicnotices.com** — "Notice to Creditors" + "Probate Notices" categories, county filter, date range. | free grid (body CAPTCHA-walled) | all 46, incl. all 7 SC core + 4 coastal | decedent, PR name, case#, county | LIVE + BUILT (`sc_public_notices`) |
| **southcarolinaprobate.net** — probate case aggregator. Returned 403 to a plain fetch on 2026-08-12 (bot-sensitive to the generic agent); the wired stealth scraper still reads it. | free but bot-sensitive; no login, no ToS prohibition | 20 SC counties incl. Charleston, Cherokee, Oconee, Georgetown — but NOT Spartanburg/Anderson/Pickens/Laurens | decedent, PR name + full mailing addr, dates | BUILT (`sc_probate_net`, 250 Charleston) |
| **Heir/estate parcels via county GIS** — retitled `"<name> HEIRS"` / `"ESTATE OF"` parcels. | free ArcGIS | Spartanburg, Pickens, Laurens, Union (+ 11 NC) | owner, situs, PIN, mailing | BUILT (`nc_heir_estate_parcels`) |

**Net:** SC estates are covered free across the whole footprint via the
newspaper Notice-to-Creditors lane, and that lane uniquely supplies the PR
**mailing address** — the thinnest field in the engine. Do NOT chase the
PublicIndex probate docket; the notice carries the same facts plus contact.

---

## Wall 4 — counties where foreclosure / lis-pendens sits only in a walled portal

| Portal wall | Free alternate | Counties | Flag |
|---|---|---|---|
| **SC PublicIndex CP-420 foreclosure** (ToS) | **scpublicnotices.com "Foreclosures"** (SC foreclosure is judicial → the summons/sale notice is published) + **MIE sale rosters** + **law-firm dockets** (Brock & Scott, Hutchens, Rogers Townsend, Bell Carrington, Finkel, Korn, Terry Howe FLC). | all SC core + coastal | LIVE + BUILT (`sc_public_notices`, `sc_county_rosters`, `sc_coastal_rosters`, `law_firms.*`) |
| **NC SP foreclosure** (AWS-WAF) | ncnotices.com + ROD S/T + law firms — see Wall 1. | all NC footprint | BUILT |
| **NC eCourts LP (lis pendens)** | Already free via the **NC Judgment Search JSON** (`CV - Lis Pendens`). Not walled. | all NC footprint | BUILT (`nc_ecourts_lis_pendens`) |
| **SC lis pendens** | scpublicnotices.com "Foreclosures" caption carries the LP; SC judicial foreclosure IS the lis pendens. | all SC footprint | BUILT |

No footprint county has foreclosure/LP that is ONLY in a walled portal with no
free notice or roster alternate. The residual gap is data DEPTH (address /
parcel / sale-date live past the CAPTCHA-gated notice body), not COVERAGE.

---

## Summary — what each wall's free alternate does and does not buy

- **NC SP foreclosure:** SOLVED for existence/name/case/county via ncnotices.com
  + ROD S/T + law firms. Address needs the manual-save lane.
- **NC EST estates:** SOLVED via Column + ncnotices notice-to-creditors +
  obituaries.
- **NC raw CVD divorce:** WALL (not published). Granted divorces free via
  Judgment JSON.
- **SC FCCMS divorce:** WALL — the only court wall with no free alternate;
  divorce is not a published notice and the index is ToS-locked. Manual FCCMS
  save lane only.
- **SC estates/probate:** SOLVED and then some — the Notice-to-Creditors lane
  (`sc_probate_notices` + scpublicnotices.com) reaches all 46 counties AND
  carries the PR mailing address the docket lacks.
- **SC foreclosure/LP:** SOLVED via scpublicnotices.com + MIE rosters + law
  firms.

The single structural hole: **SC divorce**. Everything else has a free or
manual channel, and the shared ceiling on the newspaper lanes is the
reCAPTCHA/Turnstile on the notice BODY — worked around per-lead by the operator
save-and-ingest path, never bulk.
</content>
