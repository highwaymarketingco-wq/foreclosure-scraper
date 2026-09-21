# Dashboard fixes, 2026-09-21

Front-end fixes for the findings F2, F3, F13, F15, F19 (and the F8 address label) in
`docs/audit_signal_logic_2026-09-21.md`, plus four changes for moving the board to a private
host. Files touched: `docs/dashboard.js`, `docs/index.html`, `docs/premium.css`,
`docs/manifest.json`, new `tests/js/lead_state.test.mjs`, `tests/js/io_guard.test.mjs`,
`tests/js/phone_gate.test.mjs` and `tests/test_dashboard_lead_state_js.py`. No Python file was
edited. Nothing was committed.

Line numbers are `docs/dashboard.js` as of this write and will drift; the function names are
stable. The logic lives in three marked regions, `BEGIN/END LEAD-STATE` (1424 to 2058),
`BEGIN/END IO-GUARD` (68 to 203) and `BEGIN/END PHONE-GATE` (1380 to 1422). All are pure (no
DOM, no fetch), and the node tests slice them out of the shipped file and run them under `vm`, so
the code under test is the code that ships.

## What the board looks like today (measured in the browser on the real slim payload)

170,066 leads loaded from `docs/listings_slim.json.gz`, 633 MB JS heap, no console errors. Counts
below are from running the new functions over `LISTINGS` at 13:15 on 2026-09-21:

| Measure | Count |
|---|---|
| leads carrying a `raw.upset_bid` block | 237 |
| ... of which stored `in_window: true` | 182 |
| ... of which actually open by their dates today | 7 |
| stored "open" windows that the dates say are closed | 175 |
| sale date in the past (badge, demoted in default sort) | 48,935, of which 47,163 are `tax_lien` rows |
| presumed withdrawn (`auction_status`, `stale_case` or `pulled_sale`) | 4,460 |
| foreclosure-type leads with a bankruptcy match (shown as stayed) | 74 |
| live deadline of any kind / inside 45 days | 5,358 / 2,167 |
| no street address (now says "no property address") | 34,010 |
| leads whose old "N signals" chip showed 2+ but have fewer than 2 categories | 37,800 |
| leads with 2+ distinct categories (new chip) | 9,095 |
| leads leaning on a name match (incarceration, bankruptcy, court divorce, name-resolved) | 1,014 |
| default-sort group 1 (demoted) / 2 / 3 (live deadline inside 45 days) | 51,953 / 115,946 / 2,167 |
| HOT leads in the demoted group | 582 of 2,081 |

## Decisions that need the lead's eye

1. **Sale-date-passed demotion is large.** 48,935 leads (28.8%) have a past sale date, and
   47,163 of them are `tax_lien` rows, not foreclosure sales. The brief said to demote them, so
   they sit below every lead with no clock (group 1 in `leadClock`). If a delinquent-tax row's
   `sale_date` is a stale annual date rather than an auction that ended, exempting `tax_lien` is
   one condition in `leadClock` (`else if (salePassed && !live) group = 1`). 582 HOT leads are
   demoted today.
2. **The slim payload does not carry `bankruptcy_stay`, `pulled_sale`, `sale_date_passed`,
   `divorce`, `incarceration` or `resolved_from_name`.** `tests/test_board_slim.py::
   test_slim_allowlist_matches_client` pins `_LEAN_*` in `dashboard.js` to `_SLIM_*` in
   `web_artifact.py`, and I may not edit the Python side, so I did not touch `_LEAN_*` for these (the
   phone gate is the one deliberate exception, see item 8). The
   dashboard works from what slim does carry: `sale_date` and `upset_bid_deadline` (dates, so
   passed and closed are computed), `auction_status` and `raw.stale_case` (presumed withdrawn),
   `raw.bankruptcy` (stay, see F3), `raw.name_resolution` and the stack's signal names. The
   stored blocks are read where they exist (desktop fat board, detail shard). To get the stored
   `bankruptcy_stay` and `pulled_sale` on phones, add both to `_SLIM_RAW` and `_LEAN_RAW` in the
   same edit, appended last, as `"*"`.
3. **"Live deadline" for sorting means inside 45 days** (`CLOCK_SORT_HORIZON_DAYS`, the existing
   Closing Soon window). A redemption date 300 days out otherwise outranks a HOT lead with no
   date. Beyond 45 days a lead sorts by tier then grade. `deadlineInfo` itself still returns any
   live deadline, as before.
