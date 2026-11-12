# THE IMPOSSIBLE AND THE HYPOTHETICAL

Verification key: **[V]** = statute text fetched and read this session (URL given). **[K]** = cited from knowledge, not fetched this session, treat as unverified until checked.

**Headline finding before anything else:** the single largest legal exposure in this business is not scraping. It is **S.C. Code 30-2-50**, which makes it a misdemeanor to knowingly obtain or use personal information from an SC public record for commercial solicitation. The board's SC half is built entirely from SC public records, and "personal information" is defined to include name, home address, and home telephone number. Details and the one real counterargument are in Section 1.C. This needs an SC attorney opinion, not mine.

---

## SECTION 1: LEGALLY SEALED OR RESTRICTED

### 1.A Sealed by statute or court order (no price unlocks these)

| Category | Authority | What is actually blocked | Blunt read |
|---|---|---|---|
| Juvenile records | **NC G.S. 7B-3000** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_7B/GS_7B-3000.html)) | Examination limited to the juvenile, counsel, parent/guardian, prosecutor, court counselor, probation. Everyone else needs a court order. Magistrates and LE may view but not photocopy. | Irrelevant to lead-gen anyway. Do not build against it. |
| Adoption records | **NC G.S. 48-9-102** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_48/GS_48-9-102.html)) | "All records created or filed in connection with an adoption, except the decree of adoption and the entry in the special proceedings index... are confidential." All indices sealed permanently on finality. | Kills adoption as an heir-discovery route. The Special Proceedings Index entry survives, which is a name-only breadcrumb, nothing more. |
| Mental health / commitment records | **NC G.S. 122C-52** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_122C/GS_122C-52.html)) | "Confidential information acquired in attending or treating a client is not a public record under Chapter 132." | Involuntary-commitment as a distress signal is permanently closed. Guardianship/incompetency proceedings (Chapter 35A) are a partial, separate public lane. |
| Expunged criminal records (NC) | **NC G.S. 15A-153** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_15A/GS_15A-153.html)) | Person may lawfully deny the arrest. Employers/schools may not require disclosure or inquire; penalty is a warning then up to $500 per additional violation. No private cause of action. | The restriction runs to inquiry and use, not just to the file. Any cached pre-expunction copy in the engine becomes a liability, not an asset. |
| Expunged/dismissed arrests (SC) | **SC Code 17-1-40** [V] ([scstatehouse](https://www.scstatehouse.gov/code/t17c001.php)) | Arrest/booking record, bench warrants, **mugshots and fingerprints must be destroyed**. LE may hold under seal 3 years 120 days. **17-1-60** binds private publishers: must remove within 30 days of a documented written request, may not charge a fee, misdemeanor plus civil damages for violation. | This is the one expungement regime with teeth against a private data holder. The jail-booking scraper lane must carry a purge path or it is a statutory violation waiting to happen. |
| Sealed civil court files | Inherent judicial authority; SC Rule 41.2 SCRCP [K, fetch 404'd] | Whole file or discrete exhibits removed from the index. Often the exact settlement or valuation you want. | You usually cannot even tell a sealed file exists. Silent gap, not a detectable one. |
| Criminal investigation records | **NC G.S. 132-1.4** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.4.html)) | Investigation files are not public records. Mandatory release is narrow: time/date/location/nature of the violation; **name, sex, age, address, employment, alleged violation of a person arrested or charged**; arrest circumstances; 911 content with carve-outs. | The mandatory-release list is why arrest data works at all. Note "address" is in it and DOB is not. |
| SC FOIA exemptions | **SC Code 30-4-40** [V] ([scstatehouse](https://www.scstatehouse.gov/code/t30c004.php)) | Exempts trade secrets, "unreasonable invasion of personal privacy," LE materials, **medical records, hospital reports, scholastic records, adoption records**, attorney correspondence and work product. | SC exemptions are broader and more discretionary than NC's. Expect more denials on the same request wording. |

### 1.B Federally restricted (the ones that actually bite this business)

| Category | Authority | Verified holding | Consequence for the engine |
|---|---|---|---|
| **Bank/servicer customer data by pretext** | **15 U.S.C. 6821** [V] ([Cornell](https://www.law.cornell.edu/uscode/text/15/6821)) | Prohibits obtaining or attempting to obtain customer information of a financial institution "by making a false, fictitious, or fraudulent statement" to institution staff **or to customers**. 6821(b) also bars *asking someone else* to do it. | Calling a servicer posing as the borrower to get a payoff is a federal crime, and so is hiring anyone to do it. This closes the most-wanted field in the whole business by the most tempting route. The only door is Section 4. |
| **Credit reports** | **15 U.S.C. 1681b** [V] ([Cornell](https://www.law.cornell.edu/uscode/text/15/1681b)) | (a)(3) permissible purposes are credit transaction, employment, insurance underwriting, government license, investor/servicer valuation of an *existing* credit obligation, business transaction *initiated by the consumer*, account review. (a)(2): "In accordance with the written instructions of the consumer to whom it relates." | **A cash buyer of a house has no (a)(3) permissible purpose.** Pulling credit to estimate a stranger's equity is an FCRA violation. (a)(2) written instruction is the only clean route and it requires the seller at the table. |
| **Federal tax records** | **26 U.S.C. 6103** [V] ([Cornell](https://www.law.cornell.edu/uscode/text/26/6103)) | "Returns and return information shall be confidential." | Income, Schedule E rental data, and installment-sale reporting are permanently out. Nobody sells this. |
| **Driver / motor vehicle records** | **18 U.S.C. 2721** [V] ([Cornell](https://www.law.cornell.edu/uscode/text/18/2721)) | DMV "shall not knowingly disclose." (b)(12) allows bulk marketing/solicitation **only "if the State has obtained the express consent of the person."** Research use allowed only if "not published, redisclosed, or used to contact individuals." | DMV address and DOB are closed for outreach. The research exception is useless because it forbids contact, which is the entire point. |
| **Health information** | HIPAA Privacy Rule, 45 CFR 164.502 [K, eCFR redirected] | Binds covered entities and business associates. | Health-driven distress (illness forcing a sale) is unobtainable except from the seller's own mouth. |
| **Bank records via government process** | **12 U.S.C. 3402** [V] ([Cornell](https://www.law.cornell.edu/uscode/text/12/3402)) | "no **Government authority** may have access to..." | Blunt correction to a common assumption: RFPA restricts the *government*, not you. It is not your obstacle. **GLBA 6821 is.** Do not cite RFPA as the reason you cannot get bank data. |
| **Payoff statements** | **15 U.S.C. 1639g** [V] ([Cornell](https://www.law.cornell.edu/uscode/text/15/1639g)); **12 CFR 1024.36** [V] ([CFPB](https://www.consumerfinance.gov/rules-policy/regulations/1024/36/)) | 1639g: accurate payoff balance within "no case more than 7 business days" after written request "from or on behalf of the borrower." 1024.36: borrower or documented representative; acknowledge in 5 business days; 10 business days for owner/assignee identity; 30 business days otherwise; **servicer may not charge a fee**. | Restricted, not impossible. This is a **consent-gated** field, see Section 4. |
| **Telephone solicitation** | **NC G.S. 75-102** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_75/GS_75-102.html)) | No solicitation to a number on the national DNC registry. Affiliate EBR exemption exists at (c)(5) but collapses on request, with 60-business-day scrub. | Prior note that there is "no NC/SC DNC" is right only in the narrow sense that neither state runs its own list. NC statutorily enforces the **federal** list. Cold-calling scraped numbers without DNC scrubbing is exposure in NC. |

### 1.C State public-records carve-outs and commercial-use limits

**The SC problem, stated plainly.**

- **SC Code 30-2-50(A)** [V]: "A person or private entity shall not knowingly obtain or use personal information obtained from a state agency, a local government, or other political subdivision of the State for commercial solicitation directed to any person in this State."
- **(B)** requires every SC agency to notify requestors of this. **(C)** requires agencies to take reasonable measures to prevent it. **(D)** makes a knowing violation a misdemeanor, up to $500 and/or up to one year.
- **30-2-30** [V] defines "personal information" to include **name, home address, home telephone number**, DOB, SSN, financial status, employment history, and more. The exclusions are narrow (accident and driving-violation data, DOR business addresses).
- "Commercial solicitation" is defined as contact by phone, mail, or email "for the purpose of selling or marketing a consumer product or service," with exclusions only for credit unions, continuing education, GLBA-covered banking/insurance/securities, and political contact from voter registration data.

**The honest counterargument:** an unsolicited offer to *buy* the recipient's house is arguably not "selling or marketing a consumer product or service" *to* the recipient. That reading is available and is presumably how every SC direct-mail wholesaler operates. It is also not a reading I can validate, there is no case law in front of me, and the statute's plain text plus the mandatory agency notice under (B) cut the other way. **Get an SC real estate attorney's written opinion before the next SC mail drop.** This is the highest-value legal question in the file and it is cheap to answer.

**NC is the mirror image and it is permissive.**

- **NC G.S. 132-6(b)** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-6.html)): "No person requesting to inspect and examine public records... shall be required to disclose the purpose or motive for the request." **(c)**: commingled confidential data is not grounds for denial, and the agency bears the separation cost.
- No general NC commercial-use ban on public records. NC mail from public-records-derived lists is clean at the state-records level (federal DNC still applies to calls).

**The one NC commercial-use restriction that does apply:**

- **NC G.S. 132-10** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-10.html)): counties and cities **may** condition electronic copies of GIS databases on a written agreement that the copy "will not be resold or otherwise used for trade or commercial purposes." Statutory exceptions to what counts as commercial use: **news media publication, real estate trade association activities, Multiple Listing Service operations, and professional use by licensed practitioners in their practice.**
- Blunt: a real estate investor is not on that list. **A licensed NC real estate broker is.** See Section 3, item 5, this is the cheapest legal unlock available.

**Other state carve-outs:**

- **NC G.S. 132-1.1(c)** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.1.html)): "Billing information compiled and maintained by a city or county or other public entity providing utility services... is not a public record." Exceptions are bond-related, service-integrity, and law-enforcement/judicial. **Utility shutoff and consumption as a vacancy signal is legally closed in NC.** Do not build a scraper against it and do not FOIA for it; the request will be denied on the statute.
- **NC G.S. 132-1.10** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.10.html)): SSNs and identifying information are confidential and not public record; registers of deeds and courts may proactively OCR-redact online images. This is why deed-of-trust OCR yields loan amounts but no borrower identifiers, and why the redaction coverage will keep increasing over time. Plan for OCR yield to degrade, not improve.
- **NC G.S. 132-1.2** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.2.html)): 11 confidential categories, mostly irrelevant here, but note voter DOB/DL/partial SSN and electronic payment account numbers.
- **NC G.S. 163-82.10** [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-82.10.html)): voter lists are public with **name, residence address, mailing address, sex, race, age but NOT date of birth**, party, precinct. SSN, DOB, email, DL number, and photos are confidential. Signatures may be viewed but not copied. No commercial-use ban in the statute. **NC voter file cannot supply DOB.** That confirms jail booking DOB is genuinely net-new and not substitutable in NC.
- **SC voter lists**: sold by the SEC with a fee schedule (base electronic list reduced to $25 in 2022; larger tiers run into the hundreds up to a capped maximum) [search-sourced, [scvotes](https://scvotes.gov/resources/sale-of-voter-registration-lists/) not directly fetched]. **30-2-50 applies on top**, and the political-contact exclusion in 30-2-30 protects political use only, not yours.
- **HUD USPS Vacancy Data**: aggregated at **census tract** only, and HUD states it may make the data accessible **only to governmental entities and non-profit organizations** registered as users [search-sourced from [huduser](https://www.huduser.gov/portal/datasets/usps.html); direct fetch returned empty]. A for-profit REI is ineligible, and tract-level aggregation would be useless for parcel targeting even if eligible. Close this avenue.

### 1.D Privilege and private contract

- **Attorney-client and work product**: SC 30-4-40 [V] expressly exempts "correspondence or work products of legal counsel for a public body." NC has the parallel. Foreclosure firm files, servicer loss-mit notes, and internal valuation memos are permanently closed. This is why the ALAW/Hutchens-Foundation firm lanes yield only the public notice content and never the reserve, the BPO, or the client's floor price.
- **Confidential settlements**: enforceable private contracts. The dollar figure in a settled construction-defect or partition action is unobtainable even when the case file is open.
- **Sealed exhibits in open cases**: appraisals and payoff letters attached to a foreclosure complaint are sometimes sealed or redacted individually while the docket stays public.

---

## SECTION 2: PHYSICALLY UNRECORDED

Nobody wrote these down. There is no vendor, no FOIA, no price. Every one of them is discovered by a human conversation or a site visit, which is the actual argument for spending on outreach capacity instead of on data.

**2.1 Unrecorded interests that legally exist but leave no trace**

- **Short leases.** NC G.S. 47-18 (the Connor Act) [V] ([ncleg](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47/GS_47-18.html)) requires registration only for leases **longer than three years**. SC 30-7-10 [K, search-sourced] requires recording only for landlord-tenant contracts **longer than twelve months**, and SC law expressly provides that **possession does not give constructive notice** of an unrecorded instrument. So a 12-month or 35-month lease at a below-market rent is fully valid, fully invisible, and binds you after closing.
- **Contracts for deed / land contracts / lease-options.** Recordable, routinely unrecorded, especially in exactly the low-equity rural inventory this engine surfaces. The "owner" in the tax roll may have sold the beneficial interest years ago.
- **Handshake family arrangements.** "Mom deeded it to me but my brother lives there and I promised he could stay." No instrument, no consideration, no record. This is the single most common deal-killer on probate and heir-property leads and it is 100% undetectable pre-contact.
- **Verbal heir agreements and informal partitions.** Six heirs, an oral understanding about who gets what, no partition action. The deed shows six tenants in common and tells you nothing about who actually controls the decision.
- **Life estates and occupancy promises made orally.** Sometimes reserved in a deed (recorded, findable), often not.
- **Private mortgage modifications, forbearance plans, and partial claims.** A loan-mod that re-amortizes a note or a HUD partial claim can change payoff by tens of thousands. Some partial claims record as a second lien; most modifications never record. Your recorded-DOT-principal proxy is wrong by an unknown amount in an unknown direction.
- **Oral or unrecorded easements, boundary agreements, and prescriptive claims.** The neighbor has used the driveway for 19 years. Nothing on the plat.
- **Unfiled mechanic's lien rights.** In NC the lien-agent designation is a partial signal, but the *underlying unpaid contractor* with time left to file is not on any list.

**2.2 Facts about the physical asset**

- **Actual interior condition.** No public source. Assessor condition codes are stale, clerical, and mass-appraisal-derived. Vision on a Street View image reads the roofline and the yard and nothing else.
- **Deferred maintenance dollar amount.** Roof age, HVAC age, foundation, septic function, mold, knob-and-tube, polybutylene, sagging floor joists. Permits capture only work someone pulled a permit for, which excludes most of what matters.
- **Whether the well and septic work.** Health department permits show the install, not the current function.
- **Contents and hoarding.** A material rehab cost line, invisible.
- **Whether it has been rented and to whom.** No registry in either state.

**2.3 Facts about the person**

- **Owner intent and motivation.** Whether they want to sell, whether they *would* sell at a number, what number, and by when. This is the field that determines the entire economics of the business and it exists only inside a person's head until asked.
- **Whether they already have a buyer.** Whether a wholesaler already has it under contract.
- **Family dynamics and who is actually the decision maker.** The signature you need may not be the name on the deed.
- **Financial pressure that has not yet hit a public record.** Job loss, medical debt, a business failing, a divorce being contemplated. All the "distress" the engine detects is distress that already reached a courthouse, which by definition means it is late and competitive.
- **Informal occupancy.** Who is actually living there: a squatter, a cousin, an ex-spouse, a tenant with no lease.
- **Whether the owner is even alive and reachable.** Obituary matching is a good proxy and is already built, but it is inference, not fact.

**Blunt structural point:** every category in 2.3 is knowable only through contact, and every category in 2.2 is knowable only through access. A perfect data engine still stops at the exact same place. The board is a *contact list*, and past a certain point more enrichment does not make it a better contact list.

---

## SECTION 3: THE HYPOTHETICAL PERFECT WORLD

Ranked by how much each would move the business, with the closest legal proxy and an honest grade.

### 3.1 A live, property-level mortgage payoff and lien-balance feed
**Perfect version:** every parcel carries current unpaid principal, per-diem interest, escrow advances, arrears, servicer, and investor, refreshed nightly.

**Why it wins:** it converts 30,000 undifferentiated leads into a ranked list by real equity. Everything else is a rounding error next to this. It is also the field the engine currently has at 0.0% recorded loan dollars.

**Does it exist? No, at any price.** Servicer loan tapes trade in bulk between institutions under confidentiality and are governed by GLBA; they are not sold to acquisition buyers, and pretexting for them is a **15 U.S.C. 6821 [V]** crime. MERS ServicerID returns the servicer name and never a balance.

**Closest legal proxies, stacked:**

| Proxy | Source | Grade | Notes |
|---|---|---|---|
| Recorded deed-of-trust **original principal** + amortization model | ROD document images, free, OCR pipeline already built | **B-** for ranking, **F** for exactness | Blind to modifications, HELOC draws, and extra principal. Systematically overstates debt on old loans and understates it on cash-out refis. |
| **Judgment amount** in a foreclosure decree | NC eCourts / SC MIE | **A** as of the judgment date, for that cohort only | Exact and legally certified. Already on 187 leads. Should be the priority parse target. |
| **Opening bid / upset bid floor** | Auction and MIE notices | **B** | Approximates debt plus costs. Already on 723 leads. |
| **Tax balance** | qPayBill and county rolls | **A** where it works | Exact, and it is a real lien with priority. |
| Assessor value minus modeled debt | CAMA plus DOT | **C** | This is what the board mostly does now. Treat every equity number under this method as an ordering hint, not a figure. |

**Realistic ceiling:** you can get to a defensible *rank ordering* of equity. You cannot get to a number you would wire money against. Accept that and stop paying for products that promise otherwise.

### 3.2 A real-time "this owner is considering selling" signal
**Perfect version:** an intent feed, like ad-tech intent data but for home sale.

**Does it exist? No, legitimately.** Vendors sell "predictive seller scores" (propensity models). They are models, not signals. They are built on the same public inputs you already have plus consumer marketing data of dubious provenance, and their published accuracy claims do not survive contact with a holdout test.

**Closest legal proxies:**
- **Multi-signal recency stacking.** Two or more independent distress events within 90 days on the same parcel is the strongest free intent signal that exists. Probate filed plus tax delinquent, or divorce filed plus absentee owner, beats any single-source score.
- **Listing lifecycle events** (listed then withdrawn/expired, price cut, relisted) are the best real intent signal in existence, and they live in the MLS. See 3.5.
- **FSBO and "for rent by owner" postings.** Public, self-published, high intent, and small in volume.
- **Absentee plus age plus long tenure.** Owner mailing address different from situs, owner over 70, owned 20-plus years. Free from the tax roll. Grade **B** as a propensity proxy and it costs nothing.
- **NCOALink move detection.** Legal path below in 3.6.

**Grade: C+.** Stacking gets you a genuinely better call list. Nothing gets you intent.

### 3.3 National skip-trace with consent
**Perfect version:** name to current phone, email, and address, verified, with contact consent attached.

**What is legally real:** identity-graph products (LexisNexis Accurint, TransUnion TLOxp, IDI) are **non-FCRA** products gated by certified permissible use under GLBA and DPPA. "I want to buy this person's house" maps poorly onto the standard permissible-use list, which is why these vendors underwrite accounts and why marginal REI accounts get shut down. Do not paper over that with a false use certification; that is fraud in the certification and it re-opens 6821 and DPPA exposure.

Anything FCRA-covered is closed outright: **1681b(a)(3) [V]** has no acquisition-buyer purpose.

**Closest legal proxies, all free or near-free:**
- **Tax-roll owner mailing address.** The single highest-value free skip-trace field in existence. It is the owner's self-reported current mailing address, updated by the owner because they want their tax bill. Free, public, in both states. Grade **A-**.
- **NC Secretary of State registered agent and officers** for entity-owned parcels. Built. Free. Grade **A** for entity owners, which is a large slice of the board.
- **Obituaries plus funeral-home notices** for heir names. Built. Grade **B+**.
- **NC voter file** for name-address confirmation, no DOB [V]. Grade **B** in NC, and SC's equivalent is 30-2-50-encumbered.
- **NCOALink through a licensed mail service provider.** You do not license NCOALink yourself; USPS licenses Full Service, Limited Service, and End User tiers, and every licensee must hold a Processing Acknowledgement Form per customer [search-sourced, [PostalPro](https://postalpro.usps.com/mailing-and-shipping-services/NCOALink)]. Your **mail house already holds this license.** Running your list through their standard CASS plus NCOA processing is normal, cheap, and fully legal, and it returns move flags and forwarding addresses. **This is an underused legal unlock.** Grade **A-** for "did they move," cost is pennies per record.

### 3.4 Verified occupancy
**Perfect version:** per-address occupied/vacant, refreshed monthly.

**HUD USPS Vacancy Data is not it.** Census-tract aggregate, and access limited to governmental entities and non-profits [search-sourced]. Ineligible and useless at parcel level. Close this.

**Closest legal proxies:**
- **USPS DSF2 vacancy indicator through your licensed mail service provider.** Per-address, delivery-point-level, derived from carrier reporting. Same access pattern as NCOA: your mail house holds the license. Grade **A-**. This is the correct answer to the vacancy question and it is being missed.
- **Returned mail as a feedback loop.** You are already mailing. Nixie returns are ground-truth vacancy and address-quality data that you generate for free and are probably discarding. Grade **A** on the subset you have mailed, **F** on everything else.
- **Code enforcement and nuisance abatement records** (Asheville built). Grade **B**, high specificity and low recall.
- **Homestead/owner-occupancy exemption absent on the tax roll.** Grade **B** for non-owner-occupied, which is not the same as vacant.
- **Street View imagery recency plus vision.** Grade **C+**, and the imagery is often two to four years stale in rural WNC and the Upstate.
- **Utility disconnection: legally closed in NC** per 132-1.1(c) [V]. Stop pursuing.

### 3.5 Full MLS access
**Perfect version:** active, pending, sold, withdrawn, expired, days on market, price history, agent remarks, photos, and showing activity.

**Value:** it is the best comp source, the best condition source (photos and remarks), and the only real intent feed (withdrawn and expired). It would raise ARV confidence more than any other single input, and the valuation memo already flags ARV as unbiased-at-median but noisy.

**Legal paths, in order of honesty:**
1. **Get licensed.** An NC or SC real estate broker license (prelicensing course plus exam plus fees, roughly the low four figures all-in) makes you eligible for MLS participation and, separately, drops you into the **G.S. 132-10 [V] "licensed practitioners in their practice"** exception on county GIS commercial-use agreements. Two structural unlocks for one cost. **This is the highest-ROI legal move on this entire list.**
2. **Partner with a broker** who provides comps under their license within their MLS's rules. Cheaper, slower, and dependent on a person.
3. **IDX feed:** display-only. IDX rules prohibit data mining and downstream use, and sold data is frequently excluded. Not a database.
4. **Scraping Zillow, Redfin, or Realtor.com:** ToS violation, and the operational reality is DataDome and equivalent. Already correctly classified as a wall.

Note NAR repealed or amended 18 MLS policy statements effective January 1, 2026, moving non-member MLS access to **local discretion** [search-sourced, [NAR](https://www.nar.realtor/about-nar/policies/mls-policy)]. That means Canopy MLS and the Upstate SC MLSs each set their own non-member terms now. **Worth one phone call each.** It may already be cheaper than assumed.

**Free proxy grade without a license: C.** Recorded sale prices from the ROD are the honest substitute and NC records consideration well while SC exempt deeds state no value (already documented). Assessor sale histories via qPublic per-parcel cards are the SC workaround, also already documented.

### 3.6 A complete lien-priority engine
**Perfect version:** every parcel with an ordered, certified lien stack and exact balances.

**Does it exist? Yes, and it is called a title search, and it is priced per property and produced by humans.** There is no bulk version because priority requires legal judgment about chain, indexing errors, name variants, and unrecorded superpriority, not just a database join.

- **O&E report (current-owner search, typically 30 years):** roughly **$35 to $275** per property in NC, commonly $75 to $100 [search-sourced, e.g. [Title Search Direct](https://titlesearchdirect.com/north-carolina-title-search/), [ProTitleUSA](https://protitleusa.com/services/products/oe_report)]. SC pricing was not verified.
- **Free proxy:** ROD grantor/grantee index chains plus judgment docket plus tax lien status. Gets you a **probable** stack. Grade **B-** for triage, **F** for anything you would bid on.
- **Correct operating rule:** never pay for title work at the lead stage. Order one O&E after you have a verbal, per deal. At $75 against a deal-sized spread, this is not a data problem, it is a line item.

### 3.7 The honest ranking

If you could have exactly one, take **3.1 (payoff)**. If you could have two, add **3.5 (MLS)**, because it is the only one on this list with a legal path you can actually walk this quarter. **3.2 and 3.3 do not exist in the form people sell them in**, and 3.4's best version is sitting inside your mail vendor's existing license.

---

## SECTION 4: THE CONSENT PATH

This is the honest route to most of Section 1. Everything below is unobtainable cold and routine once the seller signs. Deal stages: **Cold** (no contact), **Contact** (conversation happened), **LOI** (verbal/written offer), **Contract** (executed PA), **DD** (due diligence), **Closing**.

| # | Field unlocked | Instrument the seller signs | Legal hook (verification) | Timeline | Cost | Unlocks at |
|---|---|---|---|---|---|---|
| 1 | **Exact mortgage payoff** (UPB, per diem, good-through date) | Borrower's Authorization to Release Information, plus written payoff request | **15 U.S.C. 1639g** [V]: within **7 business days** of a written request "from or on behalf of the borrower". **NC G.S. 45-36.7** [V]: **10 days**, and NC defines "entitled person" in **45-36.4** [V] as borrower, landowner, **or a person who has contracted to purchase the property** | 7 to 10 days | NC: **one free per six-month period**, then **$25**; short-pay statement $25/$100 tier; **12 CFR 1024.36 [V] forbids any fee** for a servicer information request | **LOI**. Note the NC "contracted to purchase" hook lets **you** request directly once under contract |
| 2 | **Reinstatement figure** (arrears, fees, corporate advances) | Same authorization | Reg X information request, **12 CFR 1024.36** [V] | 30 business days, +15 with notice | $0 | **Contract**. Essential for any reinstate-and-take-over structure |
| 3 | **Full loan terms**: rate, maturity, escrow balance, ARM index, assumability, due-on-sale posture | Same authorization | **12 CFR 1024.36** [V]; identity of owner/assignee in **10 business days** | 10 to 30 business days | $0 | **DD**. This is the field that makes or breaks a subject-to or wrap |
| 4 | **Full personal lien and judgment picture** (everything not tied to the parcel) | **Written instruction of the consumer**, a distinct signed authorization | **15 U.S.C. 1681b(a)(2)** [V]. You have no (a)(3) purpose, so this is the only route | Same day | roughly $10 to $40 | **Contract**. Do not do this earlier and do not do it without the signature |
| 5 | **HOA unpaid assessments, fines, violations, special assessments** | Owner's written request to the association, or contract clause obligating owner to obtain it | **NC G.S. 47F-3-118(b)** [V]: statement of unpaid assessments to a lot owner or **authorized agent**, **within 10 business days**, **binding on the association** | 10 business days | **NC: up to $200**, plus up to **$100** expedite if within 48 hours of closing | **Contract**. The binding effect is the whole point, an informal email from a board member is worthless |
| 6 | **HOA books, budget, insurance, reserves, litigation** | Owner request as a member | **NC G.S. 47F-3-118(a)** [V]: records "reasonably available for examination by any lot owner and the lot owner's authorized agents" under the bylaws and Chapter 55A | Per bylaws | Copy cost | **DD** |
| 7 | **Condominium resale disclosure** | Owner statement to purchaser | **NC G.S. 47C-4-109** [V]: unit owner "shall furnish to a prospective purchaser before conveyance a statement" of monthly common expense assessment and other fees | Before conveyance | Nominal | **Contract**. Narrower than a full resale certificate, do not assume it covers arrears |
| 8 | **SC HOA arrears** | **Contract clause only** | **No SC statutory estoppel found.** SC Homeowners Association Act 27-30-150 [V] addresses access to the budget and membership list and cross-references the nonprofit records statutes; **it does not require a statement of unpaid assessments** | Whatever you negotiate | Whatever they charge | **Contract**. **This is a real gap: in SC, if your purchase agreement does not require the seller to produce an association ledger, nobody has to give you one.** Fix the template |
| 9 | **Certified lien priority** (O&E, then commitment) | No seller signature needed for an O&E (public records); commitment needs the transaction | Title insurance underwriting | 1 to 5 business days for O&E | roughly **$35 to $275**, commonly $75 to $100 in NC [search-sourced] | **Contract**. Never at lead stage |
| 10 | **Property tax payoff including deferred/rollback taxes** | Owner or agent request | Present-use-value deferred taxes, NC G.S. 105-277.4 [K]; county treasurer payoff | Same day to a few days | $0 to nominal | **DD**. Rollback on farm and forestry parcels is a five-figure surprise if missed |
| 11 | **Utility account status, arrears, final read, and consumption history** | Customer (owner) authorization to the utility | **NC G.S. 132-1.1(c)** [V] makes it non-public, so **only the customer can release it** | Days | $0 | **DD**. Also the only lawful route to consumption data as an occupancy proof |
| 12 | **Insurance loss history (CLUE)** | Owner requests **their own** report and shares it | FCRA-covered consumer report, consumer-access right | Days | Free once per year to the consumer | **DD**. Prior water, fire, or roof claims are the cheapest condition intelligence in the deal |
| 13 | **Interior condition, contents, systems** | Access agreement or inspection contingency | Contract | Immediate | Inspection cost | **Contract**. **No dataset substitutes. Ever.** |
| 14 | **Actual lease terms, rent, deposits, occupancy** | **Tenant estoppel certificates**, required by your PA | Contract, not statute | Days | $0 | **DD**. This is the only mechanism that surfaces the unrecorded short leases from Section 2.1 |
| 15 | **Bank statements, proof of arrears, hardship documentation** | Seller provides voluntarily | GLBA. **Never request it from the institution: 15 U.S.C. 6821** [V] | Immediate | $0 | **DD**. Seller-provided only, always |
| 16 | **Judgment payoff and satisfaction figures** | Debtor authorization to the creditor or creditor's counsel | Creditor payoff letter | Days to weeks | $0 to nominal | **Contract** |
| 17 | **Authority to sell in an estate** (letters testamentary, heirship) | Public filing, but **agreement of all heirs is private** | Probate file is public | Varies | Filing costs | **Contact**. The public file gives you the names; only conversation gives you the consent |
| 18 | **Capacity and competency questions** | HIPAA authorization or guardianship order | 45 CFR 164.502 [K] | Slow | Legal cost | **DD**. Rare, and if you need it you probably need counsel more |

### The blunt conclusion on the consent path

**Every single row above unlocks at Contact or later.** Not one of them is available at the ranking stage. That is the whole finding.

Which means the payoff-data problem is not solvable by buying data, and the money currently aimed at closing the equity gap is aimed at the wrong target. The correct sequence is: **rank on free proxies, make contact, and let the signature open the vault.** The board's job is to decide *who to call*, not to decide *what to pay*. It is already good enough for the first job and it will never be good enough for the second.

**Three concrete actions this analysis produces:**

1. **Get an SC attorney's written opinion on 30-2-50 before the next SC mail drop.** Cheapest, highest-stakes open question in the business.
2. **Call your mail house and ask for NCOALink move flags and DSF2 vacancy indicators on the existing list.** They already hold the license. This is Sections 3.3 and 3.4 solved for pennies per record, legally, this month.
3. **Price out an NC broker license.** It unlocks MLS eligibility and the G.S. 132-10 licensed-practitioner GIS exception simultaneously, and NAR's January 2026 shift of non-member MLS access to local discretion means the Canopy and Upstate MLSs should each get a phone call first, because the answer may have changed.

**Sources:** [NC G.S. 132-1.1](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.1.html), [132-1.2](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.2.html), [132-1.4](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.4.html), [132-1.10](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.10.html), [132-6](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-6.html), [132-10](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-10.html), [7B-3000](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_7B/GS_7B-3000.html), [122C-52](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_122C/GS_122C-52.html), [48-9-102](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_48/GS_48-9-102.html), [15A-153](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_15A/GS_15A-153.html), [45-36.4](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-36.4.html), [45-36.7](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-36.7.html), [47-18](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47/GS_47-18.html), [47F-3-118](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47F/GS_47F-3-118.html), [47C-4-109](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47C/GS_47C-4-109.html), [163-82.10](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-82.10.html), [75-102](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_75/GS_75-102.html); [SC Title 30 Ch.2](https://www.scstatehouse.gov/code/t30c002.php), [SC Title 30 Ch.4](https://www.scstatehouse.gov/code/t30c004.php), [SC Title 17 Ch.1](https://www.scstatehouse.gov/code/t17c001.php), [SC Title 27 Ch.30](https://www.scstatehouse.gov/code/t27c030.php); [15 U.S.C. 6821](https://www.law.cornell.edu/uscode/text/15/6821), [15 U.S.C. 1681b](https://www.law.cornell.edu/uscode/text/15/1681b), [15 U.S.C. 1639g](https://www.law.cornell.edu/uscode/text/15/1639g), [18 U.S.C. 2721](https://www.law.cornell.edu/uscode/text/18/2721), [26 U.S.C. 6103](https://www.law.cornell.edu/uscode/text/26/6103), [12 U.S.C. 3402](https://www.law.cornell.edu/uscode/text/12/3402), [12 CFR 1024.36](https://www.consumerfinance.gov/rules-policy/regulations/1024/36/); [HUD USPS Vacancy](https://www.huduser.gov/portal/datasets/usps.html), [USPS NCOALink](https://postalpro.usps.com/mailing-and-shipping-services/NCOALink), [NAR MLS Policy](https://www.nar.realtor/about-nar/policies/mls-policy), [SC voter list sales](https://scvotes.gov/resources/sale-of-voter-registration-lists/).