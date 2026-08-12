# ROAD TO 100% — MASTER COVERAGE MATRIX

One authoritative table for the 30 footprint counties x 12 distress signals. Synthesis of `completeness_matrix.md`, `completeness/cm_matrix.md`, `coverage_gap_analysis.md`, `SOURCE_REGISTER.md`, `COUNTY_SYSTEMS_REGISTRY.md`, `gap_ledger.md`, `case_type_code_map.md`, plus a live check of `src/foreclosure_scraper/scrapers/` and `src/foreclosure_scraper/config.py`. Read-only. No engine runs, no board writes.

Compliance frame: everything below stays inside FREE + PUBLIC. No CAPTCHA solving, no people-search PII, no riding a robots Disallow. Where the only path is walled, the cell is marked so and an alternate free channel is named, never a rule break.

---

## LEGEND

### Status (does the board carry the signal for that county today)
- `●` HAVE — a working scraper feeds this cell. Named in the notes.
- `◐` PARTIAL — a scraper exists but is filter-broken, pending first landing, volume-capped, or policy-gated (coastal near-beach lane).
- `○` GAP — nothing feeds this cell today.

### Lane to 100% (the compliant path that closes the cell)
- `fb` FREE-BUILT — working code exists; close the cell by un-gating, un-denying, or landing a fix already written. Lowest cost.
- `fx` FREE-BUILDABLE — an open, no-auth endpoint exists; needs a new parser.
- `ms` MANUAL-SAVE — ToS/disclaimer/WAF-walled to a bot, but an operator can save the page and an offline parser ingests it (the existing SC PublicIndex / NC eCourts lane).
- `fa` FREE-ALTERNATE-NEEDED — the obvious source is walled, but the same data is likely reachable through a free side channel. Flag for the alternate hunt.
- `hw` HARD-WALL — no compliant free path found yet.

HAVE cells are FREE-BUILT by definition and carry no lane suffix.

### Signal columns
- **S1 FCL** Foreclosure — NC power-of-sale SP cases / SC judicial CP-420 (Master-in-Equity)
- **S2 PRE** Pre-foreclosure — lis pendens / NOD / notice of hearing
- **S3 ROST** Sale rosters (MIE / sheriff / trustee) + NC upset bids
- **S4 TAXD** Tax delinquency — county unpaid rolls, tax-sale + FLC lists
- **S5 TAXL** Tax liens — state / federal
- **S6 PROB** Probate / estates
- **S7 DIV** Divorce / equitable distribution
- **S8 BKR** Bankruptcy
- **S9 LIEN** Liens — HOA / mechanic / judgment
- **S10 CODE** Code enforcement / condemnation / vacant
- **S11 EXEM** Senior / disabled / veteran exemption
- **S12 DISP** Absentee / cash-buyer (dispo)

### Scope reality (read before the grid)
The engine tracks **18 counties** (`config.ALL_COUNTIES`): 11 NC + 7 SC. Of the task's 30-county footprint:
- **12 are outside the tracked set.** Coastal SC (Charleston, Georgetown, Horry, Colleton) and coastal NC (Brunswick, Pender, Onslow, Carteret, Dare) re-enter only through the **oceanfront near-beach gate** in `main._in_scope`, so any scraper that feeds them lands only the near-beach fraction. That is why their best cells are `◐`, not `●`, even where a dedicated scraper exists.
- **Clay, Haywood, Yancey (NC) are in `SCOPE_DENY_COUNTIES`.** They are actively dropped, including via the statewide bypass sources. Their zero is a **one-line policy toggle**, not a data wall: the statewide NC lanes (nc_ecourts, courtlistener, cash_buyer_deeds, ROD) would reach them the moment the deny entry is removed. Hence their gaps are lane `fb`.

---

## THE MASTER GRID

Cells: status glyph + lane suffix. `%grn` = (HAVE + 0.5·PARTIAL) / 12.