4. **A stayed sale cannot lead the queue.** A lead with a bankruptcy stay is group 2 even with a
   sale in 5 days. It still gets the days pill and the SALE STAYED tag.
5. **`stageOf` still routes `listing_type === "foreclosure_sale"` to the foreclosure stage
   whatever the date**, and any sale within the last 14 days. Only the `raw.upset_bid` rule
   changed, as briefed. A foreclosure with a sale 200 days ago is in the stage but carries the
   badge and is demoted.
6. **Estimated upset window is sale date + 14 days**, mirroring
   `enrichment_upset_bid.UPSET_BID_WINDOW_DAYS`. It is only used when a window is tagged open and
   no `upset_bid_deadline` exists, and it is labelled estimated. The old panel badge hard-coded
   10 days and ignored `raw.upset_bid`, so it disagreed with the stage filter.
7. **`manifest.json` `id` is now `"./"`.** Per the manifest spec a relative `id` resolves against
   the origin, so on the GitHub Pages project subpath the install identity becomes the account
   root. Harmless unless another project site on the same account also uses `"./"`.
8. **(Resolved: the ops agent landed it and the test passes.) `tests/test_board_slim.py::
   test_slim_allowlist_matches_client` was red until `_SLIM_RAW["owner_phone"]` matched.** `_LEAN_RAW.owner_phone` in `dashboard.js` is already the
   seven-key tuple the phone gate asked for; `web_artifact.py` still has the three-key one
   (checked at 13:40). `owner_phone` is the only difference the test reports.

## Findings

### F2 and F15: closed windows, frozen counters

- `stageOf` (2111): a lead is in the foreclosure stage on `raw.upset_bid` only when
  `upsetBidState(l, now).open`. An `upset_bid` block whose `in_window` is not exactly `true` is
  closed, including the empty `{}` that slim emits. Even with `in_window: true`, the window is
  closed once its deadline (`upset_bid_deadline`, else sale date + 14 d) is behind today.
- `upsetBidState` (1568), `saleClock` (1536), `redemptionState`, `leadClock` (1714): open or
  closed, days left, sale date passed and redemption are all computed from the dates against
  today's local calendar day. A date is a calendar day (first ten characters), so a 00:00 sale
  date cannot flip a day depending on the viewer's timezone.
- No code reads `.days_remaining`, `.sale_date_passed` or `.sale_date_passed_days` any more
  (`_LEAN_RAW` still names `days_remaining` because the parity test requires it). The only
  `.in_window` read is the veto inside `upsetBidState`. A test enforces both.
- Text comes from the dates: "sale date passed N days ago", "window closed Sep 2",
  "redemption ends Dec 31", "upset-bid window open, closes Sep 27, 6 days left" (`clockBadges`,
  1708).
- Detail panel: the "Upset-bid window: OPEN (8d left)" row and the hard-coded 10-day NC badge
  are replaced by the computed clock (row in the Deeds panel, clock block under the badges).
  Real example on the slim board: a lead stored `{in_window: true, days_remaining: 8}` with
  deadline 2026-09-02 read "OPEN (8d left)" on 2026-09-21. It now reads "window closed Sep 2".
- CSV: `days_to_auction` is a calendar-day count from `sale_date` so it agrees with the pill, and
  a new last column `clock_status` carries the clock text.

### Badges and default sort

- Card: a loud strip at the top of the body ("SALE IN 3 DAYS  Sep 24, 26 . 10:00 AM",
  "UPSET BID CLOSES TODAY", "REDEMPTION ENDS IN 101 DAYS") and state pills under the address
  (`clockStripHtml` 3908, `lifeFlagsHtml` 3898, `renderCards` 4390).
- Table: the Sale Date cell now shows the days pill in every view (it did so only in the Closing
  Soon stage), with the date and the state pills under it (`renderTable` 3942).
- Detail panel: a clock block under the badges (`clockPanelHtml` 3919, `#d-clock` in
  `index.html`), with one line per state.
- Presumed withdrawn is read from `raw.pulled_sale.presumed_withdrawn`,
  `auction_status === "presumed_withdrawn"` and `raw.stale_case` (`presumedWithdrawn` 1524). A
  withdrawn lead has no live deadline, so its stale sale date is not shown as a clock and it is
  not in Closing Soon. The "Hide stale" filter uses the same predicate.
