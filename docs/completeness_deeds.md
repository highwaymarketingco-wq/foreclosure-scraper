## Straight answer to the operator's question

Yes. A deed search tells you **who owns it, how they got it, and what secured debt was recorded against it.** It tells you essentially nothing about **how much is owed today, whether the borrower is behind, who is living in it, what condition it is in, or what non-recorded claims are attached.** In North Carolina specifically, several of the liens investors care most about (judgments, mechanics liens, HOA liens, federal tax liens, lis pendens) are **not at the Register of Deeds at all**; they are docketed with the Clerk of Superior Court. Searching only the ROD in NC will miss them entirely.

---

## 1. What IS in a NC/SC Register of Deeds index

| Instrument | What it proves | Investor-useful fact it reveals |
|---|---|---|
| **Deed** (warranty, special warranty, quitclaim) | Chain of title | Current record owner, acquisition date, grantor/grantee names, and (NC) sale price via excise stamp. Long tenure + old low basis = equity. Quitclaim between relatives = possible probate/divorce event. |
| **Deed of trust (NC) / Mortgage (SC)** | A secured loan existed | **Original principal**, origination date, lender, trustee. Base for an amortization estimate. Multiple open DOTs = stacked liens. Private/hard-money lender named = distress signal. |
| **Assignment of deed of trust/mortgage** | Loan sold | Who to actually call. Transfer to a special servicer or debt fund is a strong pre-default signal. |
| **Satisfaction / cancellation of DOT** | Loan paid off | The single most valuable field: a DOT with no satisfaction is presumptively still open. **Free-and-clear detection is done by absence of a satisfaction, not by presence of anything.** |
| **Substitution of trustee** (NC, G.S. 45-10) | Lender swapped in a foreclosure trustee | Classic 30-to-90-day pre-foreclosure tripwire. Often the earliest recorded distress artifact in NC. |
| **Notice of hearing / notice of sale** (NC power-of-sale) | Foreclosure is running | Sale date, trustee, file number. See caveat in section 2: the statutory home is the Clerk, ROD recording is county practice. |
| **Trustee's deed / commissioner's deed / foreclosure deed** | Sale completed | Hammer price (via NC excise stamp), new owner, whether the lender credit-bid it back (REO). |
| **Tax deed** | Tax sale completed | Post-sale ownership; tax-sale investor identification. |
| **Lis pendens** | Litigation affecting title | SC: this is your judicial-foreclosure starting gun, but it lives at the **Clerk of Court**, not the ROD. |
| **Claim of lien / mechanics lien** | Unpaid contractor | **SC only** at the ROD (§29-5-90 permits ROD or Clerk of Court). **NC files these with the Clerk of Superior Court** (G.S. 44A-12). |
| **HOA/COA assessment lien** | Delinquent dues | **SC only** at the ROD. **NC files with the Clerk of Superior Court** (G.S. 47F-3-116). Amount stated is as-of-filing, not current. |
| **UCC fixture filing** | Financed fixtures (solar, HVAC, manufactured home) | NC G.S. 25-9-501: fixture filings go to the ROD. A solar UCC can blow up a deal at closing. |
| **Plat / subdivision map** | Legal boundaries | Lot dimensions, easements, setbacks, whether a parcel is legally subdividable. |
| **Easement** | Third-party rights | Access, utility, right-of-way. Landlocked-parcel detection. |
| **Restrictive covenants / declaration** | Use limits | Whether an HOA exists at all, rental restrictions, minimum square footage, mobile-home bans. |
| **Power of attorney** | Someone signs for the owner | Strong proxy for incapacity, elderly owner, or an out-of-state owner delegating. High-motivation signal. |
| **Death certificate** (recorded in some NC counties) | Owner died | Inherited-property lead. |
| **Deed of distribution (SC) / estate documents** | Estate transferred realty | SC probate transfers surface here. Heirs' names and addresses. |
| **Affidavit of heirship / affidavit of survivorship** | Who inherited | Occasionally recorded; when present it names the heirs. Frequently absent (see section 2). |
| **Separation agreement** (commonly recorded in NC) | Marriage dissolving | Pre-divorce distress before any court decree exists. |
| **Federal tax lien** | IRS claim | **SC: ROD** (SC Uniform Federal Tax Lien Registration Act, §12-57-30). **NC: Clerk of Superior Court** for real property (G.S. 44-68.12). |

