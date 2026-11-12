export const meta = {
  name: 'gap-sweep-wave6-audit-suite',
  description: 'Triage the highest-volume failing checks from the full scripts/audit_suite.py run (beyond additions/unwired_enrichers, already handled)',
  phases: [
    { title: 'Investigate' },
    { title: 'Verify' },
  ],
}

const REPO = '/Users/cashhigh/foreclosure-scraper'

const SHARED_CONTEXT = `
Repo: ${REPO}
scripts/audit_suite.py streams the live published board (docs/) through every check
module in scripts/audit_checks/*.py in one pass, each one testing a specific data
invariant with its own tolerance ("max" violations allowed before it reports NO). A full
run just now (uv run python3 scripts/audit_suite.py --no-out) found roughly 65 failing
checks; this task covers one cluster of them.

IMPORTANT, read before judging anything: these checks test DATA CONSISTENCY/correctness
invariants, not simple column-presence gaps. Several of tonight's earlier investigations
(in a separate, already-completed pass) found that some "violations" in a nearby check
module (unwired_enrichers) were not bugs at all but symptoms of a well-understood,
already-escalated systemic issue (the pipeline's per-phase time budgets can't always
reach every row on one run, see scripts/enrich_board.py's _run_async/_run_offline time
caps throughout). Do not assume every violation here is a fresh independent bug. ALSO: a
nonzero "violation" count is sometimes a TRACKED, INTENTIONAL category the check's own
author expected to stay small or zero (read the check's own code and the words it uses
very literally -- e.g. "fallback_point" suggests a deliberate degraded-match tier that
exists by design; whether its current COUNT is a regression or just the check's "max"
tolerance being stale/wrong for today's board size is exactly what you must determine,
not assume either way).

For each check in your cluster:
1. Read the check's full implementation in scripts/audit_checks/<module>.py (the
   describe string plus the actual feed()/finish() logic) to understand EXACTLY what
   it tests and why the author considered a violation bad.
2. Read whatever upstream code actually produces the condition being flagged (the
   relevant enrichment/scraper/scorer file) to find the real root cause.
3. Classify: real_bug_found (a genuine regression or defect that should be fixed),
   correctly_classified_non_bug (working as designed, or a stale/wrong tolerance in the
   check itself rather than a data problem -- say which), or needs_owner_decision (the
   right answer depends on a judgment call about data retention, scope, or tradeoffs you
   cannot make yourself).
4. If real_bug_found: name the exact file/function and the exact fix needed. Do not
   write code yourself in this task -- report precisely enough that someone else can
   implement it directly from your report.

Be honest about "inconclusive" when you cannot verify something directly (read code,
query the board) rather than guessing or padding with filler text.
`

function investigatePrompt(title, checksBlock) {
  return `You are investigating a cluster of related data-invariant check failures in a real production repo. ${SHARED_CONTEXT}

Cluster: ${title}

The failing checks in this cluster, with their current violation counts, tolerance
("max" allowed), and the audit_suite's own one-line description/sample for each:
${checksBlock}

Report one finding entry per check listed above.`
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
          check: { type: 'string' },
          classification: { type: 'string', enum: ['real_bug_found', 'correctly_classified_non_bug', 'needs_owner_decision', 'inconclusive'] },
          evidence: { type: 'string' },
          root_cause: { type: 'string' },
          proposed_fix: { type: 'string' },
          file_and_function: { type: 'string' },
        },
        required: ['check', 'classification', 'evidence'],
      },
    },
  },
  required: ['cluster', 'findings'],
}

