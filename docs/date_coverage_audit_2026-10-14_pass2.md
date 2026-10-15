# Date-coverage audit — Pass 2 — 2026-10-14

Pass 1 (`docs/date_coverage_audit_2026-10-14.md`) covered **current-state rolls**
(delinquent-tax lists, code-enforcement registries) — sources that should show the
FULL roll regardless of debt age, and mostly already did. This is Pass 2, covering
the other half of the owner's original question: **event-stream sources** (ROD
recordings, lis pendens, court dockets, foreclosure filings) — "what got filed
recently." A rolling lookback window is *correct design* for these; the risk Pass 2
hunts for is narrower and sharper:

> Is any event-stream source used as the ONLY signal for something that's really an
> ongoing STATUS, such that a case still active in court — but whose last recording
> or filing event happened outside the lookback window — gets permanently dropped and
> never resurfaces? (Concrete example: a foreclosure filed 14 months ago, still
> working through the system, generates no NEW recording — a rolling 90-day sweep
> never sees it again, even though it's a live, actionable case.)

**Method.** Candidates were enumerated by grepping
`src/foreclosure_scraper/scrapers/` for foreclosure/lis-pendens/judicial-
sale/docket-shaped file names and content, cross-referenced against what
`scrapers/_registry.py`'s `discover()` actually loads, then filtered by judgment to
genuine foreclosure/lis-pendens-carrying event streams (excluding Pass 1's tax rolls
and excluding generic public-notice/obituary feeds with no foreclosure content).
**~88 files** were looked at this way. For the FLAGGED candidates and the one
already-protected reference source, every fetch/query function and every related
board-retention code path was read in full. For the large CLEAN groups (sale-
calendar sites, law-firm trustee-sale lists, the in-rem tax-foreclosure docket
family — these are fundamentally a different, simpler shape, and Pass 1 had already
read several of them) rigor was lighter: one representative file read in full per
group, the rest confirmed by naming convention and a grep for date-window code,
matching Pass 1's own stated rigor split between its gold-standard write-ups and its
one-line bulk-CLEAN groups.

**The headline finding is structural, not a per-file bug list.** Unlike Pass 1
(four independent, unrelated date-cap constants), almost every genuine gap found
here traces back to **one shared mechanism** — the board's own cross-run retention
logic — which already has the right idea built in, just scoped to one source and
one county. See the cross-cutting section below before the per-source list; it
explains *why* a source can be correctly, deliberately date-windowed in its own
`fetch()` and still silently lose a live case.

**Result: 88 files reviewed. 72 CLEAN, 15 FLAGGED — no ongoing-case tracking (the
actionable target of this audit), 1 FLAGGED — source limitation, 0 UNCLEAR.**

---

## Cross-cutting finding: the board's own retention logic is the real mechanism — and it protects exactly one source

Every scraper here runs fresh each pass, and its own `fetch()` naturally only
returns what's inside its lookback window — that part is fine and expected. The
question is what happens to a listing that FELL OUT of that window on a later run:
does the board keep it, or silently delete it? That's decided by a completely
separate piece of code, `board_persist.merge_prior_board()`, the function that
folds the previously-published board into each fresh scrape.

Reading it end to end (`src/foreclosure_scraper/board_persist.py`), a prior-only row
(on the board, but not re-matched by this run's fresh scrape) is handled by exactly
one of four branches, checked in this order:

1. **`_is_terminal_dict()`** — dropped immediately, unconditionally, regardless of
   anything below, if `raw.sold_confirmed`, `raw.court_sale_status == "confirmed"`,
   the `upset_bid_deadline` has passed, or `sale_date` is more than
   `TERMINAL_SALE_GRACE_DAYS` (365, env-overridable) in the past. Correct: a
   confirmed sale really is over.
2. **`AGE_EXEMPT_SOURCES`** — a `frozenset`, currently holding exactly **one**
   entry: `liensnc`. The comment explains the model precisely: *"A recorded filing
   is history, not a listing that can be 'pulled': it is fed by an incremental
   hand-off (only NEW filings arrive), so absence from a run says nothing about
   it."* A row from an age-exempt source never ages, never gets a miss counted —
   it just sits on the board until something (terminal check #1, or a real
   resolution found some other way) removes it.
3. **`OPEN_CASE_SOURCES` / `OPEN_CASE_COUNTIES`** — a pair of `frozenset`s, together
   covering exactly **`national.sc_public_index`+`national.sc_public_index.judgment_lien`,
   Charleston County SC only**. `open_case_hold()` reads that row's own
   `raw["sc_public_index"]["lane"]` / `["status"]` / `["date_disposed"]` fields
   (fields this one source's Charleston lane specifically captures — see below) and
   holds the row open, no miss counted, as long as the case isn't dismissed/
   withdrawn/satisfied and has had activity within `OPEN_CASE_MAX_IDLE_DAYS` (365
   days). This is a real, deliberate, dated fix — the code comment cites it being
   added 2026-10-09 specifically because Charleston rows were getting
   `presumed_withdrawn`-tagged and dropped under the generic rule below.
4. **The generic fallback** — everything not covered by 1-3. Each miss increments
   `raw.pulled_sale.consecutive_misses`; past `max_misses` (default
   `PULLED_RETENTION_WEEKS = 4`, i.e. 4 *consecutive full-run misses*, not 4 calendar
   weeks) the row is dropped for good.

Separately, `main.py`'s `DATELESS_OK_SOURCES` whitelist (and the state-aware
upset-window grace in `_active_only`) makes sure a dateless event-stream row
survives being dropped *within the run that freshly scrapes it* — nearly every
source below is on that whitelist. That solves a different problem. It says
nothing about whether the row survives being folded forward into the *next* run
once the scraper itself stops re-finding it — that is purely branches 1-4 above.

**Why this matters concretely.** Branch 4's "4 consecutive run misses" sounds like
roughly a month. In practice it's looser, because full runs are themselves
irregular — `docs/audit_operations_2026-09-21.md` measured "7 successful full-run
publishes in about 14 weeks" against a nominal weekly schedule. But it is still
bounded, and the bound is real: once a case's last-seen event is outside **both**
its scraper's own lookback window **and** roughly a month to a few months of
further run cycles, it is gone from the board for good — with nothing checking
whether the underlying court case, bankruptcy, or recorded NOD/NOS is still
active. The owner's "14-months-old, still working through the system" example is
not a hypothetical here: for several sources below, that is almost exactly the
real elapsed time (lookback window + a handful of irregular run cycles) before a
still-open case drops off the board.

**The fix shape this points to, for every FLAGGED item below, is the same one
already proven for Charleston: extend `AGE_EXEMPT_SOURCES` or `OPEN_CASE_SOURCES`
(and, where the row's own status field uses a different key or vocabulary, add a
small adapter branch to `open_case_hold()`) — not a scraper rewrite.** That is a
materially cheaper, lower-risk fix shape than Pass 1's (which needed per-source
constant changes); it is almost entirely confined to `board_persist.py`.

---

## CLEAN — live docket / sale-calendar shape, no case-age risk by design (72)

These sources all share one property that makes the retention question above moot:
they republish whatever the source *itself* currently shows as scheduled/active,
with no code-side filter on how old the underlying case is. A case with nothing
currently scheduled correctly does not appear — that is not a false drop, because
this source type was never the one carrying the "is this case still alive" signal
in the first place (that's the FLAGGED group below). If a postponed sale later gets
a new date, it reappears on its own, correctly, the next time that page is read.

**NC in-rem tax-foreclosure sale-docket family** (Pass 1 already read several of
these; re-confirmed here against this audit's specific question by reading
`wake_tax_foreclosure.py` in full — its own page is a live accordion of "None at
this time" vs. currently-open cases per municipality, no date filter in our code at
all, cases stay listed until resolved by the county's own page, not by us):
`counties_nc/wake_tax_foreclosure.py`, `counties_nc/cleveland_tax_foreclosure.py`,
`counties_nc/cumberland_tax_foreclosure.py`, `counties_nc/edgecombe_tax_foreclosure.py`,
`counties_nc/gaston_tax_foreclosures.py`, `counties_nc/guilford_tax_foreclosures.py`,
`counties_nc/haywood_tax_foreclosures.py`, `counties_nc/mecklenburg_tax_foreclosures.py`,
`counties_nc/swain_tax_foreclosures.py`, `counties_nc/wnc_tax_foreclosures.py`,
`counties_nc/buncombe_tax_foreclosure.py`, `counties_nc/nc_coastal_tax_foreclosure.py`,
`counties_nc/nc_county_tax_foreclosure.py`, `counties_nc/rutherford_foreclosure.py`,
`counties_nc/new_hanover_foreclosures.py`, `counties_nc/stokes_delinquent_tax.py`
(misnamed — the Kania statewide sale-listing table per Pass 1).

**SC Master-in-Equity sale calendars** — read `anderson_master_in_equity.py` in
full: three PDF families (upcoming Sale-List, past Sale-Results/comps, reopened
Deficiency-Sale bidding), each gated only by *is this PDF currently published on the
county's own page*, never by case age. `greenville_mie_adverts.py` is worth naming
specifically: its past-sale rows deliberately ship as `DISTRESSED` rather than
`FORECLOSURE_SALE` specifically *because* "judgment-debt value doesn't go stale"
(see `main.py`'s `DATELESS_OK_SOURCES` comment) — a small, already-correct piece of
exactly this audit's reasoning, just applied to a different listing type. Group:
`counties_sc/anderson_master_in_equity.py`, `counties_sc/charleston_mie.py`,
`counties_sc/greenville_mie_adverts.py`, `counties_sc/pickens_master_in_equity.py`,
`counties_sc/spartanburg_master_in_equity.py`.

**SC sheriff sales** (live current-sale postings, same shape):
`counties_sc/anderson_sheriff.py`, `counties_sc/bamberg_sheriff.py`,
`counties_sc/barnwell_sheriff.py`, `counties_sc/dillon_sheriff.py`.

**Law-firm substitute-trustee pending-sale sites** — read `law_firms/hutchens.py`
in full: an ASP.NET GridView rendered entirely server-side with the firm's
CURRENT pending-sale roster, no date-window code of any kind (the whole published
grid is read every run). The rest of this family share the identical "foreclosure
law firm's own live sale-list page" shape and naming convention; not each one was
read line-by-line, but none of them plausibly carries a hidden "only show sales
filed in the last N days" cutoff — a firm's sale list is inherently "what's
currently scheduled," the same shape as the MIE calendars above. Group:
`law_firms/alaw.py`, `law_firms/aldridge_pite.py`, `law_firms/bell_carrington.py`,
`law_firms/brock_scott.py`, `law_firms/finkel.py`, `law_firms/ingle_firm.py`,
`law_firms/kania.py`, `law_firms/korn.py`, `law_firms/mcmichael_taylor_gray.py`,
`law_firms/mewborn_deselms.py`, `law_firms/rogers_townsend.py`,
`law_firms/shapiro_ingle_powerbi.py`, `law_firms/zacchaeus.py`.

**Other live-snapshot sale/auction feeds**, same reasoning (current inventory,
re-derived fresh every run, not a filing-date sweep): `counties_nc/nc_govdeals_real_property.py`,
`national/nc_upset_bids.py` (explicitly "properties CURRENTLY inside the 10-day
upset window," read in full), `national/irs_judicial_sales.py` (reads the live
`/auction/items` active-inventory index, read in full).

**National third-party listing aggregators** — a different but equally
self-correcting shape: a live for-sale listing, re-scraped fresh every run; if a
property disappears, `board_persist`'s generic `pulled_sale` miss-counter is the
*designed-for* mechanism here (a listing taken off Zillow/Realtor.com/auction.com
really did get sold/withdrawn/redeemed most of the time), not a bug: `national/zillow_foreclosures.py`,
`national/trulia_foreclosures.py`, `national/realtor_foreclosures.py`,
`national/xome.py`, `national/auction_dot_com.py`, `national/williams_auctions.py`,
`national/tranzon_auctions.py`, `national/homeharvest_distressed.py`.

**Newspaper / public-notice legal-ad feeds carrying foreclosure-sale content** — a
published legal ad is itself a point-in-time announcement of one scheduled sale;
once published it is a durable historical fact needing no "is this still open"
re-check (the sale date in the ad is the whole signal), the same reasoning Pass 1
already applied to `spartan_weekly_legals.py` and `sc_public_notices.py` (both
re-affirmed here, unchanged). Group: `counties_nc/brunswick_legal_notices.py`,
`counties_sc/spartan_weekly_legals.py`, `counties_sc/sc_public_notices.py`,
`newspapers/berkeley_independent.py`, `newspapers/aiken_standard.py`,
`newspapers/carolina_coast.py`, `newspapers/_townnews.py`, `newspapers/columbia_star.py`,
`newspapers/index_journal.py`, `newspapers/daily_courier.py`, `newspapers/coastland_times.py`,
`newspapers/shelby_star.py`, `newspapers/column_legal_notices.py`,
`newspapers/hendersonville_lightning.py`, `newspapers/mecklenburg_times.py`,
`newspapers/journal_scene.py`, `newspapers/post_and_courier.py`, `newspapers/tryon_bulletin.py`,
`public_notices/nc_notices_counties.py`, `public_notices/ncpublicnotices.py`,
`public_notices/publicnoticesc.py`.

**Already deliberately protected — the reference implementation:**
`national/sc_public_index.py` (Charleston SC lane only). This is the one source
in the whole codebase that already does what every FLAGGED item below needs: its
own `_hit_to_listing`-equivalent captures a `lane` (foreclosure/partition/quiet
title/lis pendens/judgment/other), a `status`, and a `date_disposed` per case, and
`board_persist.open_case_hold()` reads those exact fields to hold a prior-only row
open — no miss counted — for as long as the case stays open (or, for a disposed
foreclosure, for `CHARLESTON_PI_JUDGMENT_DAYS` ≈ 9 months past judgment, since in SC
a foreclosure's judgment is entered well before the Master-in-Equity sale actually
happens). This is the pattern every FLAGGED source should be made to match — it is
the Pass-2 analogue of Pass 1's `multi_year_delinquent_tax.py`.

**Already deliberately exempted — the other reference pattern:**
`counties_generic/liensnc.py`. Not itself read as a "roll vs. event" question this
pass (it's a login-gated incremental hand-off, out of this audit's normal reading
path), but cited because it is the *entire membership* of `AGE_EXEMPT_SOURCES`, and
its justification — "a recorded lien-agent filing is history, not something that
gets un-filed" — is the cheaper of the two existing patterns and, as the per-source
notes below argue, the right model for several FLAGGED sources that have no status
field to check at all.

---

## FLAGGED — no ongoing-case tracking (15 files, the actionable target of this audit)

### 1. `counties_nc/nc_ecourts_lis_pendens.py` — HIGH confidence, HIGH board impact
The single biggest footprint of anything flagged here: all 100 NC counties, a
90-day `LOOKBACK_DAYS` window on the judgment's `orderedDate`, 78,663 hits measured
in one 90-day/100-county pull (2026-09-23 widening). `_hit_to_listing` already
reads and stores `civilJudgmentStatus` per hit (used to filter OUT
Canceled/Satisfied/Dismissed/Vacated/Withdrawn/Expired/Released rows from being
emitted in the first place) — the row carries `raw.nc_ecourts.civilJudgmentStatus`
all the way through. But because this scraper only ever queries by `orderedDate`
within the last 90 days, a lis pendens, claim of lien, or judgment lien whose
`orderedDate` ages past 90 days is simply never queried again — there is no
case-number re-check. It then falls straight into `board_persist`'s generic
4-miss fallback (not in `OPEN_CASE_SOURCES`, not in `AGE_EXEMPT_SOURCES`), and most
of these rows carry `sale_date=None` (by design — `orderedDate` is a judgment date,
not a sale date), so the terminal check never catches them either; they just age
out silently.

**Fix shape:** this source is *better positioned than Charleston* to fix cheaply —
it already carries a real status field. Add an NC branch to
`board_persist.open_case_hold()` (or a sibling function) that reads
`raw["nc_ecourts"]["civilJudgmentStatus"]` with the same closed-status regex
`_hit_to_listing` already uses, and holds the row open (no miss counted) while it
isn't terminal and has had activity within some idle-days bound. No new scraping,
no change to the scraper's own 90-day window (which is fine — it's a discovery
window, not a case-status window).

### 2. CourtListener family — HIGH confidence, HIGH board impact
`national/courtlistener_bankruptcy.py` (`LOOKBACK_DAYS = 90`, `filed_after=cutoff`),
`national/courtlistener_civil.py` (imports the same `LOOKBACK_DAYS`, same
`filed_after` shape), `national/courtlistener_adversary.py` (full-text RECAP
search, no explicit day-count but the same "only recent dockets come back" shape).
All three are pure filed-date sweeps with no case-number re-check — and all three
already capture the single cleanest possible status signal in this whole audit:
**`raw["courtlistener"]["date_terminated"]`** (`hit.get("dateTerminated")` /
`res.get("dateTerminated")`), a field that is simply `null` while the
case is open. `courtlistener_bankruptcy.py`'s own comment even flags the gap in
passing: it notes `is_long_open` "will always be False on rows it emits itself"
since this scraper's own window can't produce a 10-year-old case — true, but the
real exposure isn't 10-year-old cases, it's the 90-days-to-several-years range a
Chapter 13 plan (3-5 years) or a slow civil foreclosure spends open with nothing
further filed. A separate enrichment pass, `enrichment_bankruptcy.py`'s
`_fetch_long_open_bankruptcies`, deliberately re-queries a 10-15-year-old window
for a *different* purpose (surfacing long-dormant bankruptcies as a NEW discovery
signal against other board rows) — it does not re-verify the status of a
bankruptcy/civil/adversary row this scraper already put on the board, and doesn't
touch anything filed 90 days to 10 years ago, which is exactly this gap's range.

**Fix shape:** the cheapest fix in this entire audit. Add
`national.courtlistener_bankruptcy`, `national.courtlistener_civil`, and
`national.courtlistener_adversary` to a status check that is a single null-check —
`raw.courtlistener.date_terminated is None` means still open — no regex, no
vocabulary mapping, no new fetch. Given how clean this signal is, these three
could even be reasonable candidates for `AGE_EXEMPT_SOURCES` directly (treat
`date_terminated` as the terminal signal instead of `_is_terminal_dict`'s
sale-date proxy, which these case types don't really have anyway).

### 3. `counties_sc/sc_public_index_lis_pendens.py` — HIGH-MED confidence
The 44-non-Charleston-county sibling of the already-protected `national/sc_public_index.py`
(`LOOKBACK_DAYS = 60` on `filed_date`). Already writes
**`raw["sc_public_index"]["status"]`** per row — literally the same raw key the
protected Charleston source uses — but this source's slug
(`counties_sc.sc_public_index_lis_pendens`) is not in `OPEN_CASE_SOURCES`, and none
of its counties are in `OPEN_CASE_COUNTIES`. One real wrinkle if this gets fixed:
`open_case_hold()` reads `spi.get("date_filed")` for its idle-days check, but this
file writes the key as `spi["filed_date"]` (reversed word order) — today that
silently falls through to using `first_seen` as the activity proxy instead, which
mostly still works but isn't reading the real filed date.

**Fix shape:** add this slug (and its real county footprint — Spartanburg,
Greenville, Pickens, Oconee, Anderson, and the other 39 non-Charleston counties
this source covers) to `OPEN_CASE_SOURCES`/`OPEN_CASE_COUNTIES`; fix the
`filed_date`/`date_filed` key mismatch while touching this code so the idle-days
check reads the real filed date instead of falling back to `first_seen`.

### 4. `counties_sc/sc_public_index.py` — MED confidence
Same 44-county footprint and `LOOKBACK_DAYS = 45` window, also captures a
`status_txt` and `dispo_txt`/`disposition_date` per row — but writes them under
**`raw["court"]`**, not `raw["sc_public_index"]` (a different key than both the
protected Charleston source and its own sibling file #3 above use). `open_case_hold()`
only ever reads `raw["sc_public_index"]`, so this file's rows get no benefit even
if #3's fix lands untouched.

**Fix shape:** either normalize this file's raw key to `sc_public_index` (for
consistency with its own sibling and the protected reference, lower future
maintenance cost) or add a second branch to `open_case_hold()` that also reads
`raw["court"]["status"]`/`["disposition_date"]`/`["filed_date"]`. Either way, a
board_persist-side change, not a scraper rewrite.

### 5. ROD / NOD pre-foreclosure recording-sweep family — MED-HIGH confidence, widest file count
Nine files, all sharing the identical underlying shape: sweep the last N days of
Register-of-Deeds recordings for a document type that signals the START of a
foreclosure (Notice of Default, Notice of Sale, Substitution of Trustee, Lis
Pendens), with **no case-status field of any kind** — the ROD index records what
was *filed*, never what *happened to the case afterward*. Read in full:
`counties_nc/nc_rod_substitute_trustee.py` (PRE-sale lane only — its POST-sale
Trustee's-Deed lane is CLEAN, see note below; `LOOKBACK_DAYS = 60`) and
`counties_nc/wnc_rod_foreclosure_starts.py` (`LOOKBACK_DAYS = 21` — the narrowest
window of anything in this audit, capturing the single *earliest*-stage NC
foreclosure signal there is, a substitution of trustee recorded even before the
notice of hearing is filed — meaning the real remaining case duration ahead of
this narrow window is typically the longest of any source here). Same shape,
confirmed by vendor-adapter pattern and a grep for date-window/status code (not
each read in full): `counties_nc/nc_rod_captcha.py` (`_BRUNSWICK_LOOKBACK_DAYS = 90`,
`_WAKE_LOOKBACK_DAYS = 90`, plus the CCS DevExpress county group),
`counties_nc/nc_rod_logan.py` (`_LOOKBACK_DAYS = 60`),
`counties_sc/sc_rod_acclaim.py` (`_LOOKBACK_DAYS = 45`),
`counties_sc/sc_rod_cott.py`, `counties_sc/sc_rod_walled.py`
(`CLARENDON_LOOKBACK_DAYS = 45`), `counties_sc/cherokee_rod.py`, and
`counties_generic/nod_discovery.py` (the cross-county generic NOD sweep over the
Aumentum/CCHS/Cott/Kofile adapters).

A NOD or substitution-of-trustee recording doesn't need a "is the case still open"
query at all, in principle — it's a filed, permanent fact, exactly like
`liensnc`'s lien-agent appointments. The gap is purely that these sources are not
in `AGE_EXEMPT_SOURCES` the way `liensnc` is, so they fall into the generic 4-miss
fallback once their short lookback window passes.

**Separately, `counties_generic/nod_discovery.py` has its own, sharper defect**
that would defeat even an `AGE_EXEMPT_SOURCES` fix: unlike
`nc_rod_substitute_trustee.py` (which correctly leaves `sale_date=None` on its
PRE-sale rows), `nod_discovery.py` sets `sale_date = recorded_date + 90 days`
(`NC_NOD_TO_SALE_DAYS`) — a *guessed* placeholder sale date, intended only to
surface the row in an upcoming-sales view. But `_is_terminal_dict()` runs *before*
any `AGE_EXEMPT_SOURCES`/`OPEN_CASE_SOURCES` check, and it drops any row whose
`sale_date` is more than `TERMINAL_SALE_GRACE_DAYS` (365 days) in the past —
meaning every `nod_discovery.py` row gets force-dropped as "terminal" at
recorded_date + 90 + 365 ≈ **455 days**, regardless of any future aging exemption,
simply because of the fabricated date sitting in a field a different, unrelated
piece of code trusts as a real sale date.

**Fix shape:** add all nine files to `AGE_EXEMPT_SOURCES` (same justification
`liensnc` already has on record). For `nod_discovery.py` specifically, also stop
setting a fabricated `sale_date` (set it to `None`, matching
`nc_rod_substitute_trustee.py`'s own PRE-sale convention) — otherwise the
exemption fix is silently defeated by the terminal-date check that runs ahead of
it.

**Not flagged, for contrast:** `nc_rod_substitute_trustee.py`'s POST-sale lane
(`_sold_doc_to_listing`, Trustee's Deed recordings) is CLEAN — the sale already
happened, `sale_date` is the real recording date, and the existing terminal-date
rule correctly ages these out as settled history.

---

## FLAGGED — source limitation (1)

- **`national/bankruptcy_rss_relief_from_stay.py`** — the three courts' own CM/ECF
  public RSS feeds are themselves rolling ~24-hour windows (the module's own
  docstring: "a run that skips a day loses that day's entries"); there is no
  fuller historical feed to query instead at this access tier (full history needs
  paid PACER). Not fixable by changing a constant in this file. Lower practical
  priority than the FLAGGED group above for a different reason too: each row here
  represents a single COURT MOTION event (a creditor asking to lift the automatic
  stay), which — like a published sale notice — is a point-in-time fact that
  doesn't itself need "is this still true" tracking; the thing that *does* need
  tracking is the underlying bankruptcy CASE, which is `courtlistener_bankruptcy.py`'s
  job (FLAGGED #2 above). Fixing #2 captures the real exposure this file's own
  rows would otherwise represent.

---

## Prioritized Phase-2 fix list

Unlike Pass 1, the fix for nearly everything below is concentrated in **one file**,
`src/foreclosure_scraper/board_persist.py` (specifically `AGE_EXEMPT_SOURCES`,
`OPEN_CASE_SOURCES`/`OPEN_CASE_COUNTIES`, and `open_case_hold()`), not scattered
across per-scraper constants. That makes sequencing mostly about status-field
cleanliness and board impact, not engineering difficulty — everything here is
cheaper than any single item in Pass 1's list.

1. **CourtListener family** (`courtlistener_bankruptcy.py` / `courtlistener_civil.py`
   / `courtlistener_adversary.py`) — the single cleanest fix available: a bare
   `date_terminated is None` check, no vocabulary mapping, no key-name cleanup
   needed. Also the most severe real-world mismatch measured against the owner's
   own framing — Chapter 13 plans run 3-5 years, far past any plausible lookback
   window.
2. **`counties_nc/nc_ecourts_lis_pendens.py`** — single biggest footprint in this
   audit (100 NC counties, tens of thousands of hits per 90-day pull), already
   carries a usable `civilJudgmentStatus` field; needs one new `open_case_hold()`
   branch.
3. **`counties_sc/sc_public_index_lis_pendens.py`** — cheapest SC fix: add the
   existing slug + its real county list to the existing frozensets (same raw key
   the protected Charleston source already uses), fix the `filed_date`/`date_filed`
   key mismatch while there.
4. **`counties_sc/sc_public_index.py`** — same county footprint as #3, one grade
   more work (different raw key, `raw["court"]` vs `raw["sc_public_index"]`,
   needs either a key-rename or a second `open_case_hold()` branch).
5. **ROD/NOD pre-foreclosure recording-sweep family** (9 files) — widest file
   count but the lowest-precision fix available (no status field exists to check,
   so this is an `AGE_EXEMPT_SOURCES` addition, not a status-aware hold); do
   `counties_generic/nod_discovery.py`'s fabricated-`sale_date` fix as a
   prerequisite for that file specifically, or the exemption will be silently
   defeated by the terminal-date check regardless.

Everything in the "FLAGGED — source limitation" bucket (`bankruptcy_rss_relief_from_stay.py`)
is already covered in substance once item 1 above lands, and does not need its own
fix.

---

## RESOLVED 2026-10-14 — prerequisite + all 15 FLAGGED items fixed

All of the above shipped, including the prerequisite. Mechanism-level changes are entirely in
`src/foreclosure_scraper/board_persist.py` (`AGE_EXEMPT_SOURCES` widened; three new sibling
functions to `open_case_hold()` — `courtlistener_open_hold()`, `nc_ecourts_open_hold()`,
`sc_upstate_open_hold()` — wired into `_age()` alongside it), per-source edits where noted, and
new tests in `tests/test_open_case_hold_pass2.py` (+ small per-source test additions). No change
to `src/foreclosure_scraper/web_artifact.py`; no new flat raw key needed registering (every field
added landed inside an already-wildcard-registered block: `raw['nod']`, `raw['sc_public_index']`).

**Prerequisite — `counties_generic/nod_discovery.py` fabricated `sale_date`: FIXED.**
`sale_date` is now always `None` (matches `nc_rod_substitute_trustee.py`'s own pre-sale
convention); the 90-day projection survives only as `raw['nod']['estimated_sale_date']`, a
non-authoritative estimate `_is_terminal_dict()` never reads.

1. **CourtListener trio: FIXED.** Added `national.courtlistener_bankruptcy` /
   `_civil` / `_adversary` via `board_persist.courtlistener_open_hold()` — a bare
   `date_terminated` null-check per source's own raw block (`courtlistener` /
   `courtlistener_civil` / `courtlistener_adversary` — the three do NOT share one raw key, unlike
   this doc's original item #2 text implied; verified by reading all three files in full).

2. **`counties_nc/nc_ecourts_lis_pendens.py`: FIXED.** Added both
   `counties_nc.nc_ecourts_lis_pendens` and its `.judgment_lien` sub-slug via
   `board_persist.nc_ecourts_open_hold()`, reading `raw['nc_ecourts']['civilJudgmentStatus']`
   with the same closed-status words `_hit_to_listing` already filters emission on, plus an
   idle-days bound off `orderedDate` (falling back to `first_seen`).

3. **`counties_sc/sc_public_index_lis_pendens.py`: FIXED.** Added via
   `board_persist.sc_upstate_open_hold()` (county-gated to this source's real 7-county
   footprint: Spartanburg/Anderson/Pickens/Oconee/Cherokee/Union/Laurens). Also fixed the
   `filed_date`→`date_filed` key mismatch in the scraper itself (grepped first — no other code
   read the old key) so the idle-days check reads the real filed date, not a `first_seen`
   fallback.

4. **`counties_sc/sc_public_index.py`: FIXED.** Added via the SAME `sc_upstate_open_hold()`
   (one function covering both #3 and #4, keyed per-source: this file's raw block is `court`,
   not `sc_public_index`, and it captures a real `disposition_date` #3's file doesn't — chose
   the "second branch" option over a key-rename, per this doc's own lower-risk framing).

5. **ROD/NOD family (9 files): FIXED — all nine added to `AGE_EXEMPT_SOURCES`.**
   `nc_rod_substitute_trustee`, `wnc_rod_foreclosure_starts`, `nc_rod_captcha`, `nc_rod_logan`,
   `sc_rod_acclaim`, `sc_rod_cott`, `sc_rod_walled`, `cherokee_rod`, `nod_discovery`.

   **Two bugs beyond this doc's own characterization, found while verifying each file's actual
   `Listing()` construction before exempting it (not trusting the "same shape" bulk grouping
   above at face value):**
   - `nc_rod_logan.py`'s `"foreclosure_deed"` lane (TR/D/TD/C-TR-D/SHF-D, a COMPLETED sale) and
     `wnc_rod_foreclosure_starts.py`'s `"trustees_deed"` lane (same) never set `sale_date` at
     all — only `nc_rod_substitute_trustee.py`'s post-sale lane did. Exempting either slug
     wholesale (both lanes share one slug in both files, same as `nc_rod_substitute_trustee.py`)
     would have let a completed sale sit on the board forever: `_is_terminal_dict()` runs
     unconditionally before any `AGE_EXEMPT_SOURCES` check, but needs a real `sale_date` to ever
     fire. Both lanes now set `sale_date = recorded_date`, matching the one lane that was
     already correct.
   - `wnc_rod_foreclosure_starts.py`, `nc_rod_captcha.py`, and `sc_rod_walled.py` were not in
     `main.DATELESS_OK_SOURCES` at all, and NONE of their rows (confirmed by reading every
     `Listing()` call site in all three files) ever carries a `sale_date` — meaning
     `main._active_only()` was silently dropping EVERY row from all three sources before it
     ever reached the board, independent of this retention fix entirely. Added to
     `DATELESS_OK_SOURCES`; without this, item 5's fix would have been a no-op for 3 of the 9
     files, the same "fix is silently defeated by an unrelated upstream gate" failure shape as
     the `nod_discovery` prerequisite itself.
   - `cherokee_rod.py`'s own `fetch()` currently `return []` unconditionally — it is a dormant
     enrichment-lookup helper (`search_owner`/`search_parcel`), not a live discovery source
     today. Its `AGE_EXEMPT_SOURCES` entry is correct and harmless but has NO live effect until
     a future pass wires its `fetch()` to actually emit Listings. Left as-is (out of scope to
     wire up a dormant scraper here) but flagged for whoever does that next.

   **Not independently live-verified:** the SC Upstate Public Index status vocabulary (item
   3/4's `_OPEN_CASE_CLOSED_RE` regex coverage against real "Case Status" text) — the site sits
   behind an F5/Shape JS challenge requiring a real stealth browser session (per both
   scrapers' own docstrings), which this pass deliberately did not spin up (resource
   discipline: plain httpx only). The regex reused is the one already proven live for
   Charleston; a future pass could confirm Spartanburg/Anderson/etc. use the same status words
   by reading a few real rows off the board.

**Nothing from the original 15 (+1 prerequisite) list is left open.** The two items above
(cherokee_rod's dormant `fetch()`, and the un-verified SC status vocabulary) are the only
loose ends, both called out explicitly rather than silently dropped.