- Default sort is now `_deadline` ("Deadline first", `getSortValue` 1351, `let sortKey` 9):
  live deadline inside 45 days soonest first, then tier (HOT, WARM, other), then grade; demoted
  leads last (`deadlineSortValue` 1744). Grade sort is still in the Sort menu and the Grade
  column header. The Sort menu and direction button are now visible on desktop too (they were
  phone-only), scoped to 721px and up in the `index.html` head style.

### F3: bankruptcy stay

- `bankruptcyStay` (1626): on a foreclosure-type lead (the same five types as
  `enrichment_bankruptcy_stay._FORECLOSURE_TYPES`) with `raw.bankruptcy_stay.status === "stayed"`,
  or, on slim, with `raw.bankruptcy` (the Python marks every such lead stayed, so the predicate
  is the same and is labelled "derived"), the lead shows "SALE STAYED (bankruptcy chapter N)"
  beside the sale date on the card strip, in the table cell, and in the panel.
- The panel explains resume risk from the stored fields: chapter, filing date, months since
  filing and risk are recomputed from `date_filed` against today (chapter 13 turns elevated at
  9 months, chapter 7 is high, mirroring the enricher), and it states the basis is a name match
  and that nothing re-checks dismissal or discharge (`stayLines` 1664).
- The bankruptcy badge is no longer red for chapter 13 and no longer described as a
  "HIGH-PRIORITY signal" when it is a stay. It reads "Ch.13 BANKRUPTCY <date> . name match".

### F13 and F6: signal chip and name matches

- `signalStackChip` (2698) and `getSignalCount` (2688) count distinct categories from
  `raw.distress_stack` (`distressCategories` 1824: `categories`, else `stack`, else signal
  names folded onto categories). Below 2 categories the chip prints nothing. The visible text is
  "N distress categories"; the tooltip lists the categories and the signals under them. The "Min
  signals" filter uses the same count and is relabelled "Min distress categories".
- `stackSignals` (1867) normalises `distress_stack.signals` whether each is a string, a
  `[name, category, weight]` array or an object. It reads an evidence class from `evidence`,
  `evidence_class`, `evidence_type` or `evidence_kind` on a signal, or from a
  `distress_stack.evidence` map, and shows it in the tier badge tooltip and the table tier dot
  ("foreclosure sale (record), incarceration (name match)"). Nothing is invented: a class is
  shown only if carried. Incarceration and bankruptcy are always labelled name match, and court
  divorce when `raw.divorce` is present.
- `nameMatchList` (1959) puts a "name match" chip on cards for incarceration, bankruptcy, court
  divorce and a property found by owner name, and adds labelled rows in the detail panel
  (only incarceration was labelled, and only there). The Distress Stack panel now draws its
  signals (it drew none before: it only rendered array-shaped entries and the scorer writes
  strings), name matches in the caveat colour.

### F19: equity

- `equityView` (1996): equity is shown only when the block is not withheld and the ARV trust
  gate (`arvTrust`) does not say bad or withheld. It carries its basis: "from recorded debt"
  (a deed of trust or an `amount_owed:*` figure) versus "estimated" (assessed-value guess, last
  sale amortised, opening-bid proxy), plus the confidence. Card chip, calculator row and the
  Distress Stack "Equity band" row say which.
- The legacy `high_equity` chip (from `flags.py`, outside the trust gate) shows only when the
  vetted equity block is shown and its basis is recorded (5985). `low_equity` and
  `negative_equity` chips are unchanged.

### F8 (address labels)

- Detail header reads "PROPERTY ADDRESS <address>", or "no property address" plus county, state
  and parcel when the street is empty. The Owner & Contact block leads with two labelled rows,
  "Property address (where the house is)" and "Owner's mailing address (where the owner gets
  mail)". The county-records row is "Owner's mailing address (county record ...)".
- Table, card and map tooltip say "no property address" instead of a blank or "(address
  pending)". 34,010 slim leads have no street address.

### Data-freshness banner

- `#freshness-banner` (`index.html` 140), `paintFreshness` (1085), `dataFreshness` (2037). Reads
  `health_as_of`; else `health_age_hours` plus the time since `run_time` (that field is frozen
  when run_meta is written); else `health_carried_from`, which `run_meta.json` already has;
  else says the health age is not reported. Board age comes from `run_time`. Red "Data may be
  stale" past 48 hours on either clock. Ages recompute every 5 minutes. On today's real
  `run_meta.json` it reads "Board built Sep 21, 10:11 AM (3h ago), source health as of Sep 21,
  1:33 AM (12h ago, carried forward from an earlier run)", not stale.