---

## 2. What is NOT in the deed record, and where it actually lives

| Invisible in the deed record | Why | Where it actually lives | Obtainable free? |
|---|---|---|---|
| **Current loan balance** | Only the original principal is recorded. Nothing updates it. | Servicer/borrower only. No public record anywhere. | **No. Cannot be obtained by anyone at any price** without the borrower's authorization. Estimate only: amortize original principal from origination date at an assumed rate. |
| **Delinquency, forbearance, loss-mit, modification status** | Nothing requires recording. Modifications are sometimes recorded, usually not. | Servicer. Credit bureaus (FCRA-restricted). | **No.** Proxy only: substitution of trustee, notice of hearing, or SC lis pendens. That is the earliest you can see it, and by then it is already late. |
| **Escrow advances, default interest, attorney fees, forced-place insurance** | Accrues off-record | Servicer payoff statement | **No.** Systematically causes payoff to exceed any amortization estimate. Budget a cushion. |
| **Property tax delinquency and amount owed** | NC tax lien attaches automatically Jan 1 (G.S. 105-355) with **no recording requirement**. SC operates on the same first-lien-by-operation-of-law structure. | County Tax Collector / delinquent tax office | **Yes, separately.** This is why the repo has qPayBill and the NC delinquent-tax scrapers. It will never come out of a ROD sweep. |
| **NC judgment liens** | Docketed, not recorded | **Clerk of Superior Court judgment docket** (G.S. 1-234); 10-year lien from date of entry | **Yes**, via NC eCourts Judgment Search JSON (already wired in the repo). Not in the ROD. |
| **NC mechanics liens** | G.S. 44A-12: filed in the office of the **clerk of superior court**, noted on the judgment docket | Clerk of Superior Court | Yes, same court lane. **Never** in the NC ROD. |
| **NC HOA/COA liens** | G.S. 47F-3-116: claim of lien filed of record in the office of the **clerk of superior court** | Clerk of Superior Court | Yes, same court lane. **Never** in the NC ROD. This is a real gap if you were relying on ROD sweeps for HOA distress in NC. |
| **NC federal tax liens on real property** | G.S. 44-68.12 | Clerk of Superior Court | Yes, court lane. (SC is the opposite: ROD.) |
| **NC lis pendens** | G.S. 1-116/1-117: cross-indexed by the clerk in a "Record of Lis Pendens" | Clerk of Superior Court | Yes. Note: some NC ROD vendors still carry a `LIS/P` instrument code, so you may see both. Do not assume ROD coverage is complete. |
| **NC notice of foreclosure sale** | G.S. 45-21.17 requires **posting** in the area designated by the clerk plus newspaper publication. The statute does not require ROD recording. | Clerk of Superior Court special proceeding file; legal notices in the newspaper | Yes. Many NC counties do also record a Notice of Sale at the ROD (which is why the CCHS/Logan adapters find `FCL` / `NOTICE OF SALE` codes), but coverage is county practice, not statute. **Newspaper legals remain the more reliable NC pre-sale feed.** |
| **Unrecorded utility, water/sewer, demolition, nuisance-abatement, and code-enforcement charges** | Municipal, often no recorded instrument until very late | City/town utility billing and code enforcement | Partially. The repo's Asheville code-enforcement source is the model; most towns have no feed. |
| **Occupancy and tenancy** | Nothing to record | Nowhere public | **No.** Requires physical drive-by, USPS vacancy data (paid), or utility shutoff data (not public). |
| **Leases** | NC G.S. 47-18 only requires recording for leases **over three years**. Every ordinary 12-month residential lease is invisible. | Landlord/tenant only | **No.** A tenant in place is a post-close surprise. |
| **Condition, deferred maintenance, interior, roof, systems** | Not a recordable fact | Nowhere | **No.** Only Street View, listing photos, permits, and inspection. This is the repo's vision/photo stack, and it is a proxy for exterior only. |
| **Probate transfers with no recorded deed (heirs by intestacy)** | **NC G.S. 28A-15-2(b): title vests in heirs at the moment of death.** No deed is required, none is recorded. The ROD still shows the dead person as owner. | Clerk of Superior Court estates division (NC); Probate Court (SC) | Yes, via the estates/probate lane. **This is the single biggest blind spot of a pure deed search.** A ROD-only view of a heir-owned property looks like a normal owner who has not sold in 30 years. |
| **Divorce equitable-distribution interests before judgment** | An unadjudicated ED claim is not a recorded interest | District Court civil file (NC), Family Court (SC) | Partially. NC eCourts Judgment Search surfaces divorce; pre-judgment ED claims are effectively invisible. NC separation agreements are sometimes recorded and are the only ROD-visible artifact. |
| **Contracts for deed, land contracts, unrecorded options, rights of first refusal** | NC G.S. 47-18 covers them, so an unrecorded one does not bind a purchaser for value, but it very much binds the seller and complicates the deal | Parties only | **No.** Silver lining: under 47-18 an unrecorded option/contract generally cannot defeat a BFP, so the exposure is deal friction, not title loss. |
| **True sale price on most SC deeds** | See section 3 | Assessor CAMA card (Pickens, Oconee) | Partially. |
| **Beneficial ownership behind an LLC** | Deeds name the entity | NC SoS registered agent/officers (free, already built); SC SoS is captcha-walled | NC yes, SC no. |

