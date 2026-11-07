export const meta = {
  name: 'no-retry-audit-53',
  description: 'Triage and fix bare-network-call no-retry bugs across 53 dateless scrapers',
  phases: [
    { title: 'Investigate' },
    { title: 'Fix' },
    { title: 'Verify' },
  ],
}

const REPO = '/Users/cashhigh/foreclosure-scraper'

const PATTERN_DESC = `
The proven fix pattern (already shipped successfully 4 times tonight in this same repo,
each time with full passing tests): wrap the vulnerable network call in an AsyncRetrying
block from the tenacity library, retrying ONLY transport/timeout errors, never a real
bad HTTP status or an HTTP-200-with-error-body response:

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
async for attempt in AsyncRetrying(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException, TimeoutError)),
    reraise=True,
):
    with attempt:
        r = await http.get(...)  # or .post(...), whatever the real call is

The underlying http_client.client() helper's own docstring says callers must wrap their
own retries - it does not do this itself. A bare call with zero retry wrapper means a
single transient network blip (a connection reset, a timeout) permanently zeroes that
scrape's whole result for this run, and because these 53 files are all registered in
main.DATELESS_OK_SOURCES (no fallback date window), a zeroed run cannot self-heal later -
it just silently reports an empty/healthy result forever until someone notices by hand.
This exact bug shape has already been confirmed and fixed in: a Column legal-notice API
scraper, spartan_weekly_legals.py, and the shared arcgis_webmap.query_features() function.
`

function investigatePrompt(file) {
  return `You are auditing ONE Python file in a real production repo for a specific, already-proven bug shape. Read this file only, do not edit anything:

${REPO}/${file}

${PATTERN_DESC}

Your job: determine whether THIS file has that same bug. Specifically:

1. Find every network call this file makes (http.get/.post, client().get/.post, httpx calls, requests to an external site or API). There may be more than one call site.
2. For each call site, determine: is it already wrapped in some retry mechanism (an AsyncRetrying block, a manual for-loop retry with sleep/backoff, a decorator like @retry, or anything that re-attempts on a transient failure)? If a shared helper it calls into (e.g. a project-local http client wrapper) already does this internally, say so and name that helper - do not just assume it is unprotected because you do not see "AsyncRetrying" as a literal string in THIS file.
3. If NOT already protected: determine the call's blast radius. Is it a single request whose failure zeroes the file's entire scrape output (single point of failure - e.g. one page/listing fetch, one search submission, one API call that the whole scrape depends on)? Or does the file make many independent per-item requests in a loop, where one item's failure only drops that one item and the rest of the scrape still succeeds (lower severity, but still worth the same fix for robustness)? Or does it make NO real external network call at all (e.g. it only reads a local file, or delegates entirely to another already-covered module)?
4. If there IS a real, currently-unprotected call site, give the exact function name and, if you can tell from reading the file, the approximate line number or a short unique snippet of the line itself so a fix can find it precisely afterward.

Be skeptical of your own first impression - actually read the full file, not just the top, since the real network call is sometimes buried inside a helper function defined later in the same file or imported from very nearby.

Report your findings as structured output.`
}

const INVESTIGATE_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    has_real_unprotected_network_call: { type: 'boolean', description: 'true only if there is a genuine, currently-unretried network call this file depends on' },
    already_protected_reason: { type: 'string', description: 'if false because it is already protected, name the mechanism/helper; else empty string' },
    call_pattern: { type: 'string', enum: ['single_point_of_failure', 'per_item_loop', 'no_real_network_call', 'already_protected'] },
    call_site_function: { type: 'string' },
    call_site_hint: { type: 'string', description: 'approximate line number and/or a short unique snippet of the vulnerable call line' },
    reasoning: { type: 'string' },
  },
  required: ['file', 'has_real_unprotected_network_call', 'call_pattern', 'reasoning'],
}

