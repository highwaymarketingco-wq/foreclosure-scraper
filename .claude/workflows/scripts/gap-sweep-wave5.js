export const meta = {
  name: 'gap-sweep-wave5',
  description: 'Wave 5 of the gap-list sweep: investigate the remaining 19 uninvestigated gap-matrix columns',
  phases: [
    { title: 'Investigate' },
    { title: 'Verify' },
  ],
}

const REPO = '/Users/cashhigh/foreclosure-scraper'

const SHARED_CONTEXT = `
Repo: ${REPO}
This repo runs scripts/gap_matrix.py to compute, per state/county/column, how many rows
are applicable and how many are actually filled (the "checked"/"positive" distinction),
producing docs/gap_matrix/gap_list_2026-10-16.csv (the most recent gap-list CSV, one row
per state/county/column, with an est_rows_affected number per row).

IMPORTANT prior lesson from this same sweep, earlier tonight: a column called vacant_lot
was initially thought to have a huge stale gap, but the real cause was that the
investigator (and before that, a human) used the WRONG applicability filter when
re-measuring it by hand - the column's real Spec had applies="all" (every row is
applicable, no exclusion), and once measured correctly using the Spec's own actual
applies= value, the published CSV number turned out to be exactly current, not stale.
Lesson: always read the column's actual Spec() definition in scripts/gap_matrix.py first
- its applies=, producers=, ledger=, scope, and kind fields - rather than assuming or
guessing a filter, even for a "quick" check. Two other columns investigated tonight
(heir_estate and lt_tax_lien_and_lt_tax_sale) produced literal placeholder/test output
instead of a real investigation - do not do that. If you cannot actually verify something
with a real check (reading code, querying the live board), say "inconclusive" and explain
exactly what you could not verify, rather than inventing numbers or filler text.

Also already fixed tonight and relevant background: nc_heir_estate_parcels.py (the
producer behind atty_heir_candidates / heir_estate / probate_heir-ledger columns) had a
real bug fixed earlier (commit 552ce3ae) that jumped atty_heir_candidates' hit rate from
29.66% to 68.2% once a fresh run landed. If your assigned column's gap turns out to trace
back to this SAME already-fixed producer and the same already-identified stale-CSV
mechanism (the published CSV predates the fix landing, not a new bug), say so explicitly
and mark it correctly_classified_non_bug (or already_fixed_elsewhere) rather than treating
it as a new finding needing a new code change.

To check a column's real current board-wide fill, you may query data/board/listings (or
whatever the live board storage format is - read scripts/gap_matrix.py's own loading code
if unsure how it loads the board) directly rather than guessing.
`

function investigatePrompt(title, columns, specLines, aggregateNumbers, extraHints) {
  return `You are investigating a cluster of related columns in the gap-matrix system of a real production repo. ${SHARED_CONTEXT}

Cluster: ${title}
Columns in this cluster: ${columns.join(', ')}

Their Spec() definitions in scripts/gap_matrix.py (read the full Spec for each - these are
truncated to the opening line, the rest continues on following lines in the file):
${specLines}

Current published gap-list CSV numbers (est_rows_affected, aggregated across all
state/county rows for each column) - the board currently has 437,170 total rows:
${aggregateNumbers}

${extraHints || ''}

Your job for EACH column in this cluster:
1. Read its full Spec() in scripts/gap_matrix.py (the applies=, producers=, ledger=,
   scope, kind fields matter - read the whole multi-line Spec call, not just the opening).
2. Figure out what actually produces/writes this column's data (grep for the producer
   file(s) named in producers=, or if it is ledger-based, read how ledger="X|Y|Z" columns
   get their checked/positive signal in gap_matrix.py's checked_columns()/positive_columns()
   functions).
3. Determine whether the published gap number (shown above) is CURRENT (a real, present-day
   gap needing a fix) or STALE (the CSV predates a fix that already landed, or was measured
   with a wrong applicability filter, or the producer simply has not been given a chance to
   run since some earlier change). Cross-check against the live board's actual current fill
   rate for that column if you can query it directly.
4. If it IS a real current gap: find the root cause (a bug in the producer, a bug in how
   gap_matrix.py credits "checked", a scope/applicability mismatch, a never-wired producer,
   a wall/blocker, a budget/timeout issue, etc.) and propose the exact fix - name the file,
   function, and the specific change needed. Do not write any code yourself in this task;
   just report the finding precisely enough that someone else can implement it directly
   from your report.
5. If it is NOT a real bug (stale CSV, already fixed, measured wrong, or working as
   designed by deliberate scope exclusion), say so and explain exactly why with evidence.

Classify each column as one of: real_bug_found, correctly_classified_non_bug,
already_fixed_elsewhere, inconclusive. Report one entry per column.`
}