---

## 3. Deed stamps: backing out sale price

### North Carolina (works, with caveats)

**G.S. 105-228.30:** excise tax of **$1.00 per $500 or fractional part thereof** of the consideration or value of the interest conveyed, paid to the ROD of the county where the land lies before recording.

```
sale_price ≈ excise_stamp × 500
true price lies in the interval:  ((stamp − 1) × 500,  stamp × 500]
```

The repo already implements this in `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/rod/deed_stamp.py` with a $100 to $10M plausibility band.

**Failure modes, in order of how often they bite:**

1. **It rounds up, always.** "Fractional part thereof" means `stamp × 500` is an **upper bound**, overstating by up to $499.99. Noise on a $400k sale, material on a $15k lot.
2. **Zero stamp on exempt transfers.** G.S. 105-228.29 exempts transfers: (1) by operation of law, (2) by lease for a term of years, (3) by will, (4) by intestacy, (5) by gift, (6) where no consideration is due or paid, (7) by merger/conversion/consolidation, (8) **by an instrument securing indebtedness**. So every deed of trust has no stamp, and every inherited/gifted/entity-roll-up deed reads as $0. **A $0 stamp does not mean a $0 sale, it usually means an exempt transfer.** Treat it as null, never as a comp.
3. **Governmental grantors are out of scope entirely** (G.S. 105-228.28), so tax-foreclosure and municipal deeds carry no stamp.
4. **Multi-parcel deeds.** One stamp covers every parcel in the instrument. Allocating the whole stamp to your subject parcel inflates its price, sometimes by 10x on a portfolio deed.
5. **Multi-county parcels.** 105-228.30 sends the entire tax to the county holding the greater value, so a stamp recorded in county A can cover land in county B. Cross-county comps are unreliable.
6. **Encumbrance treatment is ambiguous.** The statutory base is "the consideration or value of the interest conveyed." Whether existing debt taken subject-to is included varies by closing practice and county. This is a variance source, not a bug in your parser.
7. **Trustee's deeds on a lender credit bid.** The stamp may reflect the credit bid rather than market value, or be omitted. Credit-bid REO transfers are the noisiest single class.
8. **Index-level omission.** Many ROD grids do not expose the excise field at all. You have to open the detail page or the document image. Budget for that, it is the real throughput limiter.

### South Carolina (the operator's framing needs one correction)

SC **does** have a price-bearing fee: **§12-24-10**, a deed recording fee of **$1.85 per $500** of realty value ($1.30 state + $0.55 county). Mathematically `value = (fee / 1.85) × 500`. So the mechanism exists.

**The problem is not the absence of a rate, it is §12-24-70 plus §12-24-40:**