### Phone table layout (extra, in `premium.css`)

The phone card layout addressed columns by position for the 17-column table, and Buy Box became
column 2 later, so every rule was one column short. A phone card titled itself with the county,
showed the address as a muted subtitle, put Type where the bid goes and Max Bid where ROI goes,
and hid Sale Date. The days pill could never have reached a phone table. Renumbered
(`premium.css` 690 to 712, only inside the max-width 720px block); Buy Box is hidden on phones.
Cache-bust for `style.css`, `premium.css` and `dashboard.js` moved to `?v=20260921a`.

## Private-host changes (lead's addendum)

1. `manifest.json`: `id`, `start_url`, `scope` are `"./"`. The manifest `<link>` has
   `crossorigin="use-credentials"` (`index.html` 18).
2. Login page instead of data: `installSessionGuard` (235) wraps `fetch` once, before `loadData()`,
   so all data files (board, shards, `run_meta`, multifamily, land_buyers, detail) are checked in
   one place. 401, 403, an opaque redirect, a redirect to another origin, or a 200 `text/html`
   response on a `.json` / `.json.gz` URL shows "Session expired, reload to sign in." with a
   Reload button and reloads once. A missing optional file (404) is not a login. If the first
   `run_meta.json` fetch throws (a cross-origin login redirect the browser will not follow), the
   banner says "Could not load the data. If your sign-in expired, reload to sign in." and reloads
   once. The `sessionStorage` key `fc_session_reload_v1` is written before the reload, held
   while the problem persists (no loop), cleared after a successful load (`sessionOk`), and if
   storage throws the page never reloads.
3. CRM: `Export CRM` and `Import CRM` buttons in the footer and in the CRM block (`crmDoExport`
   6228, `initCrmIo` 6409). Export downloads `foreclosure-crm-YYYY-MM-DD.json`
   (`{format:"fc-crm-export", version:1, exported_at, origin, count, records}` where `records`
   is exactly the `fc_crm_v1` object). Import accepts that wrapper or the bare object, caps the
   file at 5 MB, and merges with `crmMerge` (159): by lead key, newer `updated` wins (`updated_at`
   accepted as a synonym, a missing date is oldest, a tie keeps local), a newer record overlays
   field by field so an older note it does not mention survives, nothing is ever deleted,
   `__proto__` / `constructor` / `prototype` keys and non-object records are skipped, notes are
   capped at 20,000 characters. The message says how many were added, updated, kept and skipped.
   The real CRM field is `updated`, not `updated_at`.
4. Nothing in `dashboard.js` or `index.html` hard-codes `github.io` or `/foreclosure-scraper/` at
   runtime. The only occurrences were in `manifest.json` (fixed) and an `index.html` comment
   (rewritten). A test enforces it. Third parties (Google Fonts, unpkg, OpenStreetMap,
   truepeoplesearch) are unchanged, as the hosting doc says.

## Phone gate (lead's second addendum, from `docs/phone_gate_handoff_2026-09-21.md` section 2)

- `ownerPhoneBlock(op)` (1393) mirrors `enrichment_sc_phone.owner_phone_block_reason`: `no_phone`,
  the stamped `do_not_dial_reason` (or `do_not_dial`), `people_search_walled`, `agent_contact`
  (by `role`, source, `raw.` source prefix or `match`), and `sc_xref_identity_<check>` for a
  `sc_voter_xref` / `ncsbe_voter_xref` phone whose `identity_check` is not `corroborated`
  (`unchecked` when never stamped: fails closed). `liensnc_filing`, the owner's own number, is
  never demoted. One deliberate widening of the handoff snippet: the walled list also has
  `enrichment_free_phones`, which `enrichment_sc_phone.WALLED_SOURCES` has and the snippet lacked.
  `phoneBlockText` (1410) turns a reason into words; an agent phone reads "Listing agent / attorney
  line, not the owner".
- Filters (2578): "Has phone" and the phone half of "Contactable" now use `ownerPhoneBlock`, so a
  blocked number is neither.
- Detail card (6062): a blocked `owner_phone` renders struck through with a red "DO NOT DIAL:
  <reason>" badge, in the Owner & Contact block, never in the plain style. Its alternates come
  from the same block and are struck too. A separate skip-trace number still shows, labelled.