| County | S1 FCL | S2 PRE | S3 ROST | S4 TAXD | S5 TAXL | S6 PROB | S7 DIV | S8 BKR | S9 LIEN | S10 CODE | S11 EXEM | S12 DISP | %grn |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|--:|
| **NC CORE (tracked)** |||||||||||||
| Buncombe | ● | ● | ● | ● | ○fa | ● | ● | ● | ○fx | ◐fx | ● | ● | 79 |
| Henderson | ● | ● | ● | ● | ○fa | ● | ● | ● | ○fx | ● | ○fx | ● | 75 |
| McDowell | ● | ● | ● | ● | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 67 |
| Cleveland | ● | ● | ● | ◐fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 63 |
| Rutherford | ● | ● | ● | ◐fb | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 63 |
| Burke | ● | ● | ● | ◐fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 63 |
| Lincoln | ● | ● | ● | ◐fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 63 |
| Polk | ● | ● | ● | ◐fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 63 |
| Transylvania | ● | ● | ● | ◐fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 63 |
| Gaston | ● | ● | ● | ○fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 58 |
| Mitchell | ● | ● | ● | ○fx | ○fa | ● | ● | ● | ○fx | ○fx | ○fx | ● | 58 |
| **NC CORE (task footprint, DENY-listed)** |||||||||||||
| Clay | ○fb | ○fb | ○fb | ○fx | ○fa | ○fb | ○fb | ○fb | ○fx | ○fx | ○fx | ○fb | 0 |
| Haywood | ○fb | ○fb | ○fb | ○fx | ○fa | ○fb | ○fb | ○fb | ○fx | ○fx | ○fx | ○fb | 0 |
| Yancey | ○fb | ○fb | ○fb | ○fx | ○fa | ○fb | ○fb | ○fb | ○fx | ○fx | ○fx | ○fb | 0 |
| **NC COASTAL (near-beach gate only)** |||||||||||||
| Brunswick | ◐fb | ◐fb | ◐fb | ◐fx | ○fa | ◐fb | ○fb | ○fb | ○fx | ○fx | ○fx | ◐fb | 25 |
| Onslow | ◐fb | ◐fb | ◐fb | ◐fx | ○fa | ◐fb | ○fb | ○fb | ○fx | ○fx | ○fx | ◐fb | 25 |
| Carteret | ◐fb | ◐fb | ◐fb | ◐fx | ○fa | ◐fb | ○fb | ○fb | ○fx | ○fx | ○fx | ◐fb | 25 |
| Pender | ◐fb | ◐fb | ◐fb | ○fx | ○fa | ◐fb | ○fb | ○fb | ○fx | ○fx | ○fx | ◐fb | 21 |
| Dare | ◐fb | ◐fb | ◐fb | ○fx | ○fa | ◐fb | ○fb | ○fb | ○fx | ○fx | ○fx | ◐fb | 21 |
| **SC CORE (tracked)** |||||||||||||
| Spartanburg | ● | ● | ● | ● | ● | ● | ● | ● | ◐fx | ● | ○fx | ● | 88 |
| Pickens | ● | ● | ● | ● | ● | ● | ● | ● | ◐fx | ○fx | ○fx | ● | 79 |
| Laurens | ● | ● | ● | ● | ● | ● | ● | ● | ◐fx | ○fx | ○fx | ● | 79 |
| Oconee | ● | ● | ● | ● | ● | ● | ● | ● | ○fx | ○fx | ○fx | ● | 75 |
| Anderson | ● | ● | ● | ○fx | ● | ● | ● | ● | ○fx | ○fx | ○fx | ● | 67 |
| Union | ● | ● | ● | ○fa | ● | ○fb | ○ms | ● | ○fx | ○fx | ○fx | ◐fb | 46 |
| Cherokee | ● | ● | ● | ○fa | ● | ○fb | ○ms | ● | ○fx | ○fx | ○fx | ○fb | 42 |
| **SC COASTAL (near-beach gate only)** |||||||||||||
| Charleston | ◐fb | ◐fb | ◐fb | ◐fx | ● | ◐fb | ○ms | ● | ◐fx | ○fx | ○fx | ◐fb | 46 |
| Georgetown | ◐fb | ◐fb | ◐fb | ◐fx | ● | ◐fb | ○ms | ● | ○fx | ○fx | ○fx | ◐fb | 42 |
| Horry | ◐fb | ◐fb | ◐fb | ◐fx | ● | ◐fb | ○ms | ● | ○fx | ○fx | ○fx | ◐fb | 42 |
| Colleton | ◐fb | ◐fb | ◐fb | ◐fx | ● | ◐fb | ○ms | ● | ○fx | ○fx | ○fx | ◐fb | 42 |

---

## PER-COUNTY NOTES (only where the grid needs explaining)

**NC core, tracked.** S1/S2/S3 are solid everywhere: nc_ecourts_lis_pendens (statewide SP + lis pendens), the substitute-trustee firms (Hutchens/Foundation, Brock & Scott, Aldridge Pite, Bell Carrington, ALAW, McMichael Taylor Gray), wnc_rod_foreclosure_starts, nc_rod_substitute_trustee, and national.nc_upset_bids (fixed 08-02) cover the foreclosure spine. Probate (S6), divorce (S7 via nc_ecourts_divorce Judgment JSON), and bankruptcy (S8 via courtlistener) ride statewide lanes, so they read HAVE for all 11.