- **§12-24-70** requires an affidavit stating value, **but "for deeds exempt from the provisions of this chapter, the value is not required to be stated on the affidavit"**; the affidavit only has to state the **reason** for the exemption. The clerk or ROD may waive the affidavit entirely at their discretion. And no affidavit at all is required for a §62-3-907 deed of distribution.
- **§12-24-40** exempts 15 categories, and the ones that matter to a distressed-property operator are exactly the ones you want priced:
  - **(13) deeds in lieu of foreclosure and deeds executed pursuant to foreclosure proceedings.** Your entire SC foreclosure comp set is exempt and therefore states no value.
  - (12) corrective and quitclaim deeds confirming existing title
  - (8)/(9) transfers to and from corporations, partnerships, and family trusts
  - (5) partition deeds
  - (4) IRC §1041 transfers, which is the **divorce** transfer category
  - (2) transfers to government
  - (10)/(11) mergers and consolidations

Net: **in SC, the foreclosure deed, the divorce deed, the family-trust deed, and the partition deed all legally recite no value.** That is a statutory wall, not a scraping problem. Combined with the already-known finding that AcclaimWeb `GridResults` omits consideration from the index grid, SC recorded sale price is not recoverable at scale from the ROD.

**The free SC workaround remains the assessor, not the ROD:** the qPublic per-parcel property card for Pickens and Oconee carries sqft plus sales history. That is the SC price lane.

---

## 4. Per-county ROD search URLs and access status

All verified live on 2026-08-02 by direct HTTP request. No CAPTCHA was encountered on any of the 18. Nothing below requires defeating a bot wall.

### South Carolina (7)

| County | ROD search URL | Vendor | Status |
|---|---|---|---|
| **Spartanburg** | `https://search.spartanburgdeeds.com/index.php` | Logan "The Lookup" (newer, DataTables/AJAX) | **OPEN**, no login (HTTP 200). Caveat: as of the repo's 2026-06-22 verification the deployment returned **zero rows for every search type**, a county-side index/QC condition. Mechanics are reverse-engineered and ready; data is not flowing. |
| **Anderson** | `https://acpass.andersoncountysc.org/deed.cgi` (menu) then `deeda.cgi?SearchType=L` | ACPASS (county-built CGI) | **OPEN**, no login (HTTP 200, 18.9 KB / 39.7 KB). Note the ACPASS **root** presents a login form; the deed module itself is publicly reachable without auth. Do not classify Anderson as login-walled based on the homepage. |
| **Pickens** | `https://www.pickensscrod.us/AcclaimWeb` | Harris Acclaim Web | **OPEN**, no login. Already wired in `rod/acclaim.py`. |
| **Oconee** | `https://oconee.sc.publicsearch.us/` | Tyler PublicSearch | **LOGIN (free account required).** County states "users will need to sign up for a free account before accessing any records." Deed index from 1957, mortgage index from 1992, **images only from 1/1/2002**. Copies $5.00 for up to 4 pages. |
| **Cherokee** | `https://www.sclandrecords.com/sclr/` (county code `sc021`) | SC Land Records (Govtech/JSP multi-county portal) | **OPEN for search**; account needed only for the Fraud Alerts feature. Index from 1/3/1995, images from 9/25/2002, copies free. Caveat: the portal is a session/JSP app (`/sclr/controller` with `jsessionid`); a cold POST returns 0 bytes, so programmatic access requires bootstrapping the session first. |
| **Union** | `https://recordroom.cottsystems.com/unionsc/guest/Search/records` | Cott RecordRoom | **OPEN via the `/guest/` path** (HTTP 200). The bare `/unionsc` path 302s to `Portal/Account/LoginRoute`, which is what makes this look walled if you probe the wrong URL. Index metadata free; document images pay-per-view. Already wired in `rod/cott_recordroom.py`. |
| **Laurens** | `https://search.laurensdeeds.com/NameSearch.php` | Logan (older, NameSearch/NamePick) | **OPEN**, no login. Hard limitation: `search_type=Standard` only, meaning **name is required**. There is no name-less instrument-type date sweep. Distress labels are full text (`FORECLOSURE DEED`, `DEED OF DISTRIBUTION`, `TAX DEED`, `HOMEOWNERS ASSOCIATION LIEN`, `ORDER BY JUDGE`), not short codes. Cannot be swept, only name-queried. |

### North Carolina (11)

