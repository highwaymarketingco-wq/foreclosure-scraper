# Additions ledger (audit 2026-10-09, area additions_verify)

The owner's question: everything added to the most recent run (new sources, new enrichers,
re-enabled approaches, run flags since 2026-10-01), did it work, is it kept from now on, are we
losing anything? This ledger answers it per addition. Public-safe: counts, slugs, county names
and commit ids only; the sampled rows with names are in the owner's private audit folder
(`~/Desktop/Audit_2026-10-09/additions/`).

## How it was measured (repeatable)

- **The run**: the gated full run `vm-run-20261008T014033` (pin d42058b3, 10/7 21:36), stopped
  before publish; its pre_publish checkpoint (383,378 rows, saved 2026-10-08 21:03 UTC). Code
  committed on 10/8 was NOT in this run.
- **Ran?**: the VM run log, grep only (`scraper.ok` / `scraper.timeout` / `scraper.conn_error` /
  `enrich.time_capped` and each enricher's `.done` event).
- **Rows**: `uv run python scripts/audit_checks/additions.py --checkpoint DIR --json OUT
  --samples ~/Desktop/.../samples.json` streams the RAW checkpoint once: rows carrying each
  addition's output before the publish trim ("raw") and after `web_artifact._to_dict` ("pub"),
  fresh rows (fetched within 3 days of the board's newest last_seen) where the block has a date,
  and a 30-row random sample (seed 20261009) per addition.
- **Published / profile**: `additions-publish-shape` (every output key in `RAW_KEEP`, private keys
  out of it) and `additions-profile-flags` (every flag an addition needs is declared in
  `deploy/oracle/run_profile.json` and exported by `deploy/oracle/vm_lib.sh`).
- **Accuracy**: 30 sampled rows (all rows when fewer) checked against the primary source with an
  independent fetch (plain HTTP, 2 s or more per host, no scraper code reused), or, where marked
  "own record", every row checked against the row's own record by `scripts/audit_checks/additions.py`.
  Accuracy = correct / (checked - unverifiable).

## Summary

61 additions. On the 10/8 checkpoint: 38 ran and reached the published board as built (6 of them
had accuracy defects, fixed here); 11 produced nothing or little, and all 11 are now fixed in code
(7 by commits made after the run's pin, 4 here); 7 are walls or have no data right now; 3 are off
on purpose (now declared in the run profile); 2 are hand-off lanes whose new output is in the 10/8
hand-off and reaches the next run. Every published output key is in RAW_KEEP (56 checked) and
every flag an addition needs is now in run_profile.json and vm_lib.sh (24 checked). Two defects
lost or mis-bound data and are fixed here: the register-of-deeds readers reached 5 of about 60
counties and the deed chain 6 (time caps), and the deed chain bound the owner's deed for ANOTHER
parcel or a stale deed on 16 of 30 checked rows. One loss is open for a decision: the 1,549
Charleston court rows age out under the new 60-day window search.

## The ledger

Ran: OK n = scraper.ok with n rows; ZERO = scraper.ok with 0; T/O = timed out; CAP = phase capped.
Rows = raw / published on the checkpoint (carried rows included). Profile: "registry" = always on
(a registered scraper, no flag), else the flag and value the run profile declares.

| Addition | What | Commit | Ran (10/8) | Rows | Published | In profile | Accuracy | Status |
|---|---|---|---|---|---|---|---|---|
| `src-bankruptcy-rss-relief` | bankruptcy RSS relief-from-stay motions | 49353e8d | OK 18 | 18 / 18 | yes | registry | SCP | working |
| `src-echovita-obituaries` | Echovita NC/SC obituaries | 3bc56410 | OK 576 | 452 / 452 | yes (survivors private) | registry | SCP | working |
| `src-obituary-feeds` | paper and funeral-home obituary feeds | 3bc56410 | OK 40 (2 hosts 429) | 40 / 40 | yes | registry | SCP | working |
| `src-publicnoticesc-estates` | SC estate notices | ff795773 | ZERO | 0 | n/a | registry | n/a | fixed after pin (cf044d6f: the run's code hid a failed preset); Mac reads 50 rows a page, no wall |
| `src-charleston-energov-history` | Charleston code cases, demolition permits | ba366cc5 | conn_error | 0 | yes (key) | registry | n/a | wall for the VM (server drops the cloud address; the Mac reads 124 cases + 929 permits in 1 s); person lane |
| `src-horry-probate` | Horry probate estates | 8e156c5d | OK 3,997 | 3,997 / 3,997 | yes | registry | SCP | working |
| `src-york-tax-sale-parcels` | York SC tax-sale layer | f73b2bf9 | OK 853 | 853 / 853 | yes | registry | SCP | working |
| `src-cumberland-delinquent-tax` | Cumberland tax ad | ba366cc5 | OK 3,755 | 3,741 / 3,741 | yes | registry | 25/30 = 83% (ad PDF) | fixed here 0459c422 (placeholder situs left in owner_name) |
| `src-guilford-tax-foreclosures` | Guilford tax-foreclosure layer | f8ad91f8 | OK 930 | 897 / 897 | yes | registry | 30/30 = 100% (layer) | working |
| `src-iredell-delinquent-tax` | Iredell delinquent layer | ba366cc5 | OK 2,366 | 2,366 / 2,366 | yes | registry | 30/30 = 100% (layer; tax year assumed, flagged) | working |
| `src-kinston-proposed-demolition` | Kinston proposed demolitions | f73b2bf9 | OK 45 | 45 / 45 | yes | registry | 28/30 = 93% (layer; 2 owner names cut at a line break) | working |
| `src-mecklenburg-delinquent-tax` | Mecklenburg delinquent XLSX | f8ad91f8 | ZERO (flag off) | 0 | yes (key) | FORECLOSURE_MECKLENBURG_DELINQUENT=0 | n/a | off by the 10/7 decision (+29k one-year rows); declared now |
| `src-mecklenburg-tax-foreclosures` | Mecklenburg tax-foreclosure layer | f8ad91f8 | OK 618 | 618 / 618 | yes | registry | 30/30 = 100% (layer) | working |
| `src-nc-metro-demolition-permits` | Charlotte, Durham, Greensboro, Cary demolitions | ba366cc5 | OK 1,865 | 1,859 / 1,859 | yes | registry | 27/30 = 90% (permit feeds) | Durham PIN fixed after pin (83a2bb95) |
| `src-nc-tax-lien-ads` | Hoke, Lee, Davidson, Randolph tax-lien ads | ba366cc5 | OK 10,171 | 10,153 / 10,153 | yes | registry | 29/30 = 97% (ad PDFs) | working (1 acreage text in an owner) |
| `src-rocky-mount-blight-survey` | Rocky Mount condition survey | f73b2bf9 | OK 618 | 618 / 618 | yes | registry | 30/30 = 100% (6 layers) | working (Nash ids kept after pin, 668ed7ad) |
| `src-rowan-delinquent-tax` | Rowan delinquent spreadsheet | ba366cc5 | OK 2,699 | 2,698 / 2,698 | yes | registry | 30/30 = 100% (XLSX; amount includes interest) | working |
| `src-wake-code-cases` | Wake 90-day code cases | ba366cc5 | OK 74 | 74 / 74 | yes | registry | 26/30 = 87% (layer; facts 30/30) | fixed here 0459c422 (boilerplate tagged unsafe / fire) |
| `src-columbia-star` | Columbia Star MIE notices | 5042a060 | OK 13 | 12 / 12 | yes | registry | SCP | working |
| `src-mecklenburg-times` | Mecklenburg Times notices RSS | d75db9f5 | BLOCKED | 0 | n/a | registry | n/a | wall: plain 403 on the first request, Mac and VM; person lane |
| `src-raleigh-structure-fires` | Raleigh structure fires | f73b2bf9 | OK 396 | 395 / 395 | yes | registry | 28/30 = 93% (layer) | fixed here 0459c422 (UTC date one day late) |
| `src-asheville-code-enforcement` | Asheville code cases | 066605da | ZERO | 0 | n/a | registry | n/a | no data: newest case on the feed is 2018-12-14 |
| `src-anderson-acpass-deeds` | Anderson ACPASS court orders + POA | 80f20417 | T/O | 0 | yes (key) | registry | n/a | fixed here 6a4b3bd3 (2-year POA sweep could not finish; rows now kept as built) |
| `src-calhoun-overage-claims` | Calhoun overage claims | 1449d702 | OK 74 | 74 / 74 | yes | registry | SCP | working |
| `src-fairfield-overage-claims` | Fairfield overage claims | 1449d702 | OK 60 | 60 / 60 | yes | registry | SCP | working |
| `src-laurens-overage-claims` | Laurens overage claims | d0923313 | ZERO | 0 | n/a | registry | n/a | fixed after pin (ad240e9f: a Gemini 503 read as an empty list) |
| `src-orangeburg-overage-claims` | Orangeburg overage claims | d0923313 | ZERO | 0 | n/a | registry | n/a | fixed after pin (7b5369ac: Cloudflare refuses a bare UA; 129 records parse with a full UA) |
| `src-greenwood-cama-condemned` | Greenwood condemned parcels | 2e32a73d | OK (in 14,538 layers) | 719 / 719 | yes | registry | SCP | working |
| `src-funeral-home-rss` | funeral-home feeds (hosts recovered) | 5b7e3ae8 | T/O (8 homes read) | 171 / 171 | yes | registry | SCP | fixed after pin (a896a642: hosts read concurrently, finished hosts ship) |
| `src-liensnc-incremental` | LiensNC: Mac incremental + never age out | 23e05763, 7a15c683 | hand-off (not in the 10/7 file) | 46,730 / 46,730 | yes | Mac job | n/a (login lane, owner-run) | age exemption worked: 44,811 carried rows kept; the 10/8 hand-off brings the incremental rows |
| `src-judgment-lien-lane` | eCourts / Public Index judgments as judgment_lien | 375b4b72, 5cb93b78 | hand-off (not in the 10/7 file) | 2,242 / 2,242 (older manual rows) | yes | Mac job | covered by area E | next run: 13,952 judgment_lien rows in the 10/8 hand-off; growth_factor in run_profile should account for it |
| `src-charleston-public-index-lanes` | Charleston lanes, judgment-entered flag | bb935e1f, 7b104baa, 0d07cf96, ab44ec1e | hand-off (10/7 file used the old code) | 0 flagged; 1,549 old-code Charleston rows | yes | Mac job (as the owner left it) | covered by area E | OPEN: the new 60-day window re-reads 52 cases; the 1,549 carried rows age out (see open items) |
| `src-sc-divorce-46-counties` | SC Family Court, 46 county codes | 11a20a99 | hand-off | 26,449 SC rows with a divorce block, 15 counties | yes | Mac job (as the owner left it) | covered by area E | working, counties rotate per run |
| `src-nc-ecourts-estates` | NC eCourts estates (WAF path) | 3827b032 | not in either hand-off | 0 | yes (key) | Mac job (as the owner left it) | n/a | zero; stealth path not touched; owner's lane |
| `src-sos-dissolution` | NC SoS dissolution (WAF path) | 3827b032 | ran: 28 checked, 28 unknown | 0 | yes (key) | registry | n/a | zero useful output; stealth path not touched |
| `src-loopnet-render` | LoopNet render rewrite | 44a61fe6 | not in either hand-off | 0 | yes (key) | Mac job | n/a | zero; WAF re-verified 10/4 (f68206a5) |
| `enr-generic-rod-platforms` | register readers by owner name (raw.rod) | a237f78b, 8611d9f3, 9edff1f3 | CAP 900 s: 5 of ~60 counties started | 114 fresh / 114 | yes | 13 platform flags + FORECLOSURE_GENERIC_ROD_BUDGET_S=2400, GENERIC_ROD_COUNTY_CONCURRENCY=8 | own record: 150/152 blocks name the row owner (98.7%); SCP for live | fixed here 3fce1eac (+ main.py wiring W-A1) |
| `enr-rod-chain` | deed chain per lead (raw.rod_chain) | a237f78b, 853ceb5c | budget 1,800 s used in 6 alphabetical counties | 88 stamped, 46 status ok | yes | FORECLOSURE_ROD_CHAIN=1, _BUDGET_S=1800, ROD_CHAIN_COUNTY_CONCURRENCY=8 | 14/30 = 47% (county + NC OneMap parcel records) | fixed here 3fce1eac (run shape) + a2c7f3ad (binding: contradicted chains become 'unbound') |
| `enr-nc-rod-render` | browser-rendered registers | 50d059c4 | off (20 counties disabled) | 0 | n/a | HARRIS / LOGAN_BLAZOR / LOGAN_REMOTE = 0 | n/a | off on purpose until a run measures memory and time |
| `enr-heir-candidates` | heir candidates (filtered names published) | bb9355a2, 0126b88f | done: 25,085 dead-owner leads, 3,755 with candidates | 3,755 / 3,755 | yes | registry (HEIR_CANDIDATES default on) | own record: 4,390/4,390 relations publishable, no age/phone/e-mail; SCP for live | working |
| `enr-obituary-match` | obituary to owner match | bb9355a2 | done: 829 indexed, 14 attached, 12 ambiguous | 26 / 0 (private by design) | private (not in RAW_KEEP, checked) | registry | SCP via heir candidates | working |
| `enr-obituary-lookup` | obituary lookups by name | 2f0d038b | off (no event) | 0 | n/a | OBITUARY_LOOKUPS=0 | n/a | off by default; declared; owner decision |
| `enr-nc-heir-estate-cap` | heir/estate parcels, cap 80 to 400 | b287eb79 | OK 3,369 (6 counties at the cap) | 6,915 / 6,915 | yes | registry | covered by source_completeness (cap invariant) | working |
| `enr-richland-parcel` | Richland map-viewer facts and mailing | b1a82194, 8592d84b | done, capped at 300 | 221 matched / 221 | yes | RICHLAND_PARCEL_MAX=500 | own record: 221/221 in Richland; SCP for live | fixed here 2e3fde0c (HOT/WARM first) + 500 a run (1,775 rows were waiting) |
| `enr-parcel-cache-join` | parcel-cache join on every row | 0adf8bba | done: 193,994 hits, 63,339 mailings filled | 37,820 / 37,820 | yes | registry (FORECLOSURE_CACHE_JOIN default on) | n/a | working |
| `enr-sos-agent-handoff` | NC SoS registered-agent contacts | ee44ec25, ed456b3b | applied: 216 attached | 809 / 809 | yes | Mac job | own record: hand-off attachments 388/389 bound; 111 government-owned rows carried another LLC's profile | fixed here 6e4b66c1 (government rows); 63 other unbound legacy profiles left (HANDOFF item 57 policy) |
| `enr-entity-type` | owner entity type | 18dcf810 | done | 383,373 / 383,373 | yes | registry | n/a | working |
| `enr-tax-age` | late years only, big old tax, not yet late | c80963f0, ae28568e | done: tier floor 304 rows | 1,458 / 1,458 | yes | registry | own record: 1,425/1,425 big-old and 33/33 not-yet-late consistent; county site: 10/11 tax_lien confirmed | working |
| `enr-tax-aging-surfaced` | tax aging surfaced to scoring | f514bd45 | done | 133,387 / 133,387 | yes | registry | n/a | working |
| `enr-co-defendant-signal` | co-defendant lienholders | 52e64f80 | done: 134 tagged | 135 / 135 | yes | registry | own record: 133/135 | fixed here cb7fce15 (plaintiff listed as its own junior lienholder) |
| `enr-hoa-plaintiff-signal` | HOA plaintiff flag | a900271b | done: 59 tagged | 60 / 60 | yes | registry | own record: 60/60 plaintiff is an association | working |
| `enr-liensnc-posthumous` | LiensNC filing after the owner's death | 23e05763 | done: 102 tagged | 113 / 113 | yes | registry | not verified: all 113 are the low-confidence name-token mechanism | working, low confidence by its own label |
| `apr-prior-correction` | correction of carried rows | ea6a4e0a, f7acaeb1, 4170cbbc | done | 3,908 / 3,908 | yes | FULLRUN_PRIOR_CORRECTION must not be 0 (gate) | own record: 408/411 withdrawn claims clean (3 re-acquired an elderly tag) | working |
| `apr-parcel-alias` | Lincoln/Rutherford 10-digit PIN alias | 38748f73 | done: 15,923 alias matches in the merge | 680 / 680 | yes | registry | 30/30 = 100% Lincoln (county layer); own record: 53 Rutherford rows mapped to another 7-digit id | fixed here 58f46fd3 (only a 10-digit PIN enters the table) |
| `apr-coastal-flip-5min` | coastal flips within a 5 minute drive | 67375356 | done | 58 / 58 | yes | registry | own record: 58/58 inside the bar | working; 45 of the 58 are HomePath retail listings that leave with the HomePath fix |
| `apr-homepath-reo-only` | HomePath: Fannie Mae REO only | c33369b5, aef7c291, 1ec2638b | ran | 589 (580 homepath_json) | yes | registry | n/a | fixed after pin (aef7c291 asks REO only; 1ec2638b prunes the retail rows); ceiling 300 invariant |
| `apr-verification-apply` | county-site verdicts applied | 465e6c1e | done | 3,185 / 3,185 | yes | VERIFICATION_APPLY must not be 0 (gate) | covered by areas E and verification | working |
| `apr-pickens-2026-cycle` | Pickens 2026 delinquent cycle | 03f6428a, ad56ce7e | OK 2,560 | 255 prior-cycle-only | yes | registry | n/a | working |
| `apr-qpaybill-staged-detail` | qPayBill roll with staged detail pages | e95dd10e, 708630b7 | T/O partial, 7,028 salvaged | 35,245 / 35,245 | yes | registry | covered by source_completeness | fixed after pin (708630b7: every county, stalest first) |
| `doc-ocr-notices` | notice PDF OCR (RECAP, county PDFs) | 236179bc, ea498cd0, 048b69b5 | CAP 900 s, Gemini 503 overloads | 76 / 76 | yes | registry | covered by documents_images | fixed after pin (7c68431c own budget; ab8de34e ledger) |
| `doc-dot-ocr` | deed-of-trust image OCR | ab8de34e | budget used: 389 searched, 0 images | 22 / 22 | yes | registry | n/a | wall: the CCHS us4/us5 tenants (Lincoln, Burke, Cleveland, Henderson) answer the VM with 403 |

SCP = South Carolina / people sources: the live check of those sampled rows is in the section
below.

## Fixes made in this audit (commits, tests, invariants)

| Defect | Scale | Fix | Test | Invariant |
|---|---|---|---|---|
| Register readers ran one county after another inside the ROD group's 900 s cap; counts lost on the cap | 5 of ~60 counties, 114 leads | 3fce1eac: counties side by side (8), imminent counties first, own budget with counts returned, counts logged on cancel | tests/test_rod_run_shape.py | `addition-enr-generic-rod-platforms` (fresh floor 200) |
| Deed chain read counties alphabetically inside 1,800 s | 6 counties, the same every run | 3fce1eac: side by side, imminent first | tests/test_rod_run_shape.py | `addition-enr-rod-chain` (fresh floor 60) |
| Generic pass would starve the deed chain of the shared 30-lookup county cap once it reaches every county | every chain county | 3fce1eac: at most 10 leads a chain county | tests/test_rod_run_shape.py | same |
| Deed chain bound by NAME: another parcel's deed or a chain that missed the owner's sale | 16 of 30 checked | a2c7f3ad: binding from the row's own parcel sale; contradicted = 'unbound'; outgoing deeds reported | tests/test_rod_run_shape.py, tests/test_nc_rod_chain.py | `additions-rod-chain-binding` |
| Government-owned rows published another LLC's SoS contact | 111 rows (120 Lincoln county parcels among them) | 6e4b66c1 | tests/test_sos_agent_handoff.py | `additions-sos-agent-bound` |
| Alias table took a 7-digit id as a PIN | 53 Rutherford rows given another property's id | 58f46fd3 | tests/test_parcel_alias_migration.py | `additions-alias-is-pin` |
| Anderson ACPASS deeds timed out with 0 rows | every run since 10/1 | 6a4b3bd3 (+ made-up fixtures replacing names copied from the live index) | tests/test_anderson_acpass_deeds.py | `addition-src-anderson-acpass-deeds` (counts) |
| Richland reader took the first 300 rows in board order | 1,775 rows waiting | 2e3fde0c + RICHLAND_PARCEL_MAX=500 | tests/test_enrichment_richland_parcel.py | `addition-enr-richland-parcel` (fresh floor 100) |
| Co-defendant scan scored the plaintiff as its own junior lienholder | 2 of 135 | cb7fce15 | tests/test_co_defendant_signal.py | (counts in the ledger) |
| Cumberland placeholder situs in owner_name; Raleigh UTC dates; Wake boilerplate tags | 5, 2, 4 of 30 | 0459c422 | tests/test_new_sources_2026_10_07*.py | per-source floors |
| Flags on by code default and new budgets not in the run profile | 11 flags | 6eef52de | tests/test_prerun_gate.py (flags check) | `additions-profile-flags` |

## main.py wiring the lead must apply (W-A1)

`src/foreclosure_scraper/main.py`, the ROD group (anchor: `# 2026-10-07: the platform adapters for
the other NC/SC counties`). Replace

```python
    try:
        from .enrichment_generic_rod import enrich_generic_rod
        _rod_phases["generic_rod"] = enrich_generic_rod(enriched)
    except Exception:
        log.error("generic_rod.failed", traceback=traceback.format_exc())
    _rod_results = await _gather_phases(_rod_phases)
```

with

```python
    _generic_rod_coro = None
    try:
        from .enrichment_generic_rod import enrich_generic_rod
        # its own budget (audit 2026-10-09 additions_verify): the 900 s group cap reached 5 of ~60 counties
        _generic_rod_budget_s = float(os.environ.get("FORECLOSURE_GENERIC_ROD_BUDGET_S", "840")) + 120
        _generic_rod_coro = _await_capped(enrich_generic_rod(enriched), "generic_rod",
                                          default_s=_generic_rod_budget_s)
    except Exception:
        log.error("generic_rod.failed", traceback=traceback.format_exc())
    _rod_results, _generic_rod_stats = await asyncio.gather(
        _gather_phases(_rod_phases),
        _generic_rod_coro if _generic_rod_coro is not None else asyncio.sleep(0))
    _rod_results["generic_rod"] = _generic_rod_stats
```

(the `for _rod_name in (...)` loop that follows already records `generic_rod`). Cost: the generic
pass runs up to 2,400 s beside the other ROD readers (they stay at 900 s), about 25 minutes more
run time; no memory change measured (it holds no rows of its own). Without this wiring the pass
still runs counties side by side and logs `generic_rod.cancelled` with its counts at 900 s.

## Open items (wall / no source / owner decision / not enough time)

1. **Charleston court rows will age out (owner decision).** The 10/7 Charleston pass change reads
   cases filed in the last 60 days (`CHARLESTON_PI_LOOKBACK_DAYS`, the Mac's stealth lane, not
   touched). The 1,549 Charleston rows the 10/7 hand-off delivered (all unlabelled old-code rows)
   are not re-read: on the next run they are marked presumed withdrawn, and dropped after 4 more
   misses. Correction 6 assumed "relabelled ones come back on the next run"; with the window they
   do not. Choices: run the Charleston pass once with a long look-back on the Mac (a parameter of
   the existing pass) so open cases are relabelled, and keep a look-back of about a year; or accept
   the loss. Invariant `additions-window-lanes-not-aging` fails when more than 10% of these rows
   are aging.
2. **Walls recorded, left to a person:** Mecklenburg Times (403), Charleston EnerGov from the VM
   (the Mac reads it), CCHS us4/us5 deed images for dot OCR (403), NC eCourts estates, SoS
   dissolution and LoopNet (stealth paths, untouched).
3. **No data:** Asheville code cases (feed ends 2018-12-14).
4. **Owner decisions declared, not changed:** obituary lookups (OBITUARY_LOOKUPS=0), Mecklenburg
   delinquent list (=0), browser register platforms (=0), the 63 unbound legacy SoS profiles on
   person-owned rows (HANDOFF item 57).
5. **Next-run growth:** the 10/8 hand-off carries 13,952 judgment_lien rows and about 60,000
   LiensNC rows the 10/8 run never saw; `memory.growth_factor` 1.15 in the run profile may be low.
6. **Not verified:** the deed chain binding was replayed on the 46 checkpoint chains (3 of 3
   contradicted ones were wrong live, 3 of 5 sale-date ones right) but not run live; the 2
   sale-date misses sold in August 2026 and should now read name_only through their outgoing deed,
   which assumes the register index returns that deed. Whether advertised taxes were since paid.
   The LiensNC posthumous tag (113 rows, all low confidence by its own label).

## Outside this area (one line each)

- The four older ROD readers (gaston, cchs, aumentum, spartanburg) were also cut at the 900 s
  group cap on 10/8, with no counts kept.
- `tests/test_prerun_gate.py` fails on the current working tree from uncommitted work of other
  areas (enrichment_comps.py whole-file load; call_ready.py unwired).
- 2,000+ `counties_sc.sc_public_index` rows sit at 2 to 3 consecutive misses (presumed withdrawn)
  and leave within two runs unless the Mac sweep reaches their counties.
- `_clean_entity` does not read "L.L.C." as a business designator.
- `exempt_claim_withdrawn`: 3 of 411 rows re-acquired an elderly life-event tag after the
  withdrawal.