const CLUSTER_SCHEMA = {
  type: 'object',
  properties: {
    cluster: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          column: { type: 'string' },
          classification: { type: 'string', enum: ['real_bug_found', 'correctly_classified_non_bug', 'already_fixed_elsewhere', 'inconclusive'] },
          evidence: { type: 'string' },
          root_cause: { type: 'string' },
          proposed_fix: { type: 'string' },
          estimated_impact_rows: { type: 'number' },
          file_and_function: { type: 'string' },
        },
        required: ['column', 'classification', 'evidence'],
      },
    },
  },
  required: ['cluster', 'findings'],
}

function verifyPrompt(finding) {
  return `You are adversarially verifying one finding from an earlier investigation in a real production repo. ${SHARED_CONTEXT}

The finding under review:
Column: ${finding.column}
Classification claimed: ${finding.classification}
Evidence given: ${finding.evidence}
Root cause claimed: ${finding.root_cause}
Proposed fix: ${finding.proposed_fix}
Estimated impact: ${finding.estimated_impact_rows}
File/function named: ${finding.file_and_function}

Try to REFUTE this finding. Independently re-check the claim: read the actual Spec() for
this column, read the actual file/function named, and if possible query the live board
directly rather than trusting the investigator's numbers. Be especially suspicious of:
literal placeholder/filler text instead of a real explanation (e.g. the word "test" or
"TODO" standing in for real content), a root cause that does not actually match what the
named file/function does when you read it yourself, an impact number with no traceable
source, or a claim that contradicts something you can directly verify is false.

Default to refuted=true if you cannot independently confirm the finding is both accurate
and real. Report your verdict with your own independent reasoning.`
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    column: { type: 'string' },
    refuted: { type: 'boolean' },
    reasoning: { type: 'string' },
  },
  required: ['column', 'refuted', 'reasoning'],
}