function verifyPrompt(finding) {
  return `You are adversarially verifying one finding from an earlier investigation in a real production repo. ${SHARED_CONTEXT}

The finding under review:
Check: ${finding.check}
Classification claimed: ${finding.classification}
Evidence given: ${finding.evidence}
Root cause claimed: ${finding.root_cause}
Proposed fix: ${finding.proposed_fix}
File/function named: ${finding.file_and_function}

Try to REFUTE this finding. Independently re-read the check's own code in
scripts/audit_checks/, re-read the file/function named as the root cause, and if
possible re-query the live board directly rather than trusting the investigator's
numbers. Be especially suspicious of: literal placeholder/filler text instead of a real
explanation, a root cause that does not actually match what the named file/function does
when you read it yourself, or a claim that contradicts something you can directly verify
is false.

Default to refuted=true if you cannot independently confirm the finding is both accurate
and real. Report your verdict with your own independent reasoning.`
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    check: { type: 'string' },
    refuted: { type: 'boolean' },
    reasoning: { type: 'string' },
  },
  required: ['check', 'refuted', 'reasoning'],
}

const CLUSTERS = [
  {
    title: 'block_binding -- data-provenance "fallback_point" and "shared copy" blocks (scripts/audit_checks/block_binding.py), the single biggest cluster by volume',
    checksBlock: `
- block-binding-family-gis: checked 219,134, violations 899, max 0. "cama:fallback_point 899" -- 899 rows where the CAMA/GIS binding fell back to a point-only match instead of a confirmed parcel match.
- block-binding-family-deed-sale: checked 143,028, violations 4,259, max 0. "deed_chain:fallback_point 4,259, last_sale:fallback_point 12" -- by far the largest single number in this cluster.
- block-binding-family-photo: checked 90,500, violations 97, max 0. "vision:fallback_point 97".
- block-binding-family-code-site: checked 96,805, violations 180, max 0. "septic:other_address 180" -- all sample rows are Buncombe septic records bound to a different address than the row's own.
- block-binding-a-shared-copy: checked 314,246, violations 12,447, max 25. "copies 12447" -- far exceeds the stated tolerance of 25; this is either a massive genuine regression in how "shared copy" (duplicate-property fusion) is tracked, or the check's own "max 25" tolerance is simply wrong for a board this size now.
- block-binding-c-other-parcel: checked 437,170, violations 180, max 0. "septic 180" -- looks like the same 180 septic rows as family-code-site, just counted a different way.
- block-binding-fallback-point: checked 437,170, violations 5,161, max 0. "deed_chain 4,259, cama 844, vision 58" -- the aggregate fallback-point count across all binding families; note 4,259 deed_chain fallback_point here vs 4,259 in family-deed-sale above -- likely literally the same underlying rows counted by two different checks in this file.
- block-binding-e-parcel-two-counties: checked 221,272, violations 434, max 400. "parcel_in_two_counties 434" -- only just over its max of 400 (434 vs 400), a much smaller miss than the others above.
`,
  },
  {
    title: 'tax_checkers_2 -- tax claims without a live checker/verifier (scripts/audit_checks/tax_checkers_2.py), the single largest raw violation count found',
    checksBlock: `
- tax-claim-has-checker: checked 146,384, violations 18,920, max 1,200. By county: NC:Davidson 3200, NC:Duplin 2902, NC:Hoke 2829, NC:Lee 2703, NC:Rowan 2695, NC:Pasquotank 1804, SC:York 844, NC:Jones 668, NC:Person 593, NC:Caswell 482, SC:Beaufort 45, SC:Chester 28. This looks concentrated in a specific set of counties/sources rather than spread evenly -- check whether these counties share a missing/broken tax-checker wiring (similar to tonight's already-fixed tax_binding_bug and column_source_silent_death patterns) versus a legitimately large but expected backlog.
`,
  },
  {
    title: 'source_completeness -- per (source, county) staleness and floor checks (scripts/audit_checks/source_completeness.py)',
    checksBlock: `
- source-county-refreshed: checked 376,393, violations 74, max 0. "(source, county) cells with >= 20 rows where more than 50% of rows missed 2+ runs in a row or are carryover replays" -- 44,787 total stale rows across the 74 flagged cells. Sample cells: public_notices.gannett_obituaries Buncombe|NC 36/36 stale, public_notices.funeral_home_rss Wilson|NC 20/20, Williamsburg|SC 20/20, Orangeburg|SC 20/20 -- entire cells 100% stale, suggesting these specific sources may have stopped running for these counties entirely, not just slowed down.
- source-county-floor: checked 261,776, violations 6, max 0. "high-value (source, county) cells holding < 50% of their rows on the baseline board, or high-value sources with no rows" -- 5,106 baseline rows missing. Samples: counties_generic.arcgis_distress.greenville_unpaid_tax_parcels Greenville|SC 831/2722 (down to 31% of baseline), counties_generic.arcgis_distress.lincoln_code_violations Lincoln|NC 7/62 (11%), counties_nc.brunswick_legal_notices 0/5 rows (completely zero).
- source-cap-not-hit: checked 25,309, violations 1, max 0. "row counts equal to a scraper's hard cap (the cap bound: rows were cut)" -- counties_nc.nc_heir_estate_parcels Washington|NC exactly at its 400/county cap, meaning real rows may be getting truncated there.
`,
  },
  {
    title: 'pipeline-grade-equity-current -- scorer grade note vs published equity mismatch (scripts/audit_checks/pipeline.py)',
    checksBlock: `
- pipeline-grade-equity-current: checked 437,161, violations 3,142, max 0. "the grade's equity note matches the published raw.equity (graded after equity)" -- by: "equity note, no published equity" 3,142. Samples all Greenville/Gaston parcels. This suggests the scorer is writing an equity-related note into the grade for rows that have NO raw.equity block at all -- either a phase-ordering bug (scored before equity was computed) or equity enrichment silently not running for these rows.
`,
  },
  {
    title: 'drops_lineage -- rows dropped/withheld and why (scripts/audit_checks/drops_lineage.py)',
    checksBlock: `
- drops-short-parcel-county-native: checked 34,845, violations 1, max 0. "no row loses a county-native short parcel id to the 7-character floor" -- 1 Cleveland county row (parcel 7877) lost to a length-floor rule that shouldn't apply to it.
- drops-dateless-filtered-source: checked 371,670, violations 1,623, max 25. "dateless rows from a source _active_only drops when dateless (their re-scrape is filtered, the published copy can only age out)" -- counties_nc.polk_tax 1,622, newspapers.index_journal 1. Note this may directly relate to the no-retry-audit-53 workflow running in parallel right now (polk_tax being dateless and filtered); do not duplicate that workflow's retry-bug work, this is about the drop/age-out LOGIC specifically, not network retries.
- drops-county-blank-source: checked 437,170, violations 675, max 25. "rows with no county come only from feeds that have none by nature" -- flagged counts across several sources that normally DO have a county (echovita_obituaries, sc_dew_lien_registry, nc_notices_counties, spartanburg_condemned, bankruptcy_rss_relief_from_stay) producing blank-county rows when they shouldn't structurally need to.
- drops-marker-bounds: checked 437,170, violations 1, max 0. "each drop/withdraw marker stays under its row-count bound" -- situs_nulled 14,627 > its stated bound of 13,000.
- drops-low-value-parcel: checked 401, violations 2, max 0. "a low county value is kept beside the low_value_parcel flag, never as tax_value, and carries no ARV" -- 2 parcels (9794-36-4500-00000, 0627-85-4307-00000) still carry tax_value when they shouldn't.
`,
  },
  {
    title: 'phones_lost -- Lincoln County AKPAR-source phone/account key issues (scripts/audit_checks/phones_lost.py)',
    checksBlock: `
- phones-lincoln-akpar-unkeyed: checked 1,104, violations 10, max 0. national.courtlistener_bankruptcy 8, counties_nc.nc_ecourts_lis_pendens 2, all NC:Lincoln.
- phones-lincoln-akpar-duplicate: checked 1,022, violations 203, max 0. Samples are all "NC:Lincoln:account NNNNN" -- a large number of duplicate account-keyed rows specific to Lincoln county's AKPAR-sourced data.
`,
  },
  {
    title: 'documents_images -- vision/OCR document processing coverage and photo-path integrity (scripts/audit_checks/documents_images.py)',
    checksBlock: `
- docs-processed-has-ledger-entry: checked 21,945, violations 160, max 0. "every document / image read on a row has a processed-documents ledger entry" -- vision:national.landandfarm 40, vision:counties_nc.buncombe_delinquent_tax 20, vision:counties_nc.buncombe_elderly 18, vision:counties_sc.sc_public_index_lis_pendens 15, and more.
- docs-per-lead-doc-outcome: checked 230, violations 93, max 4. "a row's own notice document is read or has a recorded outcome" -- counties_sc.sc_des_brownfields 57 (the largest single contributor), counties.column_legal_notices 12, counties_sc.anderson_acpass_deeds 9.
- docs-roster-rows-read: checked 6,410, violations 116, max 0. "a row lacking an address whose roster PDF the aggregate pass has a ledger outcome for" -- counties_sc.fairfield_overage_claims 59, counties_sc.calhoun_overage_claims 29, counties_sc.charleston_mie 17; note says "7 rosters never read".
- docs-dot-county-attempted: checked 11, violations 4, max 0. "every free deed-image county with eligible rows has dot_ocr ledger entries" -- NC:McDowell (3,358 eligible), NC:Mitchell (561 eligible), SC:Laurens (3,237 eligible), SC:Spartanburg (18,517 eligible) have ZERO dot_ocr ledger entries despite large eligible pools -- worth checking if dot_ocr is even enabled/running for these (recall scripts/enrich_board.py has dot_ocr explicitly SKIPPED with a comment "causes OOM kill, disabled to prevent enrichment crash" -- check if that's the whole explanation here).
- images-hot-warm-graded: checked 11,011, violations 1,294, max 550. "HOT/WARM rows with a gradable image carry a vision report or a vision ledger outcome" -- note says "other tiers: 14,341 of 27,174 gradable rows unread (VISION_MAX_LISTINGS bounds a run)" -- this strongly suggests the same already-known per-run budget/time-cap pattern (VISION_MAX_LISTINGS), not a new bug; confirm or refute this directly.
- images-relative-photo-present: checked 5,571, violations 1,377, max 0. "every dashboard-hosted photo path a row names exists under docs/" -- counties_sc.horry_delinquent_xlsx:streetview 406, counties_nc.transylvania_delinquent_tax:streetview 133, counties_sc.berkeley_paystar_tax:streetview 123 -- these are rows naming a streetview photo PATH that does not actually exist on disk, a real broken-link risk for the dashboard.
`,
  },
]

phase('Investigate')
const investigated = await pipeline(
  CLUSTERS,
  (c) => agent(investigatePrompt(c.title, c.checksBlock), { label: `investigate:${c.title.split(' --')[0]}`, phase: 'Investigate', schema: CLUSTER_SCHEMA })
)

const allFindings = investigated.filter(Boolean).flatMap((r) => r.findings)
const realBugs = allFindings.filter((f) => f.classification === 'real_bug_found')
log(`Wave 6 investigation done: ${allFindings.length} check findings, ${realBugs.length} flagged real_bug_found`)

phase('Verify')
const verified = await parallel(
  realBugs.map((f) => () => agent(verifyPrompt(f), { label: `verify:${f.check}`, phase: 'Verify', schema: VERDICT_SCHEMA }).then((v) => (v ? { ...f, verdict: v } : null)))
)

const survivors = verified.filter(Boolean).filter((v) => !v.verdict.refuted)
const refuted = verified.filter(Boolean).filter((v) => v.verdict.refuted)
const nonBugs = allFindings.filter((f) => f.classification !== 'real_bug_found')

return { allFindings, survivors, refuted, nonBugs }