| County | ROD search URL | Vendor | Status |
|---|---|---|---|
| **Buncombe** | `https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/SrchName.aspx` | Aumentum / Cott eSearch v4 | **OPEN as "Guest User."** Important gotcha: a cookieless request redirect-loops to `/External/User/Login.aspx`. With a cookie jar it lands directly on the search page with the full Quick Name / Advanced Name / Property / Book-Page / File Number / Date Range menu and `litCurrentUser` reading "Guest User." **Do not classify Buncombe as login-walled based on the 302.** County landing: `https://www.buncombenc.gov/457/Register-of-Deeds`. |
| **Henderson** | `https://us4.courthousecomputersystems.com/hendersonnc/` | CCHS classic ASP | **OPEN**, no login (HTTP 200). |
| **Gaston** | `https://gastonnc.courthousecomputersystems.com/` | CCHS | **OPEN**, no login (HTTP 200, 132 KB app). **CHANGED.** Gaston switched vendors on 2026-05-28. |
| **Cleveland** | `https://us5.courthousecomputersystems.com/clevelandnc/` | CCHS classic ASP | **OPEN**, no login. County landing `https://www.clevelandcounty.com/rod/` also 200. |
| **Rutherford** | `https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4/SrchName.aspx` | Cott / Aumentum v4 | **OPEN as guest** (HTTP 200). Note `rutherfordcountync.gov/onlinedeeds` returns a soft-404 ("we have updated our site recently") that still serves HTTP 200; the live link is on `/departments/register_of_deeds/index.php`. |
| **Burke** | `https://us5.courthousecomputersystems.com/burkenc/` | CCHS classic ASP | **OPEN**, no login. |
| **Lincoln** | `https://us4.courthousecomputersystems.com/lincolnnc/` | CCHS classic ASP | **OPEN**, no login. |
| **Polk** | `https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/SrchName.aspx` | Cott / Aumentum v4 | **OPEN as guest**, confirmed `litCurrentUser">Guest User`. Same cookieless redirect-loop artifact as Buncombe. County landing `https://www.polknc.gov/register_of_deeds.php`. |
| **McDowell** | `https://search.mcdowelldeeds.com/` | Logan "The Lookup" | **DOWN.** HTTP 500, empty body. |
| **Transylvania** | `https://search.transylvaniadeeds.com/` | Logan "The Lookup" | **DOWN.** HTTP 500, empty body. |
| **Mitchell** | `https://search.mitchelldeeds.com/` | Logan "The Lookup" | **DOWN.** HTTP 500, empty body. |

---

## 5. Live status deltas worth acting on

1. **Gaston's ROD adapter is pointed at a dead host.** `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/rod/aumentum.py:53` maps `("NC","Gaston")` to `https://deeds.gastongov.com/external/LandRecords/protected/v4`, which now **times out entirely** (curl exit 28, no response). Gaston migrated to CCHS on 2026-05-28. The correct target is `https://gastonnc.courthousecomputersystems.com/`, which means Gaston should move from the Aumentum adapter to the **CCHS adapter** (`rod/cchs.py`), whose county map is `(host, app_slug, root_slug)`. Note the Gaston install is at its own hostname, not `us4`/`us5`, so `cchs._base()` (`https://{host}.courthousecomputersystems.com/{app}`) needs a host of `gastonnc` and the app slug confirmed against the live app. `us4.courthousecomputersystems.com/gastonnc/` returns 404, so the shared-cluster pattern does not apply here.

2. **All three Logan NC counties are simultaneously 500ing.** Transylvania, McDowell, and Mitchell all return HTTP 500 with `Content-Length: 0` while Apache still issues a `PHPSESSID`. That is a **server-side PHP fault on the shared Logan deployment**, not a block, not a rate limit, and not a bug in `rod/logan.py`. Three counties failing identically points at one vendor-side incident. It will either self-heal or needs a call to the vendor. Do not spend engineering time on it.

3. **Two counties are misclassifiable as walled and are not.** Buncombe and Polk both 302 to a login page on a cookieless probe but resolve to a full guest session with cookies. Union SC looks walled at `/unionsc` and is open at `/unionsc/guest/Search/records`. Anderson SC looks walled at the ACPASS root and is open at `deed.cgi`. Any automated "is it up" check that does not carry cookies and does not use the exact guest path will produce four false negatives.

4. **Only one of the 18 is genuinely login-gated: Oconee SC** (free Tyler PublicSearch account). That is a registration wall, not a bot wall, and registering is a user decision, not something to automate around.