- **Buncombe** — the volume anchor (5,902 leads). S11 EXEM is HAVE only because buncombe_elderly exists; that single roster is 3,680 of the footprint's 3,682 exemption leads. S10 CODE is PARTIAL: asheville_helene storm + STR permits land, but code_violation and vacant read 0.
- **Henderson** — S10 CODE now HAVE (henderson_code_violations + hendersonville_vacant_structures, built 08-03). S4 TAXD strong (1,087). S11 EXEM has 1 lead.
- **McDowell** — best NC contactability (6.2% unreachable). S12 DISP is the only county carrying cash-buyer deeds (national.cash_buyer_deeds), though that source is board-broken elsewhere.
- **Cleveland/Rutherford/Burke/Lincoln/Polk/Transylvania** — S4 TAXD is PARTIAL: a tax scraper exists but underperforms. Lincoln loses ~1,205 rows to a PDF ID-column drift; Rutherford has a 9,328-bill rewrite committed 08-03 awaiting first board write (lane `fb`); Burke/others sit on nc_ptscloud tenants that return empty. cleveland_tax and polk_tax land only a handful.
- **Gaston / Mitchell** — S4 TAXD is a true GAP: **Gaston sits in no property-tax-arrears module at all** (not a PTS Cloud tenant, not in the PDF set), Mitchell's roll is unwired. Both are `fx` (buildable county endpoints exist).

**NC core, DENY-listed (Clay, Haywood, Yancey).** Zero coverage on every signal because `config.SCOPE_DENY_COUNTIES` drops them even from the statewide bypass sources. The lane is `fb` for the court/firm/deed signals (they ride the exact statewide scrapers the other NC counties already use once un-denied) and `fx` for tax/lien/code/exemption (per-county endpoints to build). These three are the cheapest large coverage win in the whole footprint if the operator wants them in scope.

**NC coastal (Brunswick, Onslow, Carteret, Pender, Dare).** Scrapers exist: nc_coastal_tax_foreclosure (Brunswick/Onslow/Carteret), sheriff_sales (Brunswick), brunswick_legal_notices, coastland_times/carolina_coast newspapers (Dare), and the statewide firms carry all five. Every cell is capped by the near-beach oceanfront gate, so status is `◐` at best. Pender and Dare are thinnest (firms + court only, no dedicated tax-foreclosure feed). S8 BKR reads GAP because courtlistener rows without a near-beach address are dropped by the deny+oceanfront interaction; lane `fb` (widen the gate).

**SC core, tracked.** S1 MIE via anderson/pickens/spartanburg_master_in_equity + sc_county_rosters; S2/S1 also via sc_public_index + sc_public_index_lis_pendens. S5 TAXL is HAVE for all SC (sc_state_tax_lien, statewide SC DOR registry). S8 BKR statewide. 
- **Spartanburg** — the strongest county (88%). Only real gaps: S9 LIEN thin, S11 EXEM absent (0 despite 8,919 leads). Its S10 CODE/CND/VAC block is the footprint's richest.
- **Pickens** — S4 HAVE on the strength of pickens_delinquent_parcels (2,161, added 08-03).
- **Anderson** — S4 TAXD GAP: **no source of any kind wired to Anderson's delinquent-tax roll** (1 lead). `fx`.
- **Cherokee / Union** — the two worst SC counties. Cherokee is 100% unreachable, zero heirs, zero absentee. S4 TAXD is `fa`: the qPayBill/parcel-mismatch wall blocks the roll, and Cherokee's delinquent-tax PDFs sit in `wp-json/wp/v2/media` unanchored (a media-index reader would be `fx`, but the county roll itself is the alternate hunt). sc_rod_cott collapses Union's 39 rows to 1. S7 DIV is `ms` (SC divorce detail is behind the PublicIndex disclaimer-accept, the operator-save lane).

**SC coastal (Charleston, Georgetown, Horry, Colleton).** Dedicated scrapers exist and are good: charleston_mie + charleston_delinquent_tax (RP+MH+FLC) + sheriff_sales, sc_coastal_rosters (MIE for Georgetown/Horry/Colleton), georgetown_civicengage, horry_flc, colleton_tax_sale. All near-beach-gated, so `◐`. S5 TAXL and S8 BKR are HAVE (statewide, not gated). S7 DIV is `ms` (PublicIndex disclaimer lane).

---

## LANE-TO-100 BY SIGNAL (the pattern behind the columns)

