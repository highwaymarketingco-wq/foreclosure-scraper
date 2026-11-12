# Audit 2026-10-09, area top80_fill: county parcel-record fill (deed book/page, legal, value, acreage, parcel id)

Owner chose to build the top 80 of the ranked build list. This group: the eight items of rank <= 80 with layer
`fill` whose source is not a register-platform adapter: ranks 1, 5, 8, 9, 21, 22, 27, 59 (the other `fill` items,
`atty_rod_lien_checked`, are register items and belong to the register groups).

| rank | column | source | cells | rows (build list) | outcome |
|---|---|---|---|---|---|
| 1 | atty_deed_ref | NC OneMap statewide parcels | 77 | 113,898 | BUILT (`gis_fill.py`), live on 1,941 NC board parcels |
| 5 | atty_deed_ref | county GIS deed book/page (SC) | 13 | 32,711 | BUILT, 13 county layers registered |
| 8 | atty_deed_ref | register index (Abbeville, Colleton, Florence, Marlboro) | 4 | 6,782 | adapters already built and ON; measured; cube now reads the bound register deed; cap-limited |
| 9 | atty_legal_description | county GIS legal field | 48 | 58,206 | BUILT (NC OneMap short legal for 43 NC counties; Aiken, Greenville, Greenwood, York layers; Beaufort registered) |
| 21 | atty_legal_description | register index (6 NC, Lancaster SC) | 7 | 4,701 | adapters exist; measured; Franklin walled, Sampson browser-only OFF |
| 22 | assessed_value | county GIS (SC, 14) | 14 | 15,386 | 2 filled (Aiken, Hampton: need parcel ids), Jasper partial, 11 end as verdicts |
| 27 | lot_size | county GIS (SC, 10) | 10 | 9,223 | 4 filled (Dorchester, Hampton, Orangeburg, Jasper partial), 6 verdicts |
| 59 | parcel_id | county GIS (SC, 4) | 4 | 1,767 | Orangeburg: 78 of 93 qPayBill roll rows joined by account; Aiken, Hampton, Marion: no free route (verdict) |

## 1. What was measured and how

Everything below is counts and county names; no parcel id, owner, legal text or value is in this repo.

- **Board** (streamed, never loaded whole, peak RSS 70 MB): the local checkpoint `data/checkpoint` (197,890 rows; the
  cube's 383,378-row checkpoint lives on the VM, so row counts here are about half the cube's). NC 110,509 rows, 74,423
  with a parcel id; SC (15 registered counties) 25,464 rows, 22,333 with one. Deed reference present before: NC 13,016
  (11.8%), SC registered counties 61.
- **Live proof** (`scripts/top80_fill_proof.py`, repeatable): up to 20 NC / 25 SC real board rows per county that
  `gis_fill.needs()`, the real enricher run on those Listings, per-county counts printed (table in
  `top80_fill_counties.csv`). Requests 2 s apart per host, one at a time, ordinary browser User-Agent, no
  CAPTCHA/login/token touched. NC: 100 counties, 1,941 rows. SC: 11 counties, 275 rows.
- **Layer fields**: each SC layer's own `?f=json` field list plus a live sample 2026-10-09; recorded in `SC_FILL`.
- **Register index**: the existing platform adapters' `chain()` on 5 real owners per county, depth 0 (last deed only).

### NC OneMap (items 1 and 9, NC part)