---

## Bottom line

The three things a deed search can **never** tell you, at any price, from any vendor:

1. **What is actually owed today.** Original principal is a decaying estimate the moment it is recorded. Nobody outside the servicer and the borrower knows the payoff.
2. **Whether anyone is behind.** Delinquency is a private contractual fact. Every "pre-foreclosure" signal in the public record is a *post*-delinquency artifact, typically 90 to 180 days after the first missed payment.
3. **Who is in the house and what shape it is in.** Not recordable, not recorded.

And the two structural traps specific to your footprint:

- **In North Carolina, the ROD is only half the record.** Judgments, mechanics liens, HOA liens, federal tax liens, and lis pendens are all at the **Clerk of Superior Court**. Property taxes are recorded **nowhere**. A NC ROD sweep with no court-lane companion is a materially incomplete lien picture.
- **In South Carolina, the deed record legally refuses to state a price on exactly the deeds you care about.** §12-24-40(13) exempts foreclosure and deed-in-lieu; (4) exempts divorce transfers; (8)/(9) exempt entity and family-trust transfers. §12-24-70 then says exempt deeds need not state value. That is a wall written into statute, and the correct response is to stop trying to get SC price out of the ROD and take it from the assessor CAMA card instead.

**Sources:**
[G.S. 105-228.30 (NC excise)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-228.30.html) · [G.S. 105-228.29 (excise exemptions)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-228.29.html) · [G.S. 105-228.28 (scope)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-228.28.html) · [G.S. 1-234 (judgment docket)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-234.html) · [G.S. 44A-12 (NC mechanics lien)](https://ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_44A/GS_44A-12.html) · [G.S. 47F-3-116 (NC HOA lien)](https://www.ncleg.net/enactedlegislation/statutes/html/bysection/chapter_47f/gs_47f-3-116.html) · [G.S. 44-68.12 (NC federal liens)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_44/GS_44-68.12.html) · [G.S. 1-117 (lis pendens cross-index)](https://law.justia.com/codes/north-carolina/chapter-1/article-11/section-1-117/) · [G.S. 45-21.17 (notice of sale)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-21.17.html) · [G.S. 105-355 (tax lien)](https://www.ncleg.gov/enactedlegislation/statutes/html/bysection/chapter_105/gs_105-355.html) · [Coates' Canons, Nuts and Bolts of Property Tax Liens](https://canons.sog.unc.edu/2015/01/the-nuts-and-bolts-of-property-tax-liens/) · [G.S. 47-18 (recording/leases)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47/GS_47-18.html) · [G.S. 25-9-501 (fixture filings)](https://www.ncleg.net/EnactedLegislation/Statutes/HTML/BySection/Chapter_25/GS_25-9-501.html) · [G.S. 28A-15-2 (title vests in heirs)](http://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_28A/GS_28A-15-2.html) · [SC Code Title 12 Ch. 24 (deed recording fee, §12-24-40 and §12-24-70)](https://www.scstatehouse.gov/code/t12c024.php) · [SC DOR Deed Recording Fee Manual](https://dor.sc.gov/sites/dor/files/Documents/Policy%20Manuals/Deed%20Recording%20Fee%20Manual%202024.pdf) · [SC Code §29-5-90 (mechanics lien)](https://law.justia.com/codes/south-carolina/title-29/chapter-5/section-29-5-90/) · [SC Code §15-11-10 (lis pendens)](https://law.justia.com/codes/south-carolina/title-15/chapter-11/section-15-11-10/) · [SC Code §30-9-30 (indexing/filing)](https://law.justia.com/codes/south-carolina/title-30/chapter-9/section-30-9-30/) · [Gaston County Register of Deeds](https://www.gastongov.com/730/Register-of-Deeds) · [Buncombe County Register of Deeds](https://www.buncombenc.gov/457/Register-of-Deeds) · [Oconee County Register of Deeds](https://oconeesc.com/departments/register-of-deeds) · [Cherokee County SC Register of Deeds](https://cherokeecountysc.gov/register-of-deeds/) · [Polk County NC Register of Deeds](https://www.polknc.gov/register_of_deeds.php) · [Rutherford County NC Register of Deeds](https://www.rutherfordcountync.gov/departments/register_of_deeds/index.php)