| Signal | Where it is solid | Where it breaks | Dominant lane to close |
|---|---|---|---|
| S1 FCL | All 18 tracked | Coastal (gate), deny trio | `fb` — un-gate / un-deny; scrapers already emit these rows |
| S2 PRE | All 18 tracked | Coastal, deny trio | `fb` |
| S3 ROST | All 18 tracked; NC upset fixed | Coastal, deny trio | `fb` |
| S4 TAXD | Buncombe, Henderson, McDowell, Spartanburg, Pickens, Oconee, Laurens | Gaston, Mitchell, Anderson (unwired); Cherokee, Union SC (qPayBill wall) | `fx` mostly; `fa` for Cherokee/Union SC roll |
| S5 TAXL | Every SC county (sc_state_tax_lien) | Every NC county | `fa` — NC has no free state tax-lien registry; federal IRS liens are recorded at county ROD, reachable via the ROD document lane |
| S6 PROB | 11 NC + 5 SC | Cherokee/Union SC, coastal | `fb` — heir parcels + column + sc_probate_net exist; NC eCourts estates is CAPTCHA-walled but covered via Column |
| S7 DIV | 11 NC + 5 SC | Cherokee/Union/coastal SC | `fb` in NC (ecourts); `ms` in SC (PublicIndex disclaimer save) |
| S8 BKR | 18 tracked + coastal SC | Coastal NC, deny trio | `fb` — courtlistener already statewide; un-deny/un-gate |
| S9 LIEN | Nowhere at scale (10 leads footprint-wide) | Everywhere | `fx` — HOA via charleston_mie pattern; mechanic/judgment liens wait on the ROD rebuild |
| S10 CODE | Spartanburg (rich), Henderson | Everywhere else; Buncombe partial | `fx` — county code/vacant portals; a few need FOIA |
| S11 EXEM | Buncombe only | Everywhere else | `fx` — per-county GIS exempt-code layers (the diversification build) |
| S12 DISP | 17 tracked (absentee via mailing-vs-situs) | Union SC, coastal, deny trio | `fb` — absentee derive + un-gate; cash-buyer deed mining is `fx` |

**No cell is a true hard-wall.** Every signal has at least one compliant path. The walls that exist (rutherford_wildfire robots Disallow, SC PublicIndex disclaimer, mewborn_deselms Cloudflare, NC eCourts estates CAPTCHA, landsofamerica Akamai) all sit at the *source* level, and each is bypassed by a free alternate already named in the register (a different portal, the operator-save lane, or a statewide feed). That is why the `hw` count is 0.

---

## STRUCTURAL FACTS THAT OUTWEIGH ANY SINGLE CELL

1. **Roughly a third of the road to 100% is a policy toggle, not a build.** The deny trio (36 cells) and the coastal near-beach gate (108 coastal cells, most `◐`) are gated by config, not by data availability. Widening the oceanfront gate and removing three deny entries lifts a large block of `◐`/`○fb` cells toward `●` with no new scraper.
2. **S5 TAXL splits cleanly by state.** SC has a free statewide tax-lien registry; NC does not. Every NC tax-lien cell is `fa` and points at the same alternate: federal liens recorded at county ROD.
3. **Three signals are effectively single-county.** S11 EXEM is Buncombe-only, S10 CODE/VAC is Spartanburg-dominant, S9 LIEN is ~unbuilt. These are the widest true build gaps and are `fx` (open endpoints exist).
4. **S4 TAXD is the highest-value fragile column.** Biggest recoverable wins: Gaston + Anderson (no lane at all), Lincoln (ID drift, ~1,205 rows), Rutherford (9,328-bill rewrite pending first write), Cherokee/Union SC (qPayBill wall, needs the `fa` alternate).
5. **Contactability is a parallel gap the signal grid does not show.** Phone is 0.0% across all 7 SC counties (no free SC voter-phone file), and 35.3% of the tracked footprint has neither mailing nor phone. Closing signal cells does not close the reach gap.

---

## SUMMARY COUNTS

30 counties x 12 signals = **360 cells.**

| Status | Count | Share |
|---|--:|--:|
| ● HAVE | 145 | 40% |
| ◐ PARTIAL | 64 | 18% |
| ○ GAP | 151 | 42% |

| Lane to 100% | Count |
|---|--:|
| FREE-BUILT (fb, incl. 145 HAVE) | 225 |
| FREE-BUILDABLE (fx) | 108 |
| FREE-ALTERNATE-NEEDED (fa) | 21 |
| MANUAL-SAVE (ms) | 6 |
| HARD-WALL (hw) | 0 |

**Five counties furthest from 100%:** Clay (0%), Haywood (0%), Yancey (0%) — all three DENY-listed, closeable by un-denying and riding existing statewide NC lanes — then Pender (21%) and Dare (21%), the thinnest coastal NC counties (firms + court only, near-beach-gated). The next tier is Brunswick/Onslow/Carteret at 25%.

_Generated 2026-08-12. Read-only synthesis; cell verdicts inherit the caveats of the 2026-08-04 completeness audit (board = the 07-31 full run; pending-fix cells marked `fb` are unproven until the next board write)._
