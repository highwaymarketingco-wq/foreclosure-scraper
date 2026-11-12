# Free Skip Tracing and Contact Data - What's Available

## FREE and COMPLIANT (already wired or available)

### 1. Owner Name + Mailing Address (ALREADY HAVE - 89.9% of board)
- Source: County GIS / tax records
- Free, public, already scraped
- This is the TCPA-free mail spine

### 2. NC Voter File Phone Numbers (ALREADY WIRED)
- Source: NC State Board of Elections voter file
- Free, licensed for this use, ~69% NC coverage
- File: `enrichment_voter_phone.py`
- SC has NO equivalent (SC voter list is paid + purpose-restricted + has no phone)

### 3. MERS ServicerID (FREE, not yet wired)
- Source: mers-servicerid.org
- Free, public, no key
- Returns: current loan SERVICER NAME only (no balance, no phone)
- Use case: confirm a live loan exists before a subject-to conversation
- This is a `creative_fit` enricher, not a skip tracer

### 4. NC SoS Registered Agent (ALREADY WIRED for NC)
- Source: `enrichment_sos_agent.py`
- Free via stealth for NC SoS
- SC SoS is captcha-walled (manual only)
- Returns: registered agent + officers for LLC/entity-owned properties

### 5. Manual Google Search (FREE, human-only)
- A human can Google "John Doe 123 Main St Asheville NC phone" in their own browser
- This is NOT scraping, NOT automated, NOT a ToS violation
- May find: phone numbers, email addresses, social media profiles
- The engine can generate a list of "search queries to run" for the operator
- The operator does the searches manually and enters results

## NOT FREE or NOT COMPLIANT

### People-Search Sites (WONT wall)
- TruePeopleSearch, FastPeopleSearch, Spokeo, Radaris, Whitepages
- OFF LIMITS per compliance constitution Rule 3
- Even manual use is against the blueprint's intent ("phones are BOUGHT per hit, never scraped")
- These sites return Cloudflare 403/paywall teasers to automation and BAN automation in ToS

### Emails
- No free compliant email source exists
- Email append services are paid (per-hit pricing)
- Direct mail is the spine (no email needed for TCPA-free outreach)

### SC Phone Numbers
- SC voter file is paid + purpose-restricted + has no phone
- No free SC phone route exists
- SC phones must be bought per-hit from compliant vendor (Tracerfy ~$0.02, PropWire $0.10)

## RECOMMENDED FREE OUTREACH STACK

1. Direct mail to owner mailing address (TCPA-free, no restrictions)
   - Yellow Letter HQ, Ballpoint, Open Letter, Lob API, USPS EDDM
   - Owner name + mailing address already on the board at 89.9%

2. NC voter file phone match (free, already wired)
   - Run "voter file" command, engine matches ~69% of NC leads
   - DNC scrub required before any call/text

3. Manual Google search batch (free, human does it)
   - Engine generates a list of top leads with "search this name + address"
   - Operator does manual searches and enters phone/email found
   - Not automated, not scraping, fully compliant

4. Bought phones for the rest (per-hit, DNC-scrubbed)
   - Tracerfy ~$0.02/match or PropWire $0.10/match
   - Only for leads where free routes failed
   - DNC scrub every 31 days before any call