- CSV: `owner_phone` is blank when blocked, `phone_source` is kept, and a new last column
  `phone_block_reason` (6453) carries the reason (blank when usable or absent).
- `_LEAN_RAW.owner_phone` is `["phone", "source", "needs_dnc_scrub", "do_not_dial",
  "do_not_dial_reason", "identity_check", "role"]`, in the order the handoff gives for
  `_SLIM_RAW`. `match` and `county_published` are not in that tuple, so on slim an agent phone is
  recognised by `role` and source, not by `match`.
- `tests/js/phone_gate.test.mjs` (5 tests) has the same cases as
  `tests/test_sc_phone_gate.py::test_block_reason_covers_every_lane_and_fails_closed_on_an_unstamped_xref_phone`
  plus every walled spelling, every agent lane and match value, stamped reasons, junk shapes, and
  checks that the filter, card and CSV use the gate. Verified in the browser on the scratch site:
  an agent phone and an unverified voter-file phone rendered struck through with their badges, a
  `liensnc_filing` phone rendered plain, "Has phone" kept only the usable one, "Contactable" kept
  the usable phone and the mailable lead and dropped both blocked ones.

## Scorer handoff (lead's third addendum, `docs/handoff_scorer_to_others_2026-09-21.md` section 3)

Items 1 (`stageOf`), 6 (`sale_date_passed` badge) and 7 (`high_equity`) were already done or
needed nothing, and are not repeated here. Done in this round:

- **Tier badge tooltip** (item 2), `stackTooltip` (1923), used by `stackTipText` and
  `distressBadge(ds, l)`, the table tier dot, and repeated as a list under the Distress Stack
  panel (`.stack-notes`) for phones. One fact per line: each signal with its evidence (an absent
  `evidence` entry is "record"; `name_only` and `name_joined` read "(name match)"; `inferred`
  reads "(inferred)"), then `stale_reason` as "event ended: ...", `stay` as "foreclosure stayed by
  Chapter N bankruptcy, resume risk X", `lane` with `days_to_event` as "foreclosure lane: sale in
  N days", `title_status` on a bidder lead, `equity estimated` when `equity_evidenced === false`,
  and `uncounted_categories` as "... not counted toward the stack". A field the stack does not
  carry adds nothing. `days_to_event` is counted from the day the board was scored, so it is
  aged by the whole days since `run_meta.run_time` and dropped once it reaches the past
  (`scoredEvent`, 1689). `stackSignals` now defaults an absent evidence entry to "record", and
  `nameMatchList` lists any other signal the scorer marks name-based as "<signal> . name match".
- **Bankruptcy banner** (item 3), `bankruptcyStay` (1626). "SALE STAYED" plus the resume risk
  when the stay is in force: from `raw.bankruptcy_stay.status === "stayed"` where that block is
  loaded, else from `distress_stack.stay` (which slim does carry, so phones now get the scorer's
  own in-force stay rather than a guess), else derived from `raw.bankruptcy` on boards scored
  before the field existed. A **lapsed** stay shows no banner, no strip tag and no demotion: it
  ends 270 days after filing for chapter 7 and 1,095 days otherwise, mirroring
  `signal_freshness.bankruptcy_lapsed` (`bankruptcyLapsed`, 1606). The filing badge then reads
  "... name match . stay lapsed"; in force it reads "... name match . sale stayed, resume risk
  moderate". The card strip's stay tag carries the resume risk too.
- **Deadline-first sort** (item 4), `leadClock(l, now, scoredAtMs)` (1714). A lead whose
  `distress_stack.lane` (or `fullmer.lane`) is `foreclosure` gets its aged `days_to_event` as a
  candidate deadline (kind `event`, "SALE EVENT IN N DAYS"), so a lane lead whose dates slim does
  not carry still sorts by its deadline. The soonest candidate wins, so a sale in 10 days and an
  event in 4 read as 4. It is ignored for a lead not in the lane and for a presumed-withdrawn
  one. The table shows the event's own date rather than the row's `sale_date`.
- **Chip text** (item 5): "N distress categories" (`signalStackChip`, 2698); the filter is
  "Min distress categories".
