# Goliath Data vs. Our Tool — Competitive Teardown

*Prepared 2026-07-02. Synthesizes three recon briefs (full site inventory, real-user sentiment sweep, and reverse-engineering probe). Our tool = the free public-records motivated-seller / foreclosure lead engine for the 18-county WNC + Upstate SC footprint.*

---

## 1. What Goliath Data Is

Goliath Data (goliathdata.com) is a venture-backed, AI-native real-estate prospecting **operating system** that fuses a distress-signal lead engine, bundled skip tracing, an AI voice agent named "David," and a built-in CRM + multi-channel outreach suite into one paid SaaS. It positions itself as "Beyond the CRM. The new standard for real estate," and explicitly sells consolidation — replacing the PropStream + a skip-trace vendor + a dialer + a CRM stack that it frames as costing "$400–$900+/mo" across tools ([platform](https://goliathdata.com/platform)). It is built for real-estate **investors/wholesalers** (primary) and **agents/realtors** (secondary), claims 11,000+ operators, nationwide 50-state coverage, and hourly data refresh ([home](https://goliathdata.com/)). Co-founders Max Yuan (CEO) and Austin Beveridge (COO); ~$1.65M raised (Better Tomorrow Ventures, Lightbank, Recursive Ventures, Brickyard, Night Capital, Teamworthy); HQ variously listed as Chattanooga, TN and New York, NY ([Crunchbase](https://www.crunchbase.com/organization/goliathdata), [f4.fund](https://f4.fund/startups/goliathdata)).

**Pricing tiers** (live [pricing page](https://goliathdata.com/pricing); annual = "2 months free"):

| Tier | Price/mo | Seats | Skip-traces/mo | Core inclusions |
|---|---|---|---|---|
| **Ramp** | **$299** | 3 | 2,500 (DNC cross-checked) | Core seller data (property records, owner details, MLS filters); basic workflows; all-in-one call/text/email; tasks/reminders/appointments/activity metrics |
| **Growth** (Popular) | **$899** | 5 | 10,000 | All Ramp + niche distress lists (pre-foreclosure, tax-delinquent, probate); advanced workflows; integrations (Google, Facebook, CallTools, ReadyMode); **David AI agent** (find→contact→qualify→book) |
| **Scale / Done-For-You** | **$2,999** | 10 | 10,000 | Fully managed: they tune the research agent to your markets/buy box, configure David's scripts, skip-trace + clean data, build/launch campaigns, set up pipelines + routing |
| **Blackbook** | Application-only | — | — | Delivered qualified listing appointments; "we qualify the seller, confirm intent, put the appointment on your calendar" |
| **Syndicate** | Invite-only | — | — | Daily feed of pre-vetted off-market deals; "we get paid when you do" (pay-per-result) |

*Note on price drift:* older SEO/blog pages and aggregators float lower anchors ($99/$83/$249, "10,000 records for $299"), and Capterra/Software Advice list Scale at $1,375–$1,699. The **live pricing page is authoritative: Ramp starts at $299** ([pricing](https://goliathdata.com/pricing), [Capterra](https://www.capterra.com/p/10035457/Goliath/), [Software Advice](https://www.softwareadvice.com/product/536319-Goliath/)). A 7-day free trial is advertised on the homepage but not on the pricing page. **All fees are non-refundable**, and Scale plans with staffed callers require 30 days' written cancellation notice ([Terms of Service](https://goliathdata.com/terms-of-service)).

---

## 2. Full Feature Inventory

Every feature/function surfaced across the site, grouped. Verbatim claims in quotes.

### Data & Lists
- **Real-time County + Court Records** — badged "Native"; property/ownership + deed/distress signals.
- **Hourly data + court updates** — "refreshed every hour"; signals caught "within the hour" of filing; marketing hook is a **"28-day advantage"** over competitors.
- **Nationwide 50-State Coverage** — "150+ markets" is the more conservative figure.
- **Pre-Foreclosures** — Notice of Default / Lis Pendens.
- **Tax-Delinquent** lists.
- **High-Equity filter** — targets homeowners with **40%+ equity**; "Four of five sellers go with the first investor they talk to."
- **Absentee Owners** flag.
- **Probate** — court filings.
- **Expired Listings** — MLS across 50 states, "updated daily."
- **Liens** — lien position + origination dates surfaced in enrichment.
- **Life-event / intent signals** — the differentiated layer: marriage licenses, job changes, family changes (pregnancy), code violations, evictions. "**500+ signals**, all answering why they would sell."
- **Native Seller Intent Scoring** — AI likelihood-to-sell score, "updates in real time as data changes," delivers an AI-ranked daily call list.
- **Advanced filter UI (14 fields):** City · Zip · Estimated Interest Rate 5–14% · Price (100k max) · **Seller Intent Score (60+)** · Estimated value (<$400k) · Bedrooms (3+) · Property Type (SFR) · Year Built (1990+) · Lot Size (0.25+ ac) · Interest Rate (<5%) · **Est. Equity (40%)** · MLS Status (Not Listed) · Owner Type (Individual).
- **"No exports"** — data lands directly in the in-app pipeline (marketed as a feature, not a limitation).

### Skip Tracing / Contact Append
- **AI Skiptracing** — verified phone + email + mailing address appended natively, "no per-record fees, no separate subscriptions."
- **DNC cross-check** — all skip-traces scrubbed against Do Not Call.
- **USPS address validation** + ownership cross-checks.
- **Bundled credits:** 2,500/mo (Ramp), 10,000/mo (Growth/Scale). Industry-benchmark figures cited in their SEO content (85–92% match, 24–72hr turnaround) are framed as sector norms, **not a Goliath SLA**.

### Comps & Analysis
- **Equity estimation** — mortgage status, origination dates, equity changes, lien position.
- **Property characteristics** — from county assessor data (beds, year built, lot size, value).
- **Seller Intent / likelihood-to-sell scoring** — the primary analytical output (there is **no ARV / rehab / MAO / comp-based valuation engine** surfaced anywhere on the site — this is a prospecting scorer, not an underwriting calculator).

### Outreach / Marketing Execution
- **Predictive Dialer** — parallel dialing, filters voicemail/dead air; localized area codes + number rotation; **DNC scrubbing, state calling-hour rules, TCPA consent tracking**; ringless voicemail drops; auto call recording/transcription/logging. ("Dial less. Talk more.")
- **Bulk Texting** — prewarmed **DIDs** (provisioning/registration/warming); compliant personalized SMS at scale; centralized inbox; automated reply handling via David; reply filtering (wrong numbers, opt-outs).
- **Bulk Emailing** — inbox warming + domain authentication; per-seller merge; CAN-SPAM opt-out/suppression/sender-auth; send-and-sign contracts from the inbox. Claims deliverability **10%→60%+**, reply rate **0.50%→3%+**.
- **Direct Mail** — postcard/letter, template or upload; **no minimums (1 piece → whole market)**; replies route (calls→David, texts→nurture agent); **QR code** pulls owner into pipeline with property attached; per-piece tracking.
- **Paid Ads** — builds a **custom audience of motivated sellers** from real-time data, **exports to Meta in one click**, spins up lookalikes; builds + hosts landing pages/forms; instant lead follow-up; cost-per-contract tracking.
- **Website / Landing Pages** — "spin up dozens" of seller-intake pages, no developer; point every channel at one page → same pipeline, source auto-tagged; **compliance record view** (name/email/property/IP/approx location on a map + submit timestamp + consent-click log to defend "I never signed up" complaints).
- **Automated Text + Drip Campaigns** — badged "Native"; drip sequences by lead type/stage.
- *Coming Soon:* Bulk Emails/Texts & Direct Mail as fully packaged bulk campaigns, plus Transaction Management, Dispositions Marketplace, Mobile App.

### AI Agent — "David by Goliath"
- **24/7 inbound call handling** — "zero missed leads," natural voice ("not a robotic IVR").
- **Multi-channel outbound** — reaches out via text/email/phone, switches channel by seller preference; responds to missed calls/form submissions/new signals instantly.
- **Auto-qualification** — motivation/timeline/condition/price expectation, using client's approved questions + objection scripts + tone matching.
- **Books walkthroughs** to calendar; tags leads by urgency; live-transfers to team; all calls recorded + summarized.
- **ROI framing:** human ISA = "$6,000–$8,000/mo"; David replaces the team "for a fraction of one ISA."

### CRM / Pipeline — "Command Center"
- **"The CRM that updates itself"** — every David call/text/appointment logged, summarized, assigned "before you open your laptop."
- **Morning intent scoring** — AI-ranked daily call list ranked by closing probability.
- **Unified Inbox** — two-way SMS/email/call in one thread, smart threading by contact, inbound-reply notifications, bulk messaging with personalization tokens.
- **Pipeline / Deal Management** — drag-and-drop builder, custom stages (acquisition/listing/wholesale), one-click contact + deal history, team assignment.
- **Workflow Automation** — if-this-then-that triggers; drip sequences by lead type/stage; priority-ranked daily agenda; deadline/overdue alerts.
- **AI Co-pilot** — flags stalling deals, quiet sellers, slipped tasks, unsigned contracts; suggests next moves for approval; auto-assign by territory/deal type/round-robin.
- **Close tools** — contract generation from deal data, same-day send, **phone-based e-signing**, real-time doc status/open-rate tracking, source attribution, per-rep performance.

### Team / Collaboration
- **Teams & Permissions** — role-based access; seats 3/5/10 by tier.
- **Analytics & Reporting** — cost per acquisition, agent conversion, marketing ROI, pipeline velocity.
- **Lead routing** — auto-assign by territory/deal type/round-robin.

### Mobile / Driving-for-Dollars
- **Mobile App** — **Coming Soon only** (not shipped). No driving-for-dollars route-tracking / photo-capture feature exists.

### Integrations
- **Google** (OAuth: Gmail/Calendar/Drive), **Google Cloud** (app hosting/storage).
- **Facebook/Meta** — custom-audience + lookalike export.
- **CallTools** and **ReadyMode** — real-estate dialers (Growth+).
- **Webhooks + REST API** — advertised; help docs are empty stubs (planned, not populated).
- **LiveChat** (site support), **Rewardful** (Stripe-based affiliate tracking → confirms Stripe billing).
- Explicitly positioned to **replace**: PropStream, BatchLeads, ListSource, Follow Up Boss, kvCORE, Top Producer, Lofty, standalone dialers, Zapier.

### Programs / Ecosystem
- **Blackbook** (application-only) — done-for-you qualified appointments.
- **Syndicate** (invite-only) — pre-vetted off-market deal feed, pay-per-result.
- **Affiliate program** — 20% recurring or one-time commission, payouts on the 15th.
- **Content moat** — 1,932-URL SEO network (756 county tax-delinquent pages, 264 encyclopedia terms, ~700 comparison/"best-of" articles, 71 local guides), all authored "Austin Beveridge."

---

## 3. Feature-by-Feature Gap Table

**Verdict key:** HAVE = we do this at rough parity · PARTIAL = we do a version, weaker/narrower · DON'T = absent from our tool. "If theirs is better, how" is honest — where they win, it says so plainly.

| Goliath feature | Do we have it? | If theirs is better, how |
|---|---|---|
| **DATA & LISTS** | | |
| Real-time county + court records | **HAVE** | Roughly even *within footprint*. We run 110 scrapers over the same county tax/court/ROD substrate. Theirs is nationwide; ours is 18 counties. |
| Hourly refresh / "28-day advantage" | **PARTIAL** | They win on cadence. They claim hourly ingest + signal-visible-within-the-hour. Ours is batch/scheduled runs, not continuous. Speed-to-signal is their marketed edge. |
| Nationwide 50-state coverage | **DON'T** | They win decisively. 18 counties vs. 50 states. This is their single biggest structural advantage over us. |
| Pre-foreclosure (NOD / Lis Pendens) | **HAVE** | Even, and arguably ours is *deeper* in-footprint: trustee law-firm feeds + Master-in-Equity rosters + lis pendens, court-confirmed. |
| Tax-delinquent lists | **HAVE** | Even/better in-footprint. We cover county tax-delinquent + tax-sale across the footprint incl. NC PTS Cloud + county PDFs + SC qPayBill balances. |
| High-equity (40%+) filter | **PARTIAL** | They compute an equity estimate from assessor + mortgage/lien data and let you filter on it. We derive equity via ARV/assessor but don't expose a clean nationwide equity-% filter. Slight edge theirs on UX. |
| Absentee-owner flag | **HAVE** | Even. We flag absentee via GIS owner-vs-situs mailing address. |
| Probate / estate / heirs | **HAVE** | Even/better in-footprint. We have probate/estate + **obituary-driven pre-probate heir** discovery (Gannett Upstate), which their "probate court filings" alone doesn't match. |
| Expired listings (MLS) | **DON'T** | They win. MLS-sourced expired/FSBO across 50 states. We have **no MLS access at all**. Purely an agent-side signal we can't touch. |
| Liens (position, origination) | **PARTIAL** | They surface lien position + origination inline. We have ROD deed/lien data + SC DOR tax liens + local ROD-$ OCR, but not packaged as a clean per-lead lien-position field. |
| Life-event signals (marriage, job change, pregnancy) | **DON'T** | They win — *if real*. These consumer life-event signals require paid data brokers we don't buy. (Caveat: the skeptic critique in §4 argues these barely predict selling.) |
| Code violations | **PARTIAL** | We have Asheville code-enforcement built + jail/eviction/vacant signals; theirs claims broader/nationwide. Even-ish in-footprint. |
| Evictions | **PARTIAL** | We gather evictions/partition via manual court gather (seller-side eviction is a confirmed wall for both). Roughly even. |
| Native seller-intent scoring | **PARTIAL** | They win on packaging. They ship a real-time 0–100 "Seller Intent Score" with a filter. We have distress scoring + **A–F grade** (comparable concept) but no single normalized intent number with the same UX polish. |
| 14-field advanced filter UI | **PARTIAL** | Their in-app filter panel is more polished. We have a hosted filterable dashboard + CSV export; fewer, coarser filter fields. |
| List stacking (multi-signal overlap) | **DON'T** | They implicitly stack (one owner, many signals, one record). We surface signals but have **no list-stacking UI** to rank owners appearing on N lists. Genuine gap. |
| **SKIP TRACING / CONTACT** | | |
| AI skip tracing — phone + email at scale | **DON'T** | They win decisively. 2,500–10,000 verified phones+emails/mo bundled. We have **owner mailing address only** + NC voter-file phone (~69% match, NC-only). No email, no phone at SC scale. **Their biggest day-to-day advantage.** |
| DNC cross-check | **DON'T** | They win. DNC scrubbing built in. We don't skip-trace, so nothing to scrub. |
| USPS address validation | **PARTIAL** | We resolve mailing addresses via GIS/parcel + situs resolvers (incl. Charleston address resolver). Not formal USPS CASS validation. |
| **COMPS & ANALYSIS** | | |
| Equity / mortgage / ownership analysis | **HAVE** | Even. Our ARV/rehab/max-bid/equity engine is arguably *more* investor-underwriting-grade than their prospecting-only equity estimate. |
| ARV / rehab / MAO valuation | **HAVE (we win)** | **We beat them.** They have **no ARV/rehab/max-bid engine** — theirs is a lead scorer, not an underwriting calculator. Ours computes ARV + rehab + max-bid + confidence, backtested vs. sold prices. |
| MLS / agent comps | **DON'T** | They win via MLS expired-listing data (though even they don't expose a full comp-set tool). We have no MLS comps; SC recorded-$/sqft comps are paywalled for us. |
| **OUTREACH / MARKETING EXECUTION** | | |
| Predictive / parallel dialer | **DON'T** | They win completely. Full dialer w/ TCPA controls, ringless VM, recording. We have **no dialer**. |
| Bulk SMS (prewarmed DIDs, compliant) | **DON'T** | They win completely. We have **no SMS**. |
| Bulk email (warming, CAN-SPAM) | **DON'T** | They win completely. We have **no email send**. |
| Direct mail (no minimums, QR tracking) | **DON'T** | They win completely. We output an `outreach_maillist.csv` — a list to hand to a mail house — but no integrated print/mail execution or tracking. |
| Paid ads (Meta custom-audience export) | **DON'T** | They win completely. We have no ad-audience builder. |
| Landing pages / web intake + consent log | **DON'T** | They win completely. We have a read-only dashboard, no lead-capture pages. |
| Automated drip campaigns | **DON'T** | They win completely. No campaign automation on our side. |
| **AI AGENT (David)** | | |
| 24/7 AI inbound call handling | **DON'T** | They win completely. No voice AI on our side. |
| AI multi-channel outbound + qualification | **DON'T** | They win completely. |
| AI books appointments to calendar | **DON'T** | They win completely. |
| **CRM / PIPELINE (Command Center)** | | |
| Full CRM w/ pipeline + deal stages | **DON'T** | They win completely. We have **no CRM** — a dashboard + CSV, not contact/deal management. |
| Unified inbox (call/text/email one thread) | **DON'T** | They win completely (we have no outreach channels to unify). |
| Workflow automation (if-this-then-that) | **DON'T** | They win completely. |
| AI co-pilot (flags stalls, next moves) | **DON'T** | They win completely. |
| Contract gen + phone e-sign + tracking | **DON'T** | They win completely. |
| **TEAM / COLLABORATION** | | |
| Teams, roles, permissions, seats | **DON'T** | They win. Ours is single-analyst; no multi-seat/roles. |
| Analytics & reporting (CPA, velocity, ROI) | **DON'T** | They win. We have no funnel/ROI reporting layer. |
| Lead routing (territory/round-robin) | **DON'T** | They win. Nothing to route without a CRM. |
| **MOBILE / DRIVING-FOR-DOLLARS** | | |
| Mobile app | **DON'T (tie — theirs unshipped)** | Neither ships one. Theirs is "Coming Soon"; ours is web-only. No advantage to either today. |
| Driving-for-dollars route/photo capture | **DON'T (tie)** | Neither has it. Not a live differentiator. |
| **INTEGRATIONS** | | |
| Google / Meta / CallTools / ReadyMode | **DON'T** | They win. We have no third-party CRM/dialer/ad integrations. |
| Webhooks + REST API | **DON'T (tie — theirs is a stub)** | Advertised by them but help docs are empty; not proven shipped. We expose CSV + JSON files, no API. Rough wash today. |
| **ECOSYSTEM / PROGRAMS** | | |
| Blackbook (done-for-you appointments) | **DON'T** | They win — it's a managed service, not software. Out of scope for us. |
| Syndicate (off-market deal marketplace) | **DON'T** | They win on concept; unproven. Not something we offer. |
| **PRICE / ACCESS** | | |
| Cost to the end user | **HAVE (we win)** | **We beat them hard.** We're **free**; they're $299–$2,999/mo, non-refundable, 30-day cancel notice on Scale. |
| Court-confirmed corroboration flag | **HAVE (we win)** | **We beat them.** We flag court-confirmed vs. single-source. Nothing on their site claims source-corroboration transparency; the founder admits it's speed-of-scrape, not verified accuracy. |
| Footprint depth (source breadth per county) | **HAVE (we win)** | **We beat them in-footprint.** 110 scrapers × distress-signal breadth (jail bookings, SC DOR liens, obituary heirs, tax-relief, STR/vacant, partition) is deeper per-county than a nationwide aggregator's uniform layer. |

**Net tally:** Goliath clearly beats us on **skip-trace at scale, nationwide coverage, dialer/SMS/email/direct-mail execution, the CRM, MLS/expired data, life-event signals, list stacking, and team features**. We clearly beat them on **price (free), ARV/underwriting math, court-confirmed corroboration, and per-county source depth in our footprint**.

---

## 4. What Real Users Say

**Headline finding: independent reviews barely exist.** Across Reddit, BiggerPockets, Trustpilot, G2, Capterra, Software Advice, SoftwareWorld, BBB, and YouTube, there is **almost no genuine third-party review of Goliath Data**. Search results are saturated by Goliath's own comparison/SEO content and recycled testimonials. Strip those out and authentic external discussion is near zero as of mid-2026. For an 11,000-user, VC-backed, paid-monthly tool, that absence is itself the loudest signal.

- **G2:** profile exists, **no user reviews** ([g2.com](https://www.g2.com/products/goliathdata/competitors/alternatives)).
- **Capterra:** "**0.0 (Based on 0 user reviews)**" ([capterra.com](https://www.capterra.com/p/10035457/Goliath/)).
- **Software Advice:** "**No Reviews Yet**" ([softwareadvice.com](https://www.softwareadvice.com/product/536319-Goliath/)).
- **Trustpilot:** no Goliath *Data* page. (The 2.6/5 "Goliath Ventures Inc." crypto-scam page is an **unrelated company** — do not conflate. [trustpilot.com](https://www.trustpilot.com/review/goliathventuresinc.com))
- **BBB:** no profile for the software company ("Goliath Properties LLC" / "Goliath Property Solutions" are unrelated).
- **Reddit:** `site:reddit.com "Goliath Data"` returned **no results**; no thread in r/realestateinvesting, r/wholesaling, r/FlippingHouses, r/realtors.
- **YouTube:** no independent "honest review / is it worth it" video for Goliath Data specifically.

### Praise — all first-party marketing (flagged as such)
Every positive quote traces back to Goliath's own site/testimonial wall — treat as marketing, not verified sentiment:
- "Amazing leads to solid prospects. **The hit rate has blown away my traditional cold calling!**"
- "I went from chasing dead-end leads to having **vetted listing appointments on my calendar every week.**"
- "The homeowners **actually expect my call**, and they're ready to have a real conversation about selling."
- Case study "Josh Wagner" (NC agent): "**from a few transactions per month to 3–6 per month.**"
- 9-person testimonial wall (Amber Fletcher/New Orleans, Chris Wallace/Charleston SC, Lauren Diaz/Charlotte NC, Marcus Bennett/Nashville, etc.), header "close 3x more deals in half the time." No independent corroboration of any of it.

### Complaints / risk flags — structural, not crowd-sourced
Because there's no review corpus, the criticism is category-level, from credible independent voices:

1. **The one substantive independent thread** — BiggerPockets, "AI for lead generation" ([thread](https://www.biggerpockets.com/forums/93/topics/1161134-ai-for-lead-generation), Dec 2023–Jan 2024). OP **Joe Homs**: *"every time I google the company the reviews are not great."* Founder **Max Yuan** posted the clearest first-party "how it works" statement (quoted in §5). Rebuttal from **Jerryll Noorden** (ex-NASA, active BP contributor) attacks the whole premise:
   > "YOU CAN NOT TARGET MOTIVATED SELLERS no matter what gadget you use… this is just DATA."
   > "3000 mailers to these lists to get one deal (if lucky). That is a **0.033% success rate**… 99.96% of the people you are targeting through lists, AI, however, are not motivated."
   > "What AI CAN do however is **automate this horribly poor inefficient method**… an automated way to lose money faster with a chance to get lucky."
   This is a structural critique of the "AI finds motivated sellers" category Goliath is built on — the most-upvoted substantive reply in the only real thread that exists.

2. **No-refund policy** — Terms state all fees are "non-refundable… all payments are final," and Scale plans require 30 days' written cancellation notice. Real buyer-beware given the thin track record ([Terms](https://goliathdata.com/terms-of-service)).

3. **Thin reputation** — zero verified reviews on any neutral platform is a due-diligence red flag for a paid tool.

4. **Data-moat question** — by the founder's own account it monitors "the same data sources you do today"; the value is speed/automation, not unique data. If speed isn't your bottleneck, the edge shrinks.

5. **Absence in "go-to stack" threads** — when BP investors name their actual tools ([thread](https://www.biggerpockets.com/forums/109/topics/1205572-best-lead-generation-tools-for-real-estate-investors-what-s-your-go-to)), they cite BatchLeads, REISift, DataFlik, 8020REI, Followup Boss, DirectSkip, Smarter Contact, Readymode — **Goliath does not come up organically.** That silence is a data point.

### Data-accuracy reality
No specific verified complaints about wrong phone numbers, bad match rates, or billing disputes were found — **but only because there is no review base**, not because sentiment is clean. Skip-trace accuracy claims (85–92%) are industry benchmarks Goliath cites in blog SEO, not a Goliath SLA. The founder's own framing (win on extraction speed, not a proprietary/verified dataset) means data accuracy is inherited from underlying vendors, undisclosed.

### Price gripes
No user-level price complaints exist (no user base to voice them). The structural price flags are: tier-price inconsistency across their own pages ($99/$249 blog anchors vs. $299/$899/$2,999 live), non-refundable billing, and Scale's 30-day-notice lock-in.

---

## 5. How They Do It (Reverse-Engineered)

**Pattern: data aggregator + skip-trace reseller wrapped in an AI-CRM.** The moat they *claim* is speed (hourly public-notice ingestion → "28-day advantage") and the David voice agent — **not proprietary data**.

### Data sources — *what's confirmed vs. speculated*
- **Confirmed (stated on-site):** county recorder records, court filings (NOD/Lis Pendens, probate, liens, evictions, code violations), county assessor data (equity/characteristics), MLS across 50 states (expired listings), consumer life-event signals (tax delinquency, marriage licenses, job changes, pregnancy), and a native skip-trace/contact append.
- **Confirmed by the founder (BiggerPockets):** Max Yuan, verbatim — *"[a tool that] monitors the same data sources as you do today, but use the newest techniques in engineering to automatically extract names, addresses and cross reference that information with county databases before streaming that information to your CRM. Likely finishing the process before anyone else has the chance to even see the original data source, giving you the first mover advantage."* → i.e., **scraping/monitoring the same public county sources everyone uses**, winning on extraction speed + enrichment, not a unique dataset.
- **Speculated (industry-pattern inference):** the assessor/recorder substrate is almost certainly **licensed bulk data of the ATTOM / CoreLogic / Black Knight / First American class**, fused with self-scraped court/public-notice feeds and a bundled skip-trace append. **No data vendor is named anywhere on-site** (no ATTOM/CoreLogic/DataTree/TLO/IDI logos) — deliberate white-labeling, normal for resellers, keeps switching costs opaque. The skip-trace vendor behind the append is likewise undisclosed.

### Coverage & refresh
- **Coverage:** nationwide/50-state claimed; "150+ markets" the more conservative real number.
- **Refresh:** hourly pipeline; signals "within the hour" of filing; MLS "daily." The "28-day advantage" and AI-ranked daily call list are the productized outputs.

### Tech stack — *hard signals from headers/HTML (confirmed)*
- **Marketing site:** **Framer** (`<meta name="generator" content="Framer">`, ~13.7k Framer refs), behind **Cloudflare** (SSG, cached, us-east-1). Not WordPress/Webflow/Next.
- **App (`realty.goliathdata.com`):** served by **Google Frontend** → runs on **Google Cloud** (App Engine / Cloud Run / Firebase-class), separate from the marketing layer.
- **Billing/affiliate:** **Rewardful** (`r.wdfl.co/rw.js`) → implies **Stripe** billing + confirms the affiliate program. **LiveChat** for support.
- **David (voice agent):** underlying LLM + voice + telephony provider **not disclosed** (no Twilio/Vapi/Retell/Bland fingerprint on marketing pages) — typical wrapper on a third-party voice-AI + telephony stack (*speculated*).
- **No shipped public API/mobile app** — help docs (webhooks/REST/skip-trace/billing) are **empty stubs**; "no exports" is marketed as a feature. Named integrations: Google, Facebook, CallTools, ReadyMode.

### What this implies
Thin funding (~$1.65M) + Framer marketing + Google-Cloud app + Stripe/Rewardful billing = a **lean, early-stage build**. The real defensibility question is whether their court/public-notice scraping breadth and David's conversion actually beat a PropStream + BatchSkipTrace + CallTools DIY stack at $299–$2,999. By their own admission, the data isn't the moat — speed and the AI agent are.

---

## 6. The Honest Verdict

### Where Goliath genuinely beats us — and why
1. **Skip tracing at scale (phone + email).** Their single biggest practical edge. 2,500–10,000 DNC-scrubbed verified phones+emails/mo bundled into the price. We have mailing address + NC-only voter phone (~69%). To *call or text* an owner tomorrow, Goliath is ready and we are not. Why: they pay a PII/skip-trace vendor; we deliberately don't.
2. **Nationwide coverage.** 50 states / 150+ markets vs. our 18 counties. Structural — we chose depth over breadth.
3. **Outreach execution (dialer + SMS + email + direct mail + ads + landing pages).** They *act* on leads; we *produce* leads. This is a whole category we don't touch.
4. **A real CRM + AI agent (David).** Pipeline, unified inbox, automation, appointment-booking voice AI. We have a dashboard, not a system of record.
5. **MLS/expired + consumer life-event signals + list stacking.** Data classes we can't reach for free (MLS, life-events) or haven't productized (stacking).

The honest caveat on all of it: by the founder's own admission the **data isn't a moat** (same public sources, faster), the **glowing testimonials are first-party**, there are **zero independent reviews**, and the loudest external voice ([Noorden](https://www.biggerpockets.com/forums/93/topics/1161134-ai-for-lead-generation)) argues the entire "AI targets motivated sellers" premise converts at ~0.033%. They beat us on *capability breadth*; whether that breadth converts is unproven publicly.

### Where we actually match or beat them
1. **Free vs. $299–$2,999/mo, non-refundable.** For our footprint, we deliver the core distress-lead data at zero cost. That is a decisive advantage for a footprint-focused operator.
2. **Court-confirmed corroboration.** We flag court-confirmed vs. single-source. Goliath's own founder frames the product as speed-of-scrape, with Terms disclaiming any accuracy guarantee. We're more honest about signal quality.
3. **Footprint depth / distress-signal breadth.** 110 scrapers per-county (jail bookings, SC DOR liens, obituary-driven pre-probate heirs, tax-relief, STR/vacant, partition/eviction, ROD deed/lien) is *deeper per county* than a uniform nationwide layer. In our 18 counties we likely see distress signals Goliath's generic pipeline misses.
4. **Underwriting math.** We ship ARV + rehab + max-bid + equity + A–F grade, backtested vs. sold prices. Goliath has **no** ARV/MAO engine — it scores *lead intent*, not *deal economics*. An investor still has to underwrite Goliath's leads elsewhere; ours come pre-underwritten.

**Bottom line:** Goliath is a broad, shallow, expensive *action platform*; we are a narrow, deep, free *intelligence engine*. They win the "one tool to run my whole acquisitions business anywhere" buyer. We win the "give me the best free distress data in my backyard, already underwritten" operator.

### 5–8 highest-value features to close the gap (tagged)

1. **Skip-trace / phone-append integration — BUILD-able free (partial) → needs-paid-vendor (at scale).** Biggest ROI. First expand what's free: extend the NC voter-file phone match, add SC voter file where lawful, and layer free reverse-lookup enrichers we already have (SoS agent enricher, doc-OCR contact backfill). Then optionally add a *pay-per-hit* skip-trace pass (BatchData/IDI/TLO-class) as an opt-in enrichment so we stay free by default. Closes their #1 advantage most of the way for our footprint.
2. **List-stacking / multi-signal ranking UI — BUILD-able free.** We already produce every signal keyed to a property/owner. Add a stacking view that ranks owners by *how many distress lists they hit* (tax-delinquent + probate + code-violation + vacant, etc.). Pure UI/data-join work on data we own. High perceived value, zero new data cost.
3. **A normalized 0–100 Seller-Intent Score + filter — BUILD-able free.** We have distress scoring + A–F grade; repackage as a single tunable intent number with a slider filter (matching their headline feature) so the dashboard reads like an intent engine, not a raw export.
4. **Direct-mail export → integrated mail send — BUILD-able free (export) / needs-paid-vendor (fulfillment).** We already emit `outreach_maillist.csv`. Add one-click hooks to a print-and-mail API (Lob/PostGrid-class, pay-per-piece) with QR-coded response tracking. Keeps the tool free; mail cost is the user's, like Goliath's model.
5. **Basic outreach/CRM lite (status + notes + follow-up) — BUILD-able free.** Not a full Command Center — just per-lead status (new/contacted/appointment/dead), notes, and next-action date on the existing dashboard. Turns a static list into a workable pipeline and removes the "it's just a CSV" objection cheaply.
6. **Continuous / near-real-time refresh cadence — BUILD-able free.** Move from batch runs toward more frequent scheduled ingest on the high-value court/foreclosure feeds so we can claim first-mover speed in-footprint (fixing the full-run hang caveat is a prerequisite). Directly answers their "28-day advantage" pitch.
7. **Lien-position + equity-% as clean per-lead fields — BUILD-able free.** We have ROD deed/lien + assessor data; surface lien position + a computed equity-% column so leads match their filter UX without new data.
8. **SMS/voice outreach — not-worth-it (for now).** Building compliant DID provisioning, TCPA/DNC infrastructure, and an AI voice agent is a large, regulated, expensive lift far outside a free public-records engine's mission. Skip unless the product pivots from *intelligence* to *execution*. Better to integrate with an existing dialer than to become one.

---

*Sources cited inline throughout. Primary: [goliathdata.com](https://goliathdata.com/) (home, /platform, /pricing, /product/*, /solutions/*, /client/*, /campaigns/*, /terms-of-service, /privacy-policy), [BiggerPockets thread 1161134](https://www.biggerpockets.com/forums/93/topics/1161134-ai-for-lead-generation) and [1205572](https://www.biggerpockets.com/forums/109/topics/1205572-best-lead-generation-tools-for-real-estate-investors-what-s-your-go-to), [Crunchbase](https://www.crunchbase.com/organization/goliathdata), [f4.fund](https://f4.fund/startups/goliathdata), [CB Insights](https://www.cbinsights.com/company/goliath-data/people), [Capterra](https://www.capterra.com/p/10035457/Goliath/), [Software Advice](https://www.softwareadvice.com/product/536319-Goliath/), [G2](https://www.g2.com/products/goliathdata/competitors/alternatives). Do not conflate with the unrelated "[Goliath Ventures Inc.](https://www.trustpilot.com/review/goliathventuresinc.com)" crypto entity.*
