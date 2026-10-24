# Hermes hand-off -- the walled bucket, triaged

Generated from `gap_list_2026-10-24.csv`. Regenerate with `python scripts/hermes_handoff.py` any time the gap list changes -- this file is a derived view, not hand-maintained.

Only **Hermes lane** (CAPTCHA or a required login) actually goes to Hermes. **Bot-wall, build in-house** is ordinary scraper work for this project (existing WAF-bypass/stealth-browser code, applied per-site) -- not a Hermes hand-off. The last two piles need a human policy call or a scheduled recheck, not a scraper at all -- see this script's own module docstring for why.

## 1. Hermes lane -- CAPTCHA or required login

641 cells, 918,202 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| NC | Mecklenburg | usps_vacancy | 39,861 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Gaston | usps_vacancy | 26,645 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Spartanburg | usps_vacancy | 19,381 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Lincoln | heir_naming_publication | 18,841 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Lincoln | multi_year_delinquent_tax | 18,841 | CAPTCHA | tax/property card: www.lincolncountytax.com |
| NC | Lincoln | quiet_title | 18,841 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Lincoln | rollback_exposure | 18,841 | CAPTCHA | tax/property card: www.lincolncountytax.com |
| NC | Lincoln | usps_vacancy | 18,841 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wake | atty_rod_lien_checked | 12,942 | CAPTCHA | register: Tyler Technologies Self-Service (recorder search,  |
| NC | Wake | liens | 12,942 | CAPTCHA | register: Tyler Technologies Self-Service (recorder search,  |
| NC | Wake | usps_vacancy | 12,942 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Transylvania | usps_vacancy | 12,528 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Buncombe | usps_vacancy | 12,446 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Guilford | usps_vacancy | 12,276 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Charleston | atty_rod_lien_checked | 11,212 | CAPTCHA | register: Charleston County ROD document search (county-buil |
| SC | Charleston | liens | 11,212 | CAPTCHA | register: Charleston County ROD document search (county-buil |
| SC | Charleston | usps_vacancy | 11,212 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Rutherford | usps_vacancy | 11,206 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Forsyth | usps_vacancy | 10,688 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Brunswick | heir_naming_publication | 9,225 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Brunswick | liens | 9,225 | CAPTCHA | register: Internet Technologies Inc. (Inttek) 'Recording-Pro |
| NC | Brunswick | quiet_title | 9,225 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Brunswick | usps_vacancy | 9,225 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Catawba | usps_vacancy | 8,291 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Horry | usps_vacancy | 6,691 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Randolph | atty_rod_lien_checked | 6,043 | CAPTCHA | register: Courthouse Computer Systems (CCS) public web searc |
| NC | Randolph | liens | 6,043 | CAPTCHA | register: Courthouse Computer Systems (CCS) public web searc |
| NC | Randolph | usps_vacancy | 6,043 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Durham | usps_vacancy | 5,966 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | New Hanover | usps_vacancy | 5,924 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Pickens | usps_vacancy | 5,795 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Sumter | usps_vacancy | 5,613 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Greenville | usps_vacancy | 5,547 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Davidson | usps_vacancy | 5,468 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Cumberland | usps_vacancy | 5,268 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Pitt | usps_vacancy | 5,183 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Spartanburg | sos_dissolution | 5,136 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Onslow | usps_vacancy | 4,836 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Rowan | usps_vacancy | 4,594 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Orangeburg | atty_deed_ref | 4,586 | login | register index: www.orangeburgscrod.org |
| SC | Orangeburg | atty_rod_lien_checked | 4,586 | login | register: County-run 'Register Of Deeds Remote Access Site'  |
| SC | Orangeburg | liens | 4,586 | login | register: County-run 'Register Of Deeds Remote Access Site'  |
| SC | Orangeburg | usps_vacancy | 4,586 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Beaufort | usps_vacancy | 4,281 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Harnett | atty_rod_lien_checked | 4,226 | CAPTCHA | register: Courthouse Computer Systems LRSearch (MVC) at us6  |
| NC | Harnett | heir_naming_publication | 4,226 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Harnett | liens | 4,226 | CAPTCHA | register: Courthouse Computer Systems LRSearch (MVC) at us6  |
| NC | Harnett | quiet_title | 4,226 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Harnett | usps_vacancy | 4,226 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Henderson | usps_vacancy | 3,976 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Duplin | usps_vacancy | 3,956 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Lee | usps_vacancy | 3,907 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Oconee | usps_vacancy | 3,888 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Florence | usps_vacancy | 3,883 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Charleston | sos_dissolution | 3,846 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| SC | Colleton | usps_vacancy | 3,680 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Duplin | probate | 3,678 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Beaufort | probate | 3,657 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Berkeley | usps_vacancy | 3,641 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Laurens | usps_vacancy | 3,611 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | McDowell | multi_year_delinquent_tax | 3,526 | CAPTCHA | tax/property card: www.bttaxpayerportal.com |
| NC | McDowell | rollback_exposure | 3,526 | CAPTCHA | tax/property card: www.bttaxpayerportal.com |
| NC | McDowell | usps_vacancy | 3,526 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Johnston | usps_vacancy | 3,485 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hoke | heir_naming_publication | 3,466 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hoke | quiet_title | 3,466 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hoke | usps_vacancy | 3,466 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Anderson | multi_year_delinquent_tax | 3,388 | login | tax/property card: acpass.andersoncountysc.org |
| SC | Anderson | usps_vacancy | 3,388 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Cherokee | usps_vacancy | 3,325 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Lexington | atty_rod_lien_checked | 3,303 | login | register: Kofile/GovOS CountyFusion countyfusion14.govos.com |
| SC | Lexington | liens | 3,303 | login | register: Kofile/GovOS CountyFusion countyfusion14.govos.com |
| SC | Lexington | usps_vacancy | 3,303 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Union | usps_vacancy | 3,163 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hyde | heir_naming_publication | 3,148 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hyde | quiet_title | 3,148 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hyde | usps_vacancy | 3,148 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Orange | heir_naming_publication | 3,046 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Orange | quiet_title | 3,046 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Orange | usps_vacancy | 3,046 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Williamsburg | atty_deed_ref | 2,956 | login | register index: williamsburgsc.avenuinsights.com |
| SC | Williamsburg | atty_rod_lien_checked | 2,956 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Williamsburg | liens | 2,956 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Williamsburg | usps_vacancy | 2,956 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hoke | probate | 2,940 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Darlington | atty_rod_lien_checked | 2,927 | login | register: Cott Systems RECORDhub recordhub.cottsystems.com |
| SC | Darlington | liens | 2,927 | login | register: Cott Systems RECORDhub recordhub.cottsystems.com |
| SC | Darlington | usps_vacancy | 2,927 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Cabarrus | usps_vacancy | 2,920 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Alamance | usps_vacancy | 2,858 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Iredell | atty_rod_lien_checked | 2,840 | CAPTCHA | register: Courthouse Computer Systems LRSearch (new, since 2 |
| NC | Iredell | liens | 2,840 | CAPTCHA | register: Courthouse Computer Systems LRSearch (new, since 2 |
| NC | Iredell | usps_vacancy | 2,840 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Anson | usps_vacancy | 2,580 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Pasquotank | usps_vacancy | 2,469 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | McDowell | atty_tax_verified_confirmed | 2,468 | CAPTCHA | tax/property card: www.bttaxpayerportal.com |
| SC | Lexington | probate | 2,417 | CAPTCHA | probate: www.lex-co.com |
| NC | Hyde | probate | 2,396 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Polk | usps_vacancy | 2,389 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Orange | probate | 2,281 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Harnett | probate | 2,244 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Rockingham | usps_vacancy | 2,241 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Richland | usps_vacancy | 2,236 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Bertie | multi_year_delinquent_tax | 2,173 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | rollback_exposure | 2,173 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | two_year_delinquent | 2,173 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | usps_vacancy | 2,173 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Washington | usps_vacancy | 2,167 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Nash | usps_vacancy | 2,090 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Dorchester | usps_vacancy | 2,080 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Kershaw | atty_deed_ref | 2,064 | login | register index: kershawsc.avenuinsights.com |
| SC | Kershaw | atty_rod_lien_checked | 2,064 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Kershaw | liens | 2,064 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Kershaw | usps_vacancy | 2,064 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Barnwell | usps_vacancy | 2,059 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Lincoln | atty_tax_verified_confirmed | 2,031 | CAPTCHA | tax/property card: www.lincolncountytax.com |
| NC | Burke | multi_year_delinquent_tax | 2,019 | CAPTCHA | tax/property card: lrcpwa.ncptscloud.com |
| NC | Burke | usps_vacancy | 2,019 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Horry | sos_dissolution | 1,995 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Granville | usps_vacancy | 1,944 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Perquimans | usps_vacancy | 1,882 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | York | usps_vacancy | 1,818 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wayne | usps_vacancy | 1,793 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Beaufort | liens | 1,744 | CAPTCHA | register: NewVision Systems BrowserView (rod.beaufortcountys |
| SC | Beaufort | usps_vacancy | 1,744 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Madison | usps_vacancy | 1,704 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Clarendon | usps_vacancy | 1,669 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Jasper | atty_rod_lien_checked | 1,669 | CAPTCHA | register: Courthouse Computer Systems (CCHS) Registrar us6.c |
| SC | Jasper | usps_vacancy | 1,669 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Union | probate | 1,632 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Craven | liens | 1,608 | CAPTCHA | register: Courthouse Computer Systems LRSearch (us5.courthou |
| NC | Craven | usps_vacancy | 1,608 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Cleveland | multi_year_delinquent_tax | 1,602 | CAPTCHA | tax/property card: www.clevelandcountytaxes.com |
| NC | Cleveland | rollback_exposure | 1,602 | CAPTCHA | tax/property card: www.clevelandcountytaxes.com |
| NC | Cleveland | usps_vacancy | 1,602 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Robeson | usps_vacancy | 1,582 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Greenville | sos_dissolution | 1,570 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Bertie | atty_tax_verified_confirmed | 1,562 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Moore | usps_vacancy | 1,557 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Chatham | usps_vacancy | 1,553 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Pender | heir_naming_publication | 1,543 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Pender | quiet_title | 1,543 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Pender | usps_vacancy | 1,543 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Bertie | tax_aging_surfaced | 1,535 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | lt_tax_lien | 1,534 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| SC | Dillon | usps_vacancy | 1,520 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Union | usps_vacancy | 1,496 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Marlboro | usps_vacancy | 1,481 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Person | heir_naming_publication | 1,429 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Person | quiet_title | 1,429 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Person | usps_vacancy | 1,429 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wilson | usps_vacancy | 1,389 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Gaston | atty_heir_candidates | 1,381 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Perquimans | probate | 1,380 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Franklin | usps_vacancy | 1,369 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Bertie | probate | 1,365 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Stanly | usps_vacancy | 1,343 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Madison | probate | 1,326 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Washington | probate | 1,313 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Caswell | usps_vacancy | 1,273 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Haywood | usps_vacancy | 1,249 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Lancaster | usps_vacancy | 1,246 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Surry | heir_naming_publication | 1,218 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Surry | quiet_title | 1,218 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Surry | usps_vacancy | 1,218 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Forsyth | atty_heir_candidates | 1,189 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Jones | heir_naming_publication | 1,177 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jones | quiet_title | 1,177 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jones | usps_vacancy | 1,177 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Granville | probate | 1,170 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Chowan | usps_vacancy | 1,166 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Calhoun | usps_vacancy | 1,142 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Newberry | atty_deed_ref | 1,142 | login | register index: newberrysc.avenuinsights.com |
| SC | Newberry | atty_rod_lien_checked | 1,142 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Newberry | usps_vacancy | 1,142 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Carteret | heir_naming_publication | 1,108 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Carteret | quiet_title | 1,108 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Carteret | usps_vacancy | 1,108 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Rutherford | atty_heir_candidates | 1,097 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Edgefield | usps_vacancy | 1,076 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wayne | probate | 1,074 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Greenwood | usps_vacancy | 1,070 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Caldwell | multi_year_delinquent_tax | 1,054 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | repeat_tax_loss | 1,054 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | tax_aging_surfaced | 1,054 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | two_year_delinquent | 1,054 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | usps_vacancy | 1,054 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Edgecombe | heir_naming_publication | 1,051 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Edgecombe | quiet_title | 1,051 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Edgecombe | usps_vacancy | 1,051 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Chesterfield | usps_vacancy | 1,034 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Georgetown | multi_year_delinquent_tax | 997 | CAPTCHA | tax/property card: georgetowncountysctax.com |
| SC | Georgetown | rollback_exposure | 997 | CAPTCHA | tax/property card: georgetowncountysctax.com |
| SC | Georgetown | tax_aging_surfaced | 997 | CAPTCHA | tax/property card: georgetowncountysctax.com |
| SC | Georgetown | usps_vacancy | 997 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Moore | probate | 991 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Pickens | sos_dissolution | 971 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Jackson | heir_naming_publication | 967 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jackson | quiet_title | 967 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jackson | usps_vacancy | 967 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |

...and 441 more rows in this pile (full set in the source gap_list CSV, filtered to this reason pattern).

## 2. Bot-wall, build in-house -- Cloudflare/WAF, not Hermes

191 cells, 212,970 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | Charleston | rollback_exposure | 11,212 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| NC | Rutherford | multi_year_delinquent_tax | 11,206 | bot check (Cloudflare/WAF) | tax/property card: rutherfordcountync.gov |
| SC | Charleston | atty_tax_verified_confirmed | 7,518 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Sumter | probate | 4,686 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Rowan | atty_rod_lien_checked | 4,594 | bot check (Cloudflare/WAF) | register: rod.rowancountync.gov (atty_rod_lien_checked: bloc |
| NC | Rowan | liens | 4,594 | bot check (Cloudflare/WAF) | register: rod.rowancountync.gov (liens: blocked) |
| SC | Charleston | lt_tax_sale | 4,156 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| NC | Lee | multi_year_delinquent_tax | 3,907 | bot check (Cloudflare/WAF) | tax/property card: taxaccess.leecountync.gov |
| NC | Lee | rollback_exposure | 3,907 | bot check (Cloudflare/WAF) | tax/property card: taxaccess.leecountync.gov |
| NC | Lee | two_year_delinquent | 3,907 | bot check (Cloudflare/WAF) | tax/property card: taxaccess.leecountync.gov |
| SC | Florence | assessed_value | 3,837 | Cloudflare check on the county property card | county GIS: services1.arcgis.com |
| NC | Union | multi_year_delinquent_tax | 3,163 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | repeat_tax_loss | 3,163 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | rollback_exposure | 3,163 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | tax_aging_surfaced | 3,163 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | two_year_delinquent | 3,163 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Lee | atty_tax_verified_confirmed | 3,076 | bot check (Cloudflare/WAF) | tax/property card: taxaccess.leecountync.gov |
| SC | Colleton | assessed_value | 2,563 | Cloudflare check on the county property card | county GIS: services1.arcgis.com |
| NC | Pasquotank | atty_rod_lien_checked | 2,469 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Pasquotank | liens | 2,469 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Polk | multi_year_delinquent_tax | 2,389 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Polk | rollback_exposure | 2,389 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Polk | tax_aging_surfaced | 2,389 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Rockingham | atty_rod_lien_checked | 2,241 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) 'e-Vault' us5.co |
| NC | Rockingham | liens | 2,241 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) 'e-Vault' us5.co |
| SC | Richland | multi_year_delinquent_tax | 2,236 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | rollback_exposure | 2,236 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | tax_aging_surfaced | 2,236 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | two_year_delinquent | 2,236 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Washington | atty_rod_lien_checked | 2,167 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Washington | liens | 2,167 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Colleton | atty_probate_case | 2,125 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Perquimans | atty_rod_lien_checked | 1,882 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Perquimans | liens | 1,882 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Colleton | atty_heir_candidates | 1,826 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | York | rollback_exposure | 1,818 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | Colleton | lt_estate_lead | 1,817 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Kershaw | probate | 1,802 | bot check (Cloudflare/WAF) | probate: www.kershaw.sc.gov |
| SC | Sumter | atty_probate_case | 1,793 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Polk | atty_tax_verified_confirmed | 1,756 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| SC | Barnwell | probate | 1,695 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Clarendon | atty_deed_ref | 1,669 | bot check (Cloudflare/WAF) | register index: acclaimprod.clarendoncountygov.org |
| SC | Clarendon | atty_rod_lien_checked | 1,669 | bot check (Cloudflare/WAF) | register: Harris AcclaimWeb acclaimprod.clarendoncountygov.o |
| SC | Clarendon | liens | 1,669 | bot check (Cloudflare/WAF) | register: Harris AcclaimWeb acclaimprod.clarendoncountygov.o |
| NC | Moore | atty_rod_lien_checked | 1,557 | bot check (Cloudflare/WAF) | register: Aumentum Recorder web access (Harris Recording Sol |
| NC | Moore | liens | 1,557 | bot check (Cloudflare/WAF) | register: Aumentum Recorder web access (Harris Recording Sol |
| NC | Chatham | multi_year_delinquent_tax | 1,553 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Chatham | repeat_tax_loss | 1,553 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Chatham | tax_aging_surfaced | 1,553 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Chatham | two_year_delinquent | 1,553 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Pender | atty_rod_lien_checked | 1,543 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Pender | liens | 1,543 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Clarendon | lot_size | 1,542 | Cloudflare check on the county property card | county GIS: qpublic.schneidercorp.com |
| NC | Union | atty_tax_verified_confirmed | 1,509 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Person | atty_rod_lien_checked | 1,429 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Person | liens | 1,429 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Wilson | multi_year_delinquent_tax | 1,389 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | repeat_tax_loss | 1,389 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | rollback_exposure | 1,389 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | tax_aging_surfaced | 1,389 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | two_year_delinquent | 1,389 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| SC | Clarendon | assessed_value | 1,383 | Cloudflare check on the county property card | county GIS: qpublic.schneidercorp.com |
| SC | Sumter | atty_heir_candidates | 1,347 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Sumter | lt_estate_lead | 1,339 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Florence | atty_heir_candidates | 1,308 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Florence | lt_estate_lead | 1,297 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | York | probate | 1,267 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Lancaster | assessed_value | 1,204 | Cloudflare check on the county property card | county GIS: services3.arcgis.com |
| SC | York | beds_baths | 1,128 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | Barnwell | atty_probate_case | 1,098 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Newberry | lot_size | 1,078 | Cloudflare check on the county property card | county GIS: map.newberrycounty.net |
| NC | Edgecombe | multi_year_delinquent_tax | 1,051 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Edgecombe | repeat_tax_loss | 1,051 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Edgecombe | tax_aging_surfaced | 1,051 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Edgecombe | two_year_delinquent | 1,051 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| SC | Edgefield | lot_size | 1,025 | Cloudflare check on the county property card | county GIS: qpublic.net |
| SC | Edgefield | assessed_value | 1,024 | Cloudflare check on the county property card | county GIS: qpublic.net |
| SC | Newberry | assessed_value | 981 | Cloudflare check on the county property card | county GIS: map.newberrycounty.net |
| SC | Lancaster | probate | 970 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Halifax | multi_year_delinquent_tax | 957 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | repeat_tax_loss | 957 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | rollback_exposure | 957 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | tax_aging_surfaced | 957 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | two_year_delinquent | 957 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| SC | York | atty_tax_verified_confirmed | 853 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | Barnwell | atty_heir_candidates | 833 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Barnwell | lt_estate_lead | 819 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Aiken | atty_rod_lien_checked | 805 | bot check (Cloudflare/WAF) | register:  www.aikencountysc.gov |
| SC | Aiken | liens | 805 | bot check (Cloudflare/WAF) | register:  www.aikencountysc.gov |
| NC | Ashe | multi_year_delinquent_tax | 794 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Ashe | repeat_tax_loss | 794 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Ashe | tax_aging_surfaced | 794 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Ashe | two_year_delinquent | 794 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| SC | Charleston | lt_tax_sale_overage | 727 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Berkeley | atty_heir_candidates | 723 | bot check (Cloudflare/WAF) | probate: berkeleycountysc.gov |
| SC | Berkeley | lt_estate_lead | 716 | bot check (Cloudflare/WAF) | probate: berkeleycountysc.gov |
| NC | Richmond | atty_rod_lien_checked | 682 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Richmond | liens | 682 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Chatham | atty_tax_verified_confirmed | 676 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Alleghany | atty_rod_lien_checked | 609 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCHS), new-style host |
| NC | Alleghany | liens | 609 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCHS), new-style host |
| SC | Lee | lot_size | 593 | Cloudflare check on the county property card | county GIS: qpublic.schneidercorp.com |
| SC | Lee | assessed_value | 574 | Cloudflare check on the county property card | county GIS: qpublic.schneidercorp.com |
| NC | Tyrrell | atty_rod_lien_checked | 537 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Tyrrell | liens | 537 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Aiken | probate | 520 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Charleston | atty_heir_candidates | 509 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Charleston | lt_probate_notice | 509 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Charleston | atty_probate_case | 417 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Dorchester | atty_heir_candidates | 364 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Avery | multi_year_delinquent_tax | 362 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | repeat_tax_loss | 362 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | rollback_exposure | 362 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | tax_aging_surfaced | 362 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | two_year_delinquent | 362 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Rockingham | divorce_no_subsequent_deed | 327 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) 'e-Vault' us5.co |
| NC | Tyrrell | marriage_license | 326 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Wilson | atty_tax_verified_confirmed | 268 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| SC | Dorchester | lt_estate_lead | 263 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Chester | probate | 214 | bot check (Cloudflare/WAF) | probate:  |
| SC | Fairfield | assessed_value | 199 | Cloudflare check on the county property card | county GIS: beacon.schneidercorp.com |
| SC | Fairfield | lot_size | 198 | Cloudflare check on the county property card | county GIS: beacon.schneidercorp.com |
| NC | Ashe | atty_tax_verified_confirmed | 179 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Gaston | divorce_no_subsequent_deed | 145 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems LRSearch (MVC/DevExpre |
| SC | Richland | lt_tax_sale_overage | 145 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Aiken | atty_heir_candidates | 139 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Aiken | lt_estate_lead | 139 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Avery | atty_tax_verified_confirmed | 128 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| SC | Spartanburg | lt_probate_notice | 111 | bot check (Cloudflare/WAF) | probate: www.spartanburgcounty.gov |
| SC | Lancaster | atty_probate_case | 110 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Spartanburg | atty_heir_candidates | 109 | bot check (Cloudflare/WAF) | probate: www.spartanburgcounty.gov |
| SC | Marlboro | atty_heir_candidates | 107 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Dorchester | atty_probate_case | 106 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Dorchester | lt_probate_notice | 106 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Colleton | lt_probate_notice | 102 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Edgecombe | atty_tax_verified_confirmed | 101 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Halifax | atty_tax_verified_confirmed | 85 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| SC | Georgetown | atty_heir_candidates | 84 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Georgetown | lt_estate_lead | 84 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Spartanburg | atty_probate_case | 79 | bot check (Cloudflare/WAF) | probate: www.spartanburgcounty.gov |
| SC | Spartanburg | probate | 75 | bot check (Cloudflare/WAF) | probate: www.spartanburgcounty.gov |
| SC | Kershaw | lt_estate_lead | 72 | bot check (Cloudflare/WAF) | probate: www.kershaw.sc.gov |
| SC | Oconee | atty_heir_candidates | 64 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Moore | divorce_no_subsequent_deed | 58 | bot check (Cloudflare/WAF) | register: Aumentum Recorder web access (Harris Recording Sol |
| SC | Kershaw | atty_heir_candidates | 56 | bot check (Cloudflare/WAF) | probate: www.kershaw.sc.gov |
| SC | Kershaw | atty_probate_case | 56 | bot check (Cloudflare/WAF) | probate: www.kershaw.sc.gov |
| SC | Chester | atty_probate_case | 54 | bot check (Cloudflare/WAF) | probate:  |
| SC | Marlboro | lt_estate_lead | 52 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Chester | atty_heir_candidates | 51 | bot check (Cloudflare/WAF) | probate:  |
| SC | Chester | lt_estate_lead | 51 | bot check (Cloudflare/WAF) | probate:  |
| SC | Marlboro | lt_probate_notice | 51 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | York | atty_heir_candidates | 50 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Marlboro | atty_probate_case | 48 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Pender | divorce_no_subsequent_deed | 37 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Richland | atty_tax_verified_confirmed | 35 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Lancaster | atty_heir_candidates | 32 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Lancaster | lt_estate_lead | 32 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Oconee | lt_probate_notice | 28 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Pasquotank | divorce_no_subsequent_deed | 20 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Berkeley | lt_probate_notice | 20 | bot check (Cloudflare/WAF) | probate: berkeleycountysc.gov |
| SC | York | atty_probate_case | 19 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | York | lt_probate_notice | 19 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Edgecombe | lt_tax_sale | 17 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Person | divorce_no_subsequent_deed | 15 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Florence | lt_probate_notice | 12 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Florence | atty_probate_case | 11 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Barnwell | lt_probate_notice | 10 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Charleston | probate | 8 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Perquimans | divorce_no_subsequent_deed | 5 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Chatham | lt_tax_sale | 4 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | lt_tax_sale | 4 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Tyrrell | divorce_no_subsequent_deed | 3 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Georgetown | lt_probate_notice | 3 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Berkeley | atty_probate_case | 2 | bot check (Cloudflare/WAF) | probate: berkeleycountysc.gov |
| NC | Washington | divorce_no_subsequent_deed | 1 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Aiken | atty_probate_case | 1 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Aiken | lt_probate_notice | 1 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Dorchester | probate | 1 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Georgetown | atty_probate_case | 1 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Oconee | atty_probate_case | 1 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| SC | Oconee | probate | 1 | bot check (Cloudflare/WAF) | probate: www.southcarolinaprobate.net |
| NC | Ashe | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Avery | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Chatham | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Edgecombe | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Halifax | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Lee | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: taxaccess.leecountync.gov |
| NC | Polk | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Rutherford | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: rutherfordcountync.gov |
| NC | Union | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Wilson | lt_tax_sale_overage | 0 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |

## 3. Human judgment call -- NOT a scrape target

268 cells, 192,016 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | Charleston | phone | 11,126 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Horry | phone | 6,616 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Sumter | phone | 5,552 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Greenville | phone | 5,380 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Sumter | divorce | 4,686 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Orangeburg | phone | 4,552 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Horry | divorce | 4,551 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Florence | atty_legal_description | 3,883 | only on the deed image | register: search.florencedeeds.com |
| SC | Oconee | phone | 3,851 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Florence | phone | 3,849 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Orangeburg | divorce | 3,848 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Colleton | phone | 3,667 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Laurens | phone | 3,533 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Berkeley | phone | 3,462 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Charleston | tax_aging_surfaced | 3,412 | verifier is a declared wall | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Anderson | phone | 3,333 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Cherokee | liens | 3,325 | terms forbid automation | register: Avenu Insights / Neumo Records Management (GRIDS), |
| SC | Cherokee | phone | 3,316 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Charleston | lt_tax_lien | 3,285 | verifier is a declared wall | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Lexington | phone | 3,262 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Florence | divorce | 3,150 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Williamsburg | phone | 2,949 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Darlington | phone | 2,910 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Berkeley | divorce | 2,688 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Darlington | divorce | 2,505 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Williamsburg | divorce | 2,453 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Lexington | divorce | 2,417 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Richland | atty_deed_ref | 2,236 | paywall | register index: www.richlandcountysc.gov |
| SC | Richland | atty_rod_lien_checked | 2,236 | paywall | register: Richland County 'Online Data Services' subscriptio |
| SC | Richland | liens | 2,236 | paywall | register: Richland County 'Online Data Services' subscriptio |
| SC | Richland | phone | 2,184 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Dorchester | atty_legal_description | 2,080 | only on the deed image | register: search.dorchesterdeeds.com |
| SC | Kershaw | phone | 2,054 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Barnwell | phone | 2,048 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Dorchester | phone | 2,048 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | McDowell | tax_aging_surfaced | 1,875 | verifier is a declared wall | tax/property card: www.bttaxpayerportal.com |
| SC | Kershaw | divorce | 1,802 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | York | phone | 1,790 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Dorchester | divorce | 1,716 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Beaufort | phone | 1,698 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Barnwell | divorce | 1,695 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Clarendon | phone | 1,663 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Jasper | phone | 1,663 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | Lincoln | tax_aging_surfaced | 1,609 | verifier is a declared wall | tax/property card: www.lincolncountytax.com |
| SC | Richland | divorce | 1,546 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Dillon | phone | 1,504 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Union | phone | 1,486 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Marlboro | phone | 1,471 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Jasper | divorce | 1,426 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Clarendon | divorce | 1,421 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Charleston | lt_lis_pendens | 1,406 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Dillon | divorce | 1,348 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Marlboro | divorce | 1,318 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | York | divorce | 1,267 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Lancaster | phone | 1,231 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Calhoun | atty_deed_ref | 1,142 | paywall | register index: www.titlesearcher.com |
| SC | Calhoun | atty_rod_lien_checked | 1,142 | paywall | register: TitleSearcher (paid subscription); Clerk of Court  |
| SC | Calhoun | liens | 1,142 | paywall | register: TitleSearcher (paid subscription); Clerk of Court  |
| SC | Calhoun | phone | 1,138 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Newberry | phone | 1,121 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Edgefield | phone | 1,067 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Greenwood | phone | 1,059 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Chesterfield | phone | 1,024 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Calhoun | divorce | 1,020 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Georgetown | phone | 982 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lancaster | divorce | 970 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Edgefield | divorce | 931 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Spartanburg | lt_lis_pendens | 917 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Bamberg | phone | 872 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Beaufort | lt_tax_lien | 863 | verifier is a declared wall | tax/property card: www.beaufortcountytreasurer.com |
| SC | Abbeville | phone | 862 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Anderson | lt_lis_pendens | 838 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Newberry | divorce | 819 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Chesterfield | divorce | 810 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Aiken | phone | 789 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Abbeville | divorce | 735 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Bamberg | divorce | 726 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Allendale | phone | 674 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lee | atty_deed_ref | 628 | paywall | register index: leesc.avenuinsights.com |
| SC | Lee | atty_rod_lien_checked | 628 | paywall | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Lee | liens | 628 | paywall | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Lee | phone | 624 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Allendale | divorce | 602 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Saluda | phone | 562 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lee | divorce | 532 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Aiken | divorce | 520 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Saluda | divorce | 493 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Laurens | lt_lis_pendens | 489 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Cherokee | lt_lis_pendens | 457 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Pickens | lt_lis_pendens | 440 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Anderson | lt_tax_lien | 411 | verifier is a declared wall | tax/property card: acpass.andersoncountysc.org |
| SC | McCormick | phone | 408 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Oconee | lt_lis_pendens | 393 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Beaufort | lt_lis_pendens | 376 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | McCormick | divorce | 336 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Greenville | lt_lis_pendens | 316 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Chester | phone | 313 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | UNKNOWN | lt_probate_notice | 295 | verifier is a declared wall | county missing from the county records matrix |
| NC | Cabarrus | lt_probate_notice | 255 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Marion | phone | 245 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | Guilford | lt_probate_notice | 225 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Johnston | lt_probate_notice | 216 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Chester | divorce | 214 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Union | lt_lis_pendens | 214 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Hampton | phone | 205 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Georgetown | lt_tax_lien | 202 | verifier is a declared wall | tax/property card: georgetowncountysctax.com |
| SC | Fairfield | phone | 198 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | Robeson | lt_probate_notice | 173 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Marion | divorce | 158 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Laurens | lt_tax_lien | 151 | verifier is a declared wall | tax/property card: laurenstreasurer.qpaybill.com |
| NC | Rockingham | lt_probate_notice | 146 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Forsyth | lt_probate_notice | 136 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Hampton | divorce | 136 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Fairfield | divorce | 131 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | UNKNOWN | lt_tax_lien | 123 | verifier is a declared wall | county unknown |
| NC | Rutherford | lt_probate_notice | 116 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | McDowell | lt_probate_notice | 84 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Spartanburg | divorce | 82 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Onslow | lt_probate_notice | 81 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Brunswick | lt_probate_notice | 80 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Iredell | lt_probate_notice | 77 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Greenville | divorce | 77 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Gaston | lt_probate_notice | 76 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Scotland | lt_probate_notice | 71 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Cleveland | tax_aging_surfaced | 62 | verifier is a declared wall | tax/property card: www.clevelandcountytaxes.com |
| NC | Sampson | lt_probate_notice | 62 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Richmond | lt_probate_notice | 60 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Bladen | lt_probate_notice | 59 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Polk | lt_probate_notice | 58 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Aiken | lt_lis_pendens | 58 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Pickens | divorce | 57 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Catawba | lt_probate_notice | 54 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | New Hanover | lt_probate_notice | 52 | verifier is a declared wall | county missing from the county records matrix |
| SC | Berkeley | lt_lis_pendens | 52 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Cleveland | lt_probate_notice | 50 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Columbus | lt_probate_notice | 50 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Edgefield | lt_lis_pendens | 48 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Saluda | lt_lis_pendens | 42 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Union | lt_tax_lien | 42 | verifier is a declared wall | tax/property card: uniontreasurer.qpaybill.com |
| NC | Burke | lt_probate_notice | 38 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Carteret | lt_probate_notice | 35 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Cherokee | divorce | 35 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Haywood | lt_probate_notice | 31 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Richland | lt_tax_lien | 31 | verifier is a declared wall | tax/property card:  |
| SC | Colleton | lt_lis_pendens | 28 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Anson | lt_probate_notice | 27 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Oconee | divorce | 26 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Union | divorce | 23 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Henderson | lt_probate_notice | 22 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Laurens | divorce | 22 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Mecklenburg | lt_probate_notice | 21 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Georgetown | lt_lis_pendens | 18 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Burke | tax_aging_surfaced | 17 | verifier is a declared wall | tax/property card: lrcpwa.ncptscloud.com |
| SC | Anderson | divorce | 17 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Dorchester | lt_lis_pendens | 15 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Richland | lt_lis_pendens | 12 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Nash | lt_probate_notice | 10 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Aiken | lt_tax_lien | 10 | verifier is a declared wall | tax/property card: aikencountysctax.com |
| SC | Florence | lt_tax_lien | 9 | verifier is a declared wall | tax/property card: web.florenceco.org |
| SC | Orangeburg | lt_lis_pendens | 9 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | York | lt_tax_lien | 9 | verifier is a declared wall | tax/property card: www.yorkcountysc.gov |
| NC | Transylvania | lt_probate_notice | 7 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Craven | lt_probate_notice | 6 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Newberry | lt_tax_lien | 6 | verifier is a declared wall | tax/property card: newberrytreasurer.qpaybill.com |
| SC | Saluda | lt_tax_lien | 6 | verifier is a declared wall | tax/property card: saludacountytreasurer.qpaybill.com |
| SC | Williamsburg | lt_lis_pendens | 6 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Cumberland | lt_probate_notice | 5 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Durham | lt_probate_notice | 5 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Randolph | lt_probate_notice | 5 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Greenwood | lt_lis_pendens | 5 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Jasper | lt_tax_lien | 5 | verifier is a declared wall | tax/property card: jaspercountydelinquenttax.qpaybill.com |
| SC | Orangeburg | lt_tax_lien | 5 | verifier is a declared wall | tax/property card: orangeburgtreasurer.qpaybill.com |
| NC | Alamance | lt_probate_notice | 4 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Lenoir | lt_probate_notice | 4 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Wake | lt_probate_notice | 4 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Clarendon | lt_tax_lien | 4 | verifier is a declared wall | tax/property card: clarendoncountysctax.qpaybill.com |
| SC | Darlington | lt_tax_lien | 4 | verifier is a declared wall | tax/property card: darlingtontreasurer.qpaybill.com |
| SC | Kershaw | lt_tax_lien | 4 | verifier is a declared wall | tax/property card: kershawcounty.qpaybill.com |
| SC | Sumter | lt_tax_lien | 4 | verifier is a declared wall | tax/property card: sumtercounty.qpaybill.com |
| SC | York | lt_lis_pendens | 4 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Pender | lt_probate_notice | 3 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Pitt | lt_probate_notice | 3 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Greenwood | lt_tax_lien | 3 | verifier is a declared wall | tax/property card: greenwoodco.corebtpay.com |
| SC | Hampton | lt_lis_pendens | 3 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Hampton | lt_tax_lien | 3 | verifier is a declared wall | tax/property card: hamptoncountytax.org |
| SC | Lancaster | lt_tax_lien | 3 | verifier is a declared wall | tax/property card: lancastersctax.qpaybill.com |
| SC | Marion | lt_tax_lien | 3 | verifier is a declared wall | tax/property card: www.marionsc.org |
| SC | UNKNOWN | lt_lis_pendens | 3 | verifier is a declared wall | county unknown |
| NC | Chatham | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Dare | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Halifax | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Hertford | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Lee | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Rowan | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Warren | lt_probate_notice | 2 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Barnwell | lt_tax_lien | 2 | verifier is a declared wall | tax/property card: barnwelltreasurer.qpaybill.com |
| SC | Lexington | lt_lis_pendens | 2 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Sumter | lt_lis_pendens | 2 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Avery | lt_probate_notice | 1 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Caldwell | lt_probate_notice | 1 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |

...and 68 more rows in this pile (full set in the source gap_list CSV, filtered to this reason pattern).

## 4. Stale scope -- needs a periodic recheck, not a wall

54 cells, 91,366 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | Sumter | heir_naming_publication | 5,613 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Sumter | quiet_title | 5,613 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Orangeburg | heir_naming_publication | 4,586 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Orangeburg | quiet_title | 4,586 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Berkeley | heir_naming_publication | 3,641 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Berkeley | quiet_title | 3,641 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Lexington | heir_naming_publication | 3,303 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Lexington | quiet_title | 3,303 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Williamsburg | heir_naming_publication | 2,956 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Williamsburg | quiet_title | 2,956 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Richland | heir_naming_publication | 2,236 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Richland | quiet_title | 2,236 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Dorchester | heir_naming_publication | 2,080 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Dorchester | quiet_title | 2,080 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Kershaw | heir_naming_publication | 2,064 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Kershaw | quiet_title | 2,064 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Barnwell | heir_naming_publication | 2,059 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Barnwell | quiet_title | 2,059 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | York | heir_naming_publication | 1,818 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | York | quiet_title | 1,818 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Clarendon | heir_naming_publication | 1,669 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Clarendon | quiet_title | 1,669 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Jasper | heir_naming_publication | 1,669 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Jasper | quiet_title | 1,669 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Dillon | heir_naming_publication | 1,520 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Dillon | quiet_title | 1,520 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Lancaster | heir_naming_publication | 1,246 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Lancaster | quiet_title | 1,246 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Calhoun | heir_naming_publication | 1,142 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Calhoun | quiet_title | 1,142 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Newberry | heir_naming_publication | 1,142 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Newberry | quiet_title | 1,142 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Edgefield | heir_naming_publication | 1,076 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Edgefield | quiet_title | 1,076 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Greenwood | heir_naming_publication | 1,070 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Greenwood | quiet_title | 1,070 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Bamberg | heir_naming_publication | 894 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Bamberg | quiet_title | 894 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Abbeville | heir_naming_publication | 870 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Abbeville | quiet_title | 870 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Allendale | heir_naming_publication | 686 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Allendale | quiet_title | 686 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Lee | heir_naming_publication | 628 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Lee | quiet_title | 628 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Saluda | heir_naming_publication | 564 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Saluda | quiet_title | 564 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | McCormick | heir_naming_publication | 411 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | McCormick | quiet_title | 411 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Chester | heir_naming_publication | 323 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Chester | quiet_title | 323 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Hampton | heir_naming_publication | 209 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Hampton | quiet_title | 209 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Fairfield | heir_naming_publication | 208 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
| SC | Fairfield | quiet_title | 208 | Column's SC estate lane only queries 18 of 46 counties per run; the other 28 were probed once (2026- | statewide: Column's SC estate lane only queries 18 of 46 cou |