- **Filing-date sources.** `FILING_DATE_SOURCES` (1535, the lead's edit to `saleClock`) is kept.
  `stageOf` did not know about it, so a liensnc or nc_sos_ucc filing in the last 14 days counted
  as a sale in the last 14 days and landed in the foreclosure stage. `stageOf` now skips them too.

Tests: `tests/js/lead_state.test.mjs` grew from 28 to 37 (tooltip with every field, empty
fields, aging, lane sort, lapse boundaries at day 270 and 1,095, the scorer stay on slim,
evidence-driven name chips, filing-date sources, wiring). Run
`node --test tests/js/*.test.mjs`: 57 tests, all pass in three timezones; the pytest wrapper and
`test_slim_allowlist_matches_client` pass (the ops agent has landed `_SLIM_RAW["owner_phone"]`, so
decision 8 above is resolved). Verified in the browser on the scratch site with five synthetic
leads carrying the new stack fields: the tooltip text, the lane lead with no sale date sorting
second with a "3d sale event" pill, the slim-only stay with resume risk, the lapsed chapter 7
with no banner, and a liensnc filing with no "sale date passed" badge. Not re-run against the
real 170K board: the scorer's new fields are not on the published board yet, so there was
nothing new to see there.

## How it was verified

- `node --test tests/js/lead_state.test.mjs tests/js/io_guard.test.mjs tests/js/phone_gate.test.mjs`:
  57 tests (after the scorer-handoff round), all pass, also
  under `TZ` = UTC, America/Los_Angeles, Pacific/Auckland (the clock code compares local
  calendar days). `tests/test_dashboard_lead_state_js.py` runs both under pytest and skips if
  node is missing. Note `node --test tests/js/` (a directory) does not work on node 22; pass the
  files, or use the pytest wrapper (it globs `tests/js/*.test.mjs`).
- `pytest tests/test_board_slim.py::test_slim_allowlist_matches_client tests/test_detail_shards.py
  tests/test_dashboard_lead_state_js.py`: 24 pass, parity included.
- Browser, real board: `python3 -m http.server 8765` from `docs/`, `index.html?lean=1` (forces
  the slim payload on a desktop viewport). 170,066 records rendered, 50 table rows, 40 cards,
  no console errors, screenshot taken, the top of the default sort was 2,167 live-deadline
  leads starting with upset windows closing today. Server killed afterwards, tab closed, memory
  back to 49% free.
- Browser, scratch site: 409 records (400 real slim records plus 9 synthetic edge cases with
  dates relative to today) on ports 8766 and 8767, checked in table, cards and detail panel at
  desktop and 375px. Confirmed: stale-flag window reads "window closed" and is not in the
  foreclosure stage; open window is green with days left; sale passed 40 days shows the badge
  and sorts last; presumed withdrawn with a future sale date has no clock and sorts last; the
  stayed sale shows SALE STAYED beside the date with the resume-risk text and is not first;
  `high_equity` hidden on estimated equity and on an ARV flagged bad, shown on recorded equity;
  one category prints no chip, two print "2 distress categories"; "no property address" and the two
  labelled address rows; stale banner in red, fallback wording on `health_carried_from`.
- Session guard, on a server that can switch modes: 200 HTML, 401 and a cross-origin 302 each
  gave the banner and exactly one reload (two page loads in the server log, flag held), and a
  return to normal cleared the flag. CRM export produced the expected file name and JSON, and
  import merged as described, in the browser.

## What could not be verified

- No screenshot of cards on the real 170K board: the Browser pane went hidden mid-session
  (another session was also driving that pane and navigated the first tab away, so I worked in
  my own tab), and screenshots of a hidden pane are blank. Cards on the real board were checked
  by reading the DOM (40 cards, strips present); cards were screenshotted on the scratch site.
- The real download and file picker were not exercised (I stubbed the anchor click and built a
  `File` in the page). A real Cloudflare Access session was not available; the three failure
  shapes were simulated.
- Stored `bankruptcy_stay`, `pulled_sale` and `divorce` blocks on the real slim board: they are
  not in it (see decision 2). On phones the stay now comes from `distress_stack.stay` once the
  board is rescored with the new scorer, and is derived from `raw.bankruptcy` until then.
- The tier itself (HOT / WARM / COLD) is still the Python scorer's value. This front end only
  stops presenting a closed window, a passed sale or a stay as live. The scorer fixes in the
  audit (date logic, stack rule) are not in this change.
- `tests/test_board_slim.py::test_gz_only_rewrite_does_not_wipe_the_sidecar` fails in the
  working tree at `web_artifact._check_not_changed_since_load` (board lock). It does not touch
  `dashboard.js` and I did not investigate it; other sessions have uncommitted edits to
  `scripts/board_lock.sh` and Python files.