Sample: 20 real board rows per county (the county's own rows that still lacked a field), 100 NC counties, 1,941 rows:

| result | rows | share of sampled |
|---|---|---|
| parcel found in the layer | 1,760 | 90.7% |
| deed book/page read | 1,440 | 74.2% |
| deed `none` (parcel in layer, assessor's record blank: a per-row verdict) | 320 | 16.5% |
| short legal read | 1,135 | 58.5% |
| legal `none` (record blank) | 625 | 32.2% |

Projected on the local checkpoint (74,383 NC rows with a parcel id; 13,016 already had a deed reference and 19,546 a
legal): NC deed reference **11.8% -> about 53% of rows**, plus about 9% more carrying a `none` verdict; legal
**17.7% -> about 47%**, plus about 16% verdicts. The rest are rows with no parcel id (33% of NC rows) or whose id is not
the layer's id; `gis_fill` cannot reach them (`top80-fill-unscreened` counts them).

Join (board id to the layer's `parno`/`altparno`): exact id forms first (40 pins a request), then a LIKE pass for the
pins the exact forms missed, accepted only when the layer's id equals the board's letter for letter. Two alias rules
were found live: a separated `-00` sub-parcel suffix (Edgecombe 0 of 8 became 8 of 8) and the Buncombe 10-digit index
PIN that is the head of the layer's 15-digit parno (Buncombe, the biggest county, 8,649 rows with a parcel id: 45% to
100% in layer, 40 of 40 with a deed reference).

NC counties whose assessor layer carries no usable deed reference (a per-row `none` verdict, the county record is
blank): Anson, Avery, Brunswick, Cleveland, Gates, Guilford (book only), Hoke, Lee, Macon, Martin, Swain, Union, Washington. Counties whose layer has no short legal: Alleghany, Anson, Buncombe, Burke, Caldwell, Camden, Caswell, Cleveland, Columbus, Dare, Duplin, Durham, Forsyth, Franklin, Greene, Hoke, Hyde, Johnston, Jones, Madison, Martin, Mitchell, Pasquotank, Perquimans, Polk, Richmond, Rutherford, Sampson, Stanly, Surry, Wilkes, Yadkin, Yancey. Counties where the board's parcel id and the
layer's differ so the join still misses most rows: Vance, Rowan, Iredell, Currituck, Tyrrell, Madison, Onslow.

### SC county layers (items 5, 9, 22, 27)

Sample: 25 board rows per county (Barnwell, Berkeley, Darlington, Greenville, Horry, Jasper, Lancaster, Lexington,
Saluda, Sumter, York; 275 rows): in layer 218 (79%), deed read 206, deed `none` 12, legal read 104, legal `none` 66,
value filled 109, acreage filled 34. Aiken, Dorchester, Greenwood, Hampton, Orangeburg have no board row with a parcel
id (their rows are names only, see item 59), so they were proven on 10 parcels each taken from the layer itself, not from
the board: Aiken 9 deed / 9 legal / 9 value / 10 acres, Dorchester 10 deed / 10 acres, Greenwood 10 deed / 10 legal /
9 value, Hampton 9 deed / 10 value / 9 acres, Orangeburg 10 acres. Beaufort is registered (its EnerGov layer has deed,
legal, value, acres) but none of its 918 board rows carries a parcel id (a street only: the situs-address resolver
`scripts/resolve_parcel_from_address.py` is the lever, outside the run).

Projected on the 22,333 SC rows with a parcel id in the 15 registered counties (61 had a deed reference): deed
reference **0.2% -> about 66%** of the registered counties' rows, plus about 5% `none` verdicts.

## 2. Defects found and fixed

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| deed book/page and short legal sat in the county parcel layer, unread | NC 74,383 rows with a parcel id, SC 22,333 | the board kept only the owner, value and acreage off those layers | `gis_fill.py` (`raw['county_deed_ref']`, `raw['county_legal']`, dated `raw['gis_fill']`) | tests/test_top80_fill.py | `top80-fill-deed-ref-shape`, `-bound`, `-legal-shape`, `-screen-honest`, `-values-sane`, `-unscreened` |
| a blank record read as an unchecked cell | every county whose assessor leaves the field empty (13 NC counties for the deed, 32 for the legal) | the cube counted only hits for field columns | per-row `none` verdict only when the parcel IS in the layer; `gap_matrix` counts it as checked (`GIS_FILL_VERDICT_COLS`); a parcel the layer does not hold is no verdict | same | `top80-fill-screen-honest` (verdict without parcel, found without block) |
| Jasper's parcel layer answers `Token Required` | 817 Jasper rows with a parcel id | the county put its service behind a token (2026-10-09) | the public June-17 copy of the same county service is read (`SC_FILL_EXTRA`); 11 of 25 sampled parcels are in it | same | same |
| Orangeburg qPayBill roll rows had no parcel id | 93 rows | the roll names an account number; the county layer carries it as `parcel_id` | `enrich_account_parcels`: exact key join, unique account only; Orangeburg added to `parcel_cache.PARCEL_LAYERS` (62,555 parcels, cache built, count-verified) | same | `top80-fill-account-join` |
| a loose id match could bind a neighbour | design | LIKE patterns match more than one id | a record is accepted only when its id equals the board's letter for letter after separators; a cut (`exceededTransferLimit`) answer leaves unmatched pins unscreened | same | `top80-fill-deed-ref-bound` |
| the LIKE pass could close the whole NC OneMap lane on two slow answers | design | one error counter per url | LIKE errors close only the LIKE pass | same | n/a |

## 3. Item by item

**Item 1, atty_deed_ref, NC OneMap, 77 cells: BUILT.** `gis_fill.fetch_nc`. In the item's 77 counties 1,065 of 1,474 sampled rows (72%) got a deed reference; in 45 of the 77 every sampled row ended as a hit or a verdict. 13
counties' assessor layers carry no usable deed reference (Anson, Avery, Brunswick, Cleveland, Gates, Guilford (book
only), Hoke, Lee, Macon, Martin, Swain, Union, Washington): those rows get the per-row verdict and the register route
(`deed_latest`) is their only fill. Join misses (id schemes differ from the layer's): Vance 0 of 20, Rowan 5, Iredell 5,
Currituck 7, Tyrrell 8, Madison and Onslow 11 of 20.

**Item 5, atty_deed_ref, county GIS (SC, 13 cells): BUILT.** All 13 counties registered in `SC_FILL` with the deed
fields read off each layer (Aiken `SaleBookPage`, Barnwell/Hampton/Saluda/Sumter book+page, Berkeley, Darlington,
Dorchester `DEED` ('007687-289'), Greenwood `Deed` ('695-194'), Horry, Lancaster (books like 'D006'), Lexington (CAMA
pair, else the map pair), York `TransferBook/Page`). Placeholders ('NA', '0000', zero padding) are not deed references.

**Item 8, atty_deed_ref, register index (Abbeville, Colleton, Florence, Marlboro): measured, adapters already ON.**
`rod/sc_online_record_system.chain` and `rod/sc_cott_esearch.chain`, 5 real owners each, depth 0: Abbeville 0 of 5 (the
name index names none of them), Colleton 2 of 5, Florence 1 of 5, Marlboro 4 of 5 (+1 partial); every `ok` result
carried a book/page and the index's description. Lancaster (item 21) 5 of 5. Flags `FORECLOSURE_SC_ORS_ROD` and
`FORECLOSURE_SC_COTT_ESEARCH_ROD` are already 1. The limit is the name-search budget (30 lookups a county a run against
6,782 rows), not missing code; there is no deed field on the Colleton or Florence layer (`LAYER_LACKS`). What I added: the
cube now counts a register deed BOUND to the parcel (`raw['deed_latest']`, lawyer_lane) for both attorney columns.

**Item 9, atty_legal_description, county GIS (48 cells): BUILT.** NC: the assessor's short legal (`legdecfull`) for the 43
NC counties of the item, from the same request as item 1 (none of the 43 is in the blank-legal list of section 1). In the item's 45 counties with a sample, 766 of 883 sampled rows (87%) got a short legal and 29 counties ended every sampled row as hit or verdict (Aiken, Beaufort, Greenwood have no board row with a parcel id). SC: Aiken, Greenville, Greenwood, York, Horry, Lexington, Sumter, Barnwell, Darlington, Saluda
layers; Beaufort registered, no parcel ids on its rows. A deed reference that a county writes into the legal field
(Caldwell) is read as a deed reference, never shown as a legal. It is the assessor's SHORT legal, labelled
`assessor_short_legal`; the deed image has the full text.

**Item 21, atty_legal_description, register index (Columbus, Franklin, Jones, Sampson, Stanly, Yancey, Lancaster):
measured.** 5 owners each: Columbus 1 of 5 (The Lookup), Jones 1 of 5 (Cott v4), Stanly 3 of 5 (CCHS classic), Lancaster
5 of 5; all `ok` results carried the index description. Yancey: 2 not found and 3 `error` (an adapter fault, see
section 5). Franklin: walled (CCHS hosted tenant, `nc_cchs_classic.HOSTED_WALLED`; walls_register card nc_cchs_cf).
Sampson: Logan Blazor, browser-only, stays OFF (the Logan/Harris group measured it at 20 s a lookup and about 26 lookups
in 900 s against 10,292 rows; my one attempt timed out clicking, 60 s). The bound register description reaches the
cube through `deed_latest.legal_description`.

**Item 22, assessed_value, county GIS (SC, 14 cells).** Filled once a row has a parcel id: Aiken (AssessedValue,
TotalMarketValue), Hampton (Tot_Assesd_Value, Tot_Market_Appr), Jasper (public June-17 copy, market value, 11 of 25
parcels held). Ends as a verdict (11 cells): walled by qPublic/Beacon's Cloudflare check (card sc_qpublic): Clarendon,
Edgefield, Fairfield, Lee, Lancaster, Florence (the open layer holds the BUILDING value only, no land value), Orangeburg;
no source: Chesterfield, Marion, Williamsburg (WTH map shell, no REST layer), Dorchester (open layer, no value field).

**Item 27, lot_size, county GIS (SC, 10 cells).** Filled: Dorchester (TAXED_ACRES, GIS_ACREAGE), Hampton, Orangeburg
(CalculatedAcres; the layer is in `parcel_cache.PARCEL_LAYERS` and `SC_FILL`), Jasper (partial). Verdicts (6): Edgefield,
Fairfield, Lee (qPublic wall), Newberry (the county's service answers 'Service not started', property card on qPublic),
Marion, Williamsburg (no layer).

**Item 59, parcel_id, county GIS (SC, 4 cells).** Orangeburg: the 93 qPayBill roll rows carry an account number that
equals the county layer's `parcel_id`; `enrich_account_parcels` resolved 78 of 93 (84%) to the layer's TMS, with the
acreage, by exact key join (an account on two parcels is not resolved). The other 15 accounts are not in the layer.
Aiken, Hampton, Marion: no free route. Their parcel-less rows are names only (Aiken: HUD REAC property names, newspaper
lis pendens; Marion: 32 probate notices; Hampton: 3 state tax-lien and bankruptcy rows): no street address and no
point, and an owner-name match to the county layer found no unique parcel (Aiken 0 of 31 matchable names, Orangeburg 0
of 31, 74 of 93 qPayBill names ambiguous). Point-in-polygon from a geocode was NOT adopted: on 10 precise points
each, Beaufort's returned parcel agreed with the row's street number on 2 of 8 comparable rows, Orangeburg's with the
owner on 2 of 6, so writing those parcel ids would bind another property's facts to the row.

**Cells.** None of the 77 + 13 + 48 + 14 + 10 + 4 fill cells reaches 100% by fill alone: every county still has rows with
no parcel id or whose id the layer does not hold. 20 cells end as verdicts the cube now reads (11 + 6 + 3 above; two
more beyond the item lists: Colleton and Newberry assessed value). The per-row `none` verdicts (deed 16.5% of NC rows
sampled, legal 32.2%) count as checked in `gap_matrix` for atty_deed_ref, atty_legal_description, assessed_value and
lot_size; a parcel the layer does not hold is no verdict. Nothing was dropped as not worth building.

## 4. Wiring (the lead applies; main.py and HANDOFF.md untouched)

`deploy/oracle/run_profile.json` `unwired_wire_pending` carries it; the line is:

```python
    # main.py, right after the enrich_gis_attrs try/except (the "GIS attribute backfill" block)
    try:
        from .gis_fill import enrich_gis_fill
        s = await _await_capped(enrich_gis_fill(enriched), "gis_fill",
                                default_s=float(os.environ.get("FORECLOSURE_GIS_FILL_BUDGET_S", "2400")) + 180)
        if s and "skipped" not in s: enrichment_stats["gis_fill"] = s
    except Exception:
        log.error("gis_fill.failed", traceback=traceback.format_exc())
```

Flags (already in `deploy/oracle/vm_lib.sh` and `run_profile.json`): `FORECLOSURE_GIS_FILL=1`,
`FORECLOSURE_GIS_FILL_BUDGET_S=2400`. The pass keeps its screen on every row between runs (`RECHECK_DAYS` 45), so a
budget that ends early finishes on the next run. At about 2.5 s a request (40 parcels) the NC exact pass for
74,383 parcels is about 1,900 requests; the LIKE pass follows with what is left. Run order matters:
after parcel resolution and `enrich_gis_attrs`, before `enrich_rod_chain` (which then skips its own live
`county_deed_ref` read for every row this pass screened).

## 5. Not verified, and outside my area

- Not verified: that a deed reference the assessor writes is the parcel's LATEST deed (the layer says "last
  conveyed by"; Union writes none, Guilford a book only); the full legal description (the deed image has it; the
  short legal is the assessor's, labelled as such); the account join for the 15 of 93 Orangeburg roll accounts
  the county layer does not hold.
- Not run: the VM, a full board pass, any publish. `gap_matrix` not re-run on the 383,378-row cube checkpoint (it is
  on the VM); the projection above is from the local 197,890-row checkpoint and a 20-row-per-county sample.
- Outside my area: `rod/nc_lookup.chain('Yancey', ...)` answered `error: the session holds '' names, not the 1 ticked`
  for 3 of 5 owners (2026-10-09); Franklin NC (CCHS hosted tenant) has no chain adapter in the registry because
  `nc_cchs_classic.HOSTED_WALLED` lists it; `tests/test_prerun_gate.py::test_the_real_profile_has_nothing_pending`
  and `::test_frozen_keys_known_in_the_real_profile` fail on other groups' pending wiring.
