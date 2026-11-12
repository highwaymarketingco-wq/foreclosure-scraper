export const meta = {
  name: 'gap-sweep-wave7-top80-valuation',
  description: 'Investigate and adversarially verify the 14 live top80/valuation audit violations',
  phases: [{ title: 'Investigate' }, { title: 'Verify' }],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    is_real_bug: { type: 'boolean' },
    title: { type: 'string' },
    file: { type: 'string' },
    root_cause: { type: 'string' },
    recommended_fix: { type: 'string' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['is_real_bug', 'title', 'root_cause', 'recommended_fix', 'confidence'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    reasoning: { type: 'string' },
  },
  required: ['refuted', 'reasoning'],
}

const PREAMBLE = `You are investigating ONE specific audit_suite.py finding in the foreclosure-scraper repo
(/Users/cashhigh/foreclosure-scraper, NC+SC motivated-seller lead engine). Audit checks live in
scripts/audit_checks/*.py; run "uv run python scripts/audit_suite.py --only <check_stem> --board docs"
to re-measure live. The board is docs/listings.json.gz (437,170 rows) plus lazy detail sidecars.

Your job: read the check's own docstring (top of the relevant scripts/audit_checks/*.py file) for
exactly what it measures and why it would have caught something real, then trace the ACTUAL producer
code (grep for the raw key / stamp the check reads) to find the real root cause. Distinguish THREE
possible outcomes, and say which one applies:
  (a) REAL BUG in current code -- test it against a live failing example from the sample below before
      concluding this; propose a minimal, safe fix.
  (b) STALE-BOARD ARTIFACT -- a fix already shipped but affected rows haven't been re-scraped/re-touched
      since; or the violation count is explained by rows that predate a design decision. Not a code bug.
  (c) DELIBERATE DESIGN / NEEDS OWNER DECISION -- the current behavior is intentional (check the
      docstring's own "max" value and surrounding prose) or requires a product/business judgment call
      only the owner can make (budget size, which counties to prioritize, a tolerance threshold).
NEVER attempt a CAPTCHA bypass -- if a county's wall is the blocker, say so and stop (owner routes that
to Hermes). NEVER guess at a genuinely ambiguous design question -- flag it as needing the owner, do
not invent an answer. Set is_real_bug=true ONLY for outcome (a). Report in under 400 words total.`

const CLUSTERS = [
  {
    key: 'its-roll-shape',
    prompt: `${PREAMBLE}

CHECK: top80-its-roll-shape (scripts/audit_checks/top80_checks.py). Measures: a raw['nc_its_public_tax']
block that contradicts itself (is_two_year_plus mismatch, years not ascending, unconfigured county, a row
with NEITHER a parcel id NOR a street address -- unplaceable, tax_owed mismatch).
LIVE: 240 violations, all kind 'no_parcel_and_no_street', ALL in Duplin and Person counties only (two
of the 10 configured ITS portal counties). Investigate verification/verifiers/tax_lien_itspublic.py's
Duplin and Person portal configs/parsers specifically -- why would exactly these two counties produce
rows with no placeable identifier at all, while the other 8 configured counties (Alleghany, Anson,
Caswell, Graham, Granville, Harnett, Jones, Onslow) do not? Pull 2-3 live board rows for Duplin/Person
with this raw key and look at exactly what's missing.`,
  },
  {
    key: 'its-county-silent',
    prompt: `${PREAMBLE}

CHECK: top80-its-county-silent (scripts/audit_checks/top80_checks.py). Measures: a configured ITSPublic
county with ZERO rows on the board while the board holds ITS rows at all from other counties -- the
portal answered the probe on 2026-10-09 (400 bills in 10 counties) so total silence now is a parser or
session regression, not just low volume.
LIVE: Scotland and Yadkin are the 2 silent counties (of the 10 configured). The other 8 counties range
from 322 to 2,902 rows. Investigate verification/verifiers/tax_lien_itspublic.py's Scotland and Yadkin
portal entries (PORTALS dict / CELLS vs ITSNET_CELLS variant) -- are they even registered? Is the base
URL correct? Try a live probe against the portal the same way Duplin was verified in a prior pass
(verification.fetch.Fetcher + m.search against a real board parcel from another county in the same
vendor family, to confirm the vendor itself is reachable) if a comparable parcel id pattern can be
found; otherwise reason from the portal config alone.`,
  },
  {
    key: 'onemap-heir-shape',
    prompt: `${PREAMBLE}

CHECK: top80-onemap-heir-shape (scripts/audit_checks/top80_checks.py). Measures: raw['heir_estate']
stamped by the NC OneMap sweep (source nc_onemap_sweep) whose owner_of_record carries NEITHER "HEIR"
nor "ESTATE" in the name, or names a LIFE ESTATE / REAL ESTATE / ESTATES holder (the scraper's own
documented exclusions -- these three substrings should have been filtered out but weren't).
LIVE: 8 violations, sample counties: Chatham, Rutherford (x5), Henderson. Find the OneMap heir-estate
sweep scraper (grep for "nc_onemap_sweep" and "heir_estate" stamping), read its exclusion filter logic,
and pull the actual owner_of_record strings for 2-3 live violating rows in Rutherford to see exactly
what's slipping through the LIFE ESTATE/REAL ESTATE/ESTATES exclusion.`,
  },
  {
    key: 'fill-deed-ref-shape-and-bound',
    prompt: `${PREAMBLE}

CHECK (two related checks, same producer likely): top80-fill-deed-ref-shape and top80-fill-deed-ref-bound
(scripts/audit_checks/top80_fill.py). shape: 1 violation, kind 'placeholder_or_padded' (NC:Macon:
7540038288) -- a deed_ref that looks like a placeholder/padded value rather than a real reference.
bound: 1,453 violations -- by far the LARGEST finding in this wave -- kind 'county_deed_ref_other_parcel'
(939) and 'county_legal_other_parcel' (514): a row's deed_ref or legal_description was actually sourced
from a DIFFERENT parcel's county record than the one it's attached to on the board. Sample counties:
Rutherford, Polk, Henderson, Mecklenburg (truncated in the audit sample -- re-run
"uv run python scripts/audit_suite.py --only top80_fill --board docs" yourself to see the full sample
list). This is a serious misattribution bug class if real -- a lead could show another property's deed
reference or legal description. Find the fill/screen producer (grep for "deed_ref" assignment sites in
enrichment_*.py and the gis_fill/dot_ocr family) and trace EXACTLY how a value from parcel A's county
record ends up written onto parcel B's row. Pull 2-3 live violating examples and manually verify the
parcel ids really differ (not a normalization/formatting false-positive in the audit check itself).`,
  },
  {
    key: 'fill-screen-honest',
    prompt: `${PREAMBLE}

CHECK: top80-fill-screen-honest (scripts/audit_checks/top80_fill.py). Measures: a row whose screening
ledger claims it found a deed/value/legal-description block but the row carries no actual matching
field -- a dishonest "found" stamp (the ledger says success but nothing was actually attached).
LIVE: 83 violations, by kind: deed_found_no_block (30), value_found_no_value (46), legal_found_no_block
(7). Sample: Buncombe, Polk, Henderson, Mecklenburg. Find the screening ledger write site (grep for
"deed_found"/"value_found"/"legal_found" literal strings or the doc_ledger/screen_ledger module) and
trace why a "found" outcome can be recorded without the corresponding field landing on the row --
likely a code path that records success before confirming the write, or an exception between the two
steps that isn't caught. Pull 2-3 live violating rows to confirm this reproduces, not stale.`,
  },
  {
    key: 'fill-values-sane',
    prompt: `${PREAMBLE}

CHECK: top80-fill-values-sane (scripts/audit_checks/top80_fill.py). Measures: an assessed_value or
market_value filled by this group that is implausible (too low/high for a real property value).
LIVE: 37 violations: assessed_value_implausible (11, all Lincoln county per the sample), market_value_
implausible (26). Find the value-fill producer for Lincoln county specifically (grep for
"assessed_value_implausible" bound check logic in top80_fill.py for the exact threshold, then find
which scraper/enrichment writes Lincoln's assessed_value) and pull 2-3 live violating Lincoln rows to
see the actual bad values (off by a decimal/unit conversion? a totally wrong field read?).`,
  },
  {
    key: 'lien-sweep-name-fit',
    prompt: `${PREAMBLE}

CHECK: top80-lien-sweep-name-fit (scripts/audit_checks/top80_logan_harris.py, presumably). Measures: a
lien-sweep stamp marked "found" whose cited instrument does NOT actually name the row's owner --
a name-matching false positive.
LIVE: only 2 violations, sample parcel ids 4131-00-07-7763 and 5019-19-62-4188 (no county given in the
sample -- find it from the parcel ids on the board). Pull these 2 exact rows, read the lien-sweep stamp
and the instrument it cites, and the row's owner_name, to see exactly how the name-fit check was
satisfied incorrectly (common surname? substring match too loose? wrong row's instrument attached?).
With only 2 rows this may be an edge case worth a narrow fix, or may be inherent noise in fuzzy name
matching -- say which.`,
  },
  {
    key: 'sweep-county-silent',
    prompt: `${PREAMBLE}

CHECK: top80-sweep-county-silent (scripts/audit_checks/top80_logan_harris.py, presumably). Measures: a
swept county with >= 20 owner rows where NONE carry a sweep stamp at all -- the sweep never touched that
county despite having enough owner rows to be worth sweeping.
LIVE: this is the SECOND-LARGEST finding: 20 of 23 swept counties with qualifying owner-row volume have
ZERO sweep stamps. Counties: NC Beaufort, Burke, Caldwell, Camden, Caswell, Chowan, Cleveland, Currituck,
Dare, Duplin, Franklin, Gates, Henderson, Hertford, Hyde, Lincoln, Madison, Montgomery, Stanly; SC Oconee.
This smells like the SAME "round-robin starvation" / "never gets a turn" bug class found repeatedly
tonight in other sweep sources (budget exhausted by a few high-volume counties before low-priority ones
get even one attempt) OR a county-list/config gap (these 20 counties never actually enrolled in the
sweep's target list at all). Find the sweep's own module (grep for "top80_logan_harris" config / the
actual Logan/Harris-vendor lien or marriage sweep scraper(s)), check whether these 20 counties are even
in its county list, and if they are, check its budget/rotation allocation logic for a starvation pattern.
This is the kind of finding worth a careful, evidence-first investigation -- do not guess.`,
  },
  {
    key: 'other-marriage-bound',
    prompt: `${PREAMBLE}

CHECK: top80-other-marriage-bound (scripts/audit_checks/top80_register_other.py). Measures: a register
marriage-license block that sits outside its configured index county, or is otherwise malformed.
LIVE: 3 violations, all NC/Edgecombe. Find the marriage-license register producer (grep for
"marriage" in top80_register_other.py's config and the actual scraper that stamps these blocks), check
whether Edgecombe is a configured index county at all, and pull the 3 live violating rows to see the
exact malformation.`,
  },
  {
    key: 'court-feed-has-verifier',
    prompt: `${PREAMBLE}

CHECK: top80v-court-feed-has-verifier (scripts/audit_checks/top80_verify.py). Measures: a row an NC
Judgment Search scraper typed lis_pendens or divorce_notice must have a live verifier attached -- an
unverified court-feed signal is a trust gap.
LIVE: 3 violations: divorce_notice from counties_nc.nc_ecourts_divorce (2), lis_pendens from
counties_nc.nc_ecourts_lis_pendens (1). This matches [[project_nc_ecourts_endpoint_split]] context from
earlier work (NC eCourts Judgment Search JSON splits lis-pendens+divorce). Find the verifier registry
(grep for "lis_pendens"/"divorce_notice" verifier declarations in verification/verifiers/ or wherever
verifiers register their covered signals) and determine whether a verifier for these two scrapers' output
exists but isn't correctly declared/registered, or genuinely doesn't exist yet (needs to be built --
flag as needing owner prioritization if so, don't attempt a brand-new verifier yourself).`,
  },
  {
    key: 'valuation-hot-arv-supported',
    prompt: `${PREAMBLE}

CHECK: valuation-hot-arv-supported (scripts/audit_checks/valuation.py). Measures: a HOT-graded row
(the call list) whose published ARV has no support at all -- no cited comp sold within 2x of it, no
>=3-sale recorded basket it was priced from, no county value it sits within 0.4x-3.5x of. max is 0 per
the docstring (this check is meant to NEVER fire).
LIVE: exactly 1 violation: SC|Laurens|901-11-02-007. Pull this exact row's full valuation detail (comps,
county values, grade) via the detail sidecar (DETAIL_KEYS: comps and cama) and figure out why this one
HOT row's ARV lost all three forms of support -- a comps-pruning side effect? a county-value lookup
miss specific to Laurens SC? Since max=0, this is meant to be a hard guarantee -- treat it as a real bug
unless you find a clear, narrow, deliberate reason this one row is a legitimate edge case.`,
  },
  {
    key: 'valuation-comps-kind-fits-and-age',
    prompt: `${PREAMBLE}

CHECK (two related checks): valuation-comps-kind-fits and valuation-comps-age (scripts/audit_checks/
valuation.py). kind-fits: a row whose cited comps are ALL of a kind that doesn't fit the subject
(validation._validate_comps' rule: townhouse and single_family trade together, nothing else crosses).
LIVE: 17 violations: land<-single_family (13), land<-single_family,townhouse (1), single_family<-land
(3). Sample counties: Henderson (several), plus some board rows only identified by an "h:" hash id (no
plain county -- these may be in a different board partition, check published_rows()'s detail_keys).
age: a cited comp older than COMPS_CARRY_MAX_AGE_DAYS=365 with no age label; enrichment_comps.age_comps()
is supposed to prune/label these every comps phase. LIVE: 2 violations (older than 365 days, sample
h:787d00f1273da31d, h:6c18c800ba396d87). For BOTH: find enrichment_comps.py's age_comps() and the comp-
kind validation call site, pull the 2-3 live violating rows (resolving the "h:" hash ids via the detail
sidecar if needed), and determine if these are rows that predate the pruning logic (stale) or rows the
pruning logic is currently missing (real bug) -- re-running the SAME pruning function against the live
row data (without any code change) is the fastest way to tell, exactly like the block_binding ordering
bug was confirmed earlier tonight.`,
  },
]

const results = await pipeline(
  CLUSTERS,
  c => agent(c.prompt, { label: `investigate:${c.key}`, phase: 'Investigate', schema: FINDINGS_SCHEMA }),
  (finding, c) => {
    if (!finding || !finding.is_real_bug) return { cluster: c.key, finding, verdict: null }
    return parallel(
      Array.from({ length: 3 }, () => () =>
        agent(
          `Adversarially verify this audit finding from the foreclosure-scraper repo. Try hard to REFUTE
it -- read the exact file/line cited, re-run the check live if a command was given, and check whether
this is actually a stale-board artifact or deliberate design rather than a live code bug. Default to
refuted=true if you cannot personally confirm the root cause against live code/data.

CLUSTER: ${c.key}
CLAIMED FINDING: ${JSON.stringify(finding)}`,
          { label: `verify:${c.key}`, phase: 'Verify', schema: VERDICT_SCHEMA }
        )
      )
    ).then(votes => {
      const valid = votes.filter(Boolean)
      const refutedCount = valid.filter(v => v.refuted).length
      const survives = valid.length > 0 && refutedCount < 2
      return { cluster: c.key, finding, verdict: { survives, votes: valid } }
    })
  }
)

const survivors = results.filter(r => r && r.verdict && r.verdict.survives)
const refuted = results.filter(r => r && r.finding && r.finding.is_real_bug && (!r.verdict || !r.verdict.survives))
const notBugs = results.filter(r => r && r.finding && !r.finding.is_real_bug)

log(`${survivors.length} confirmed real bugs, ${refuted.length} refuted, ${notBugs.length} not bugs (stale/deliberate)`)

return { survivors, refuted, notBugs, all: results }