const CLUSTERS = [
  {
    title: 'vacancy_and_usps_vacancy (near-full-board gap, highest priority — check for a vacant_lot-style measurement trap first)',
    columns: ['vacancy', 'usps_vacancy'],
    specLines: '"vacancy": Spec(_S, "row", "code", ledger="vacant_structure", ...) -- line 823\n"usps_vacancy": Spec(_S, "county", "usps", producers=("enrichment_usps_vacancy.py",), ...) -- line 733',
    aggregateNumbers: 'vacancy: 437,120 of 437,170 total board rows (151 county-rows affected)\nusps_vacancy: 437,170 of 437,170 total board rows (148 county-rows affected, i.e. EVERY applicable row)',
    extraHints: 'These two numbers are each almost exactly the full board size. That is an extreme red flag for either a genuinely catastrophic near-100% gap (the single biggest finding of the whole night if real) or a measurement artifact exactly like the vacant_lot trap described above (wrong applies= filter, or the producer/ledger genuinely never having been wired/run at all, which is a different and more specific finding than "broken"). Read enrichment_usps_vacancy.py directly to see if it is even called anywhere in main.py\'s run(), and check vacant_structure ledger writes the same way.',
  },
  {
    title: 'storm_damage (massive single-column gap, second highest priority)',
    columns: ['storm_damage'],
    specLines: '"storm_damage": Spec(_S, "county", "disaster", producers=("enrichment_helene_damage.py",), ...) -- line 731',
    aggregateNumbers: 'storm_damage: 392,412 of 437,170 total board rows (145 county-rows affected)',
    extraHints: 'Note enrichment_helene_damage.py already came up tonight in a different context (asheville_helene.py scraper is in the no-retry-audit candidate list running in parallel right now) - check whether this gap is a downstream symptom of that scraper never producing input, or a separate bug in the enrichment step itself, or a scope issue (storm damage may only be applicable to WNC counties actually hit by Helene, not statewide - check applies= carefully).',
  },
  {
    title: 'probate (73k gap — check overlap with already-fixed heir/probate work)',
    columns: ['probate'],
    specLines: '"probate": Spec(_S, "county", "probate", applies="person", ledger="probate_heir", ...) -- line 820',
    aggregateNumbers: 'probate: 73,446 of 437,170 total board rows, applies="person" denominator (121 county-rows affected)',
    extraHints: 'This shares the probate_heir ledger with lt_estate_lead and lt_probate_notice (see other clusters) and with atty_heir_candidates/heir_estate, already fixed tonight via nc_heir_estate_parcels.py (commit 552ce3ae). Determine precisely whether this column\'s own gap is explained by that same already-shipped fix (stale CSV) or is a genuinely separate issue — applies="person" is a different denominator than heir_estate used, so check whether that denominator itself is computed correctly.',
  },
  {
    title: 'lt_elderly_disabled (108k gap, GIS-exemption feed type)',
    columns: ['lt_elderly_disabled'],
    specLines: '"lt_elderly_disabled": Spec(_S, "feed", "gis_exempt", ledger="elderly_disabled", ...) -- line 659',
    aggregateNumbers: 'lt_elderly_disabled: 108,771 of 437,170 total board rows (148 county-rows affected, i.e. nearly every county)',
    extraHints: 'This is a "feed"-scope ledger column fed by GIS exemption data (property tax exemption codes for elderly/disabled owners, most likely from each county\'s own parcel_cache / GIS layer rather than a dedicated scraper). Check parcel_cache.py and any gis_fill.py-adjacent code for an elderly/disabled exemption field, and check whether the elderly_disabled ledger is actually being written anywhere at all.',
  },
  {
    title: 'lt_estate_lead (26.5k gap, probate-ledger feed type)',
    columns: ['lt_estate_lead'],
    specLines: '"lt_estate_lead": Spec(_S, "feed", "probate", ledger="probate_heir|heir_roll|court_wall", verify_family="probate", doc="listing_type == estate_lead") -- line 658',
    aggregateNumbers: 'lt_estate_lead: 26,504 of 437,170 total board rows (148 county-rows affected)',
    extraHints: 'Same probate_heir ledger family as the probate cluster above - check whether this is the same already-fixed stale-CSV situation, or whether "listing_type == estate_lead" doc-filtering introduces a separate, still-unfixed issue.',
  },
  {
    title: 'lt_lis_pendens, lt_divorce_notice, lt_probate_notice (court/notice feed types, similar size, likely share a mechanism)',
    columns: ['lt_lis_pendens', 'lt_divorce_notice', 'lt_probate_notice'],
    specLines: '"lt_lis_pendens": Spec(_S, "feed", "court", ledger="foreclosure_rod|nc_ecourts_case|court_wall", ...) -- line 639\n"lt_divorce_notice": Spec(_S, "feed", "court", ledger="nc_ecourts_case|divorce", ...) -- line 653\n"lt_probate_notice": Spec(_S, "feed", "notices", statewide=NOTICES, ledger="probate_heir|court_wall", verify_family="probate", doc="listing_type == probate_notice") -- line 657',
    aggregateNumbers: 'lt_lis_pendens: 7,275 of 437,170 (101 county-rows)\nlt_divorce_notice: 7,252 of 437,170 (142 county-rows)\nlt_probate_notice: 6,038 of 437,170 (146 county-rows)',
    extraHints: 'All three are "feed" scope with a pipe-separated multi-source ledger= (meaning several different producers can each satisfy the same column). Investigate whether all the named ledger sources for each (nc_ecourts_case, divorce, court_wall, probate_heir, foreclosure_rod) are actually wired and running, or whether one of the pipe-separated alternatives is silently the only one that ever fires.',
  },
  {
    title: 'divorce_no_subsequent_deed, notice_service_defect, title_risk (small derived-scope signals, likely share a mechanism)',
    columns: ['divorce_no_subsequent_deed', 'notice_service_defect', 'title_risk'],
    specLines: '"divorce_no_subsequent_deed": Spec(_S, "derived", "rod", applies="divorced", ...) -- line 689\n"notice_service_defect": Spec(_S, "derived", "derived", applies="foreclosure", ...) -- line 800\n"title_risk": Spec(_S, "derived", "derived", applies="foreclosure", producers=("enrichment_title_risk.py",), ...) -- line 792',
    aggregateNumbers: 'divorce_no_subsequent_deed: 4,350 of 437,170, applies="divorced" (95 county-rows)\nnotice_service_defect: 2,313 of 437,170, applies="foreclosure" (75 county-rows)\ntitle_risk: 2,658 of 437,170, applies="foreclosure" producers=enrichment_title_risk.py (118 county-rows)',
    extraHints: 'These are all "derived" scope (computed from other already-collected signals, not a direct scrape target) and small relative to the board. Check each one\'s actual derivation logic for a bug (e.g. a condition that can never be true, a key lookup that is wrong), rather than assuming it is simply an uncollected-data gap.',
  },
  {
    title: 'lt_bankruptcy and bankruptcy_stay (bankruptcy pair)',
    columns: ['lt_bankruptcy', 'bankruptcy_stay'],
    specLines: '"lt_bankruptcy": Spec(_S, "feed", "federal", ledger="bankruptcy_stay", ...) -- line 664\n"bankruptcy_stay": Spec(_S, "row", "federal", applies="bankrupt", ledger="bankruptcy_stay", ...) -- line 703',
    aggregateNumbers: 'lt_bankruptcy: 1,002 of 437,170 (19 county-rows - note: only 19 counties even show as affected, far fewer than the ~148-159 most other columns show)\nbankruptcy_stay: 1,455 of 437,170, applies="bankrupt" (159 county-rows)',
    extraHints: 'lt_bankruptcy showing only 19 affected county-rows (vs the ~148-159 nearly every other column shows) is itself worth explaining - is that because most counties are already at 100% for this column (good), or because most counties were never even evaluated for it (a different kind of gap entirely, a scope/wiring issue)? Check both. This cluster also relates to the earlier-flagged unresolved rollback_exposure vendor mismatch and the national/courtlistener_bankruptcy.py and national/bankruptcy_rss_relief_from_stay.py scrapers currently also in the parallel no-retry-audit workflow - note any relevant overlap but do not duplicate that workflow\'s retry-bug work here; this investigation is about the gap_matrix column logic, not the scraper\'s network retry behavior.',
  },
  {
    title: 'lt_foreclosure_sale, lt_auction, lt_sheriff_sale, lt_reo, lt_hoa_sale (all near-zero gaps — verify these are genuinely near-complete, not broken/unwired and silently reporting zero)',
    columns: ['lt_foreclosure_sale', 'lt_auction', 'lt_sheriff_sale', 'lt_reo', 'lt_hoa_sale'],
    specLines: '"lt_foreclosure_sale": Spec(_S, "feed", "foreclosure", ledger="foreclosure_rod|foreclosure_sale_list|court_wall", ...) -- line 632\n"lt_auction": Spec(_S, "feed", "auction", ...) -- line 645\n"lt_sheriff_sale": Spec(_S, "feed", "notices", statewide=NOTICES, ...) -- line 635\n"lt_reo": Spec(_S, "feed", "reo", statewide=(("NC","HUD/HomePath/bank REO"),("SC","HUD/HomePath/bank REO")), ...) -- line 648\n"lt_hoa_sale": Spec(_S, "feed", "notices", statewide=NOTICES, doc="listing_type == hoa_sale", ...) -- line 650',
    aggregateNumbers: 'lt_foreclosure_sale: 839 of 437,170 (135 county-rows)\nlt_auction: 1 of 437,170 (115 county-rows)\nlt_sheriff_sale: 0 of 437,170 (148 county-rows)\nlt_reo: 20 of 437,170 (115 county-rows)\nlt_hoa_sale: 0 of 437,170 (147 county-rows)\n\nIMPORTANT: this project also has an established, deliberate gap pattern (see memory: "condemned gap NOT a bug", "jail_booking_new gap NOT a bug") where a near-zero number is sometimes the CORRECT, expected result (no source exists for most counties, by design) rather than a bug. Do not assume near-zero automatically means broken - but do not assume it automatically means fine either. Check which case applies for each of these 5.',
    extraHints: 'A near-zero gap could mean either (a) genuinely excellent coverage (good), or (b) the checked_columns()/positive_columns() logic for these never credits anything as "checked" so the gap denominator itself is wrong (the measurement never runs, so it always reports near-zero gap regardless of true state) - these are very different findings. Check both possibilities directly for each column, especially lt_sheriff_sale and lt_hoa_sale which show EXACTLY zero across nearly every county.',
  },
]

phase('Investigate')
const investigated = await pipeline(
  CLUSTERS,
  (c) => agent(investigatePrompt(c.title, c.columns, c.specLines, c.aggregateNumbers, c.extraHints), { label: `investigate:${c.columns[0]}`, phase: 'Investigate', schema: CLUSTER_SCHEMA })
)

const allFindings = investigated.filter(Boolean).flatMap((r) => r.findings)
const realBugs = allFindings.filter((f) => f.classification === 'real_bug_found')
log(`Investigation done: ${allFindings.length} column findings, ${realBugs.length} flagged real_bug_found`)

phase('Verify')
const verified = await parallel(
  realBugs.map((f) => () => agent(verifyPrompt(f), { label: `verify:${f.column}`, phase: 'Verify', schema: VERDICT_SCHEMA }).then((v) => (v ? { ...f, verdict: v } : null)))
)

const survivors = verified.filter(Boolean).filter((v) => !v.verdict.refuted)
const refuted = verified.filter(Boolean).filter((v) => v.verdict.refuted)
const nonBugs = allFindings.filter((f) => f.classification !== 'real_bug_found')

return { allFindings, survivors, refuted, nonBugs }