function fixPrompt(inv) {
  return `You are fixing ONE confirmed bug in a real production repo. An investigation already confirmed this file has an unprotected network call matching a proven bug shape:

File: ${REPO}/${inv.file}
Call site function: ${inv.call_site_function}
Call site hint: ${inv.call_site_hint}
Investigator's reasoning: ${inv.reasoning}

${PATTERN_DESC}

Your job, scoped STRICTLY to this one file plus one new test file:

1. Read the file fully first to confirm the call site and see the real imports already present (httpx, tenacity, etc. - some may already be imported for other reasons).
2. Add the missing tenacity import if not already present (AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter).
3. Wrap ONLY the confirmed vulnerable call (or calls, if there is more than one genuinely unprotected one) in the exact proven AsyncRetrying pattern shown above. Keep the wrapped code's actual request logic identical - you are only adding retry cushioning around it, not changing what is requested or how the response is parsed. Do not touch any other function or any other file.
4. Write ONE new test file at ${REPO}/tests/ named test_<module_basename>_retry.py (snake_case, derived from this file's own basename) that proves the fix, modeled on this existing proven test file in the same repo (read it for the exact shape and fixture style before writing yours): ${REPO}/tests/test_arcgis_webmap_query_features_retry.py
   Your test must cover, at minimum: (a) a transient transport/timeout error is retried and then succeeds, (b) a transient error that never clears still raises after the retry budget is exhausted (not an infinite hang), (c) a real non-transport HTTP error status is NOT retried (fails immediately on attempt 1). Use monkeypatch to make backoff waits fast in tests, exactly like the reference test file does.
5. Run this new test file with pytest and make sure it passes. Also run the full existing test file for this module if one already exists (same basename pattern) to make sure you have not broken anything.
6. Do NOT run git add, git commit, or git push. Do NOT edit any file other than the one target file and the one new test file. Do NOT touch docs/, scripts/, or any other scraper file.

Report back: whether you actually made the fix (false if on closer reading you conclude the investigator was wrong and there is no real bug - explain why, and make no edit in that case), the exact test file path you created, and the pytest result.`
}

const FIX_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    fixed: { type: 'boolean' },
    test_file_written: { type: 'string' },
    pytest_result: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['file', 'fixed', 'notes'],
}

function verifyPrompt(fix) {
  return `You are adversarially reviewing a code change in a real production repo, before it gets committed. Someone claims to have fixed a missing-retry bug in:

${REPO}/${fix.file}

Their own report: fixed=${fix.fixed}, test_file_written=${fix.test_file_written}, pytest_result=${fix.pytest_result}, notes=${fix.notes}

Run: cd ${REPO} && git diff -- ${fix.file} ${fix.test_file_written}
to see the actual change, then verify:

1. Is the diff MINIMAL and scoped only to adding retry cushioning (an AsyncRetrying wrap plus the needed import) around a real network call, with no unrelated changes, no changed request logic, no changed response parsing?
2. Does the new test file actually exist and actually exercise the retry behavior (not a trivial no-op test, not literal placeholder content like "test"/"TODO")? Re-run it yourself: cd ${REPO} && python -m pytest ${fix.test_file_written} -q
3. Does the retry correctly exclude real HTTP error statuses and HTTP-200-with-error-body responses from being retried (only transport/timeout errors should retry)?
4. Default to refuted=true if anything is unclear, the diff touches more than the one intended call site, the test does not actually pass when you run it yourself, or the claimed fix does not match what the file actually needed.

Report a verdict.`
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    refuted: { type: 'boolean' },
    reasoning: { type: 'string' },
  },
  required: ['file', 'refuted', 'reasoning'],
}

phase('Investigate')
const files = args
const investigated = await parallel(
  files.map((file) => () => agent(investigatePrompt(file), { label: `investigate:${file.split('/').pop()}`, phase: 'Investigate', schema: INVESTIGATE_SCHEMA }).then((r) => (r ? { ...r, file } : null)))
)

const confirmed = investigated.filter(Boolean).filter((r) => r.has_real_unprotected_network_call)
log(`Investigation done: ${confirmed.length}/${files.length} files confirmed as real unprotected-network-call bugs`)

phase('Fix')
const fixed = await parallel(
  confirmed.map((inv) => () => agent(fixPrompt(inv), { label: `fix:${inv.file.split('/').pop()}`, phase: 'Fix', schema: FIX_SCHEMA }).then((r) => (r ? { ...r, file: inv.file } : null)))
)
const realFixes = fixed.filter(Boolean).filter((f) => f.fixed)
log(`Fix stage done: ${realFixes.length}/${confirmed.length} confirmed bugs actually fixed with a passing test`)

phase('Verify')
const verified = await parallel(
  realFixes.map((fix) => () => agent(verifyPrompt(fix), { label: `verify:${fix.file.split('/').pop()}`, phase: 'Verify', schema: VERDICT_SCHEMA }).then((v) => (v ? { ...fix, verdict: v } : null)))
)

const survivors = verified.filter(Boolean).filter((v) => !v.verdict.refuted)
const refutedList = verified.filter(Boolean).filter((v) => v.verdict.refuted)
const nonBugs = investigated.filter(Boolean).filter((r) => !r.has_real_unprotected_network_call)
const notFixed = fixed.filter(Boolean).filter((f) => !f.fixed)

return { total: files.length, confirmed: confirmed.length, fixed: realFixes.length, survivors, refutedList, nonBugs, notFixed }
