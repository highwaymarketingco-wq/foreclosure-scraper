# Hermes hand-off -- the walled bucket, triaged

Generated from `gap_list_2026-11-24.csv`. Regenerate with `python scripts/hermes_handoff.py` any time the gap list changes -- this file is a derived view, not hand-maintained.

Only **Hermes lane** (CAPTCHA or a required login) actually goes to Hermes. **Bot-wall, build in-house** is ordinary scraper work for this project (existing WAF-bypass/stealth-browser code, applied per-site) -- not a Hermes hand-off. The last two piles need a human policy call or a scheduled recheck, not a scraper at all -- see this script's own module docstring for why.

## 1. Hermes lane -- CAPTCHA or required login

509 cells, 1,126,823 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | York | usps_vacancy | 81,358 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Spartanburg | usps_vacancy | 48,828 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Mecklenburg | usps_vacancy | 39,893 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Lexington | atty_rod_lien_checked | 32,471 | login | register: Kofile/GovOS CountyFusion countyfusion14.govos.com |
| SC | Lexington | liens | 32,471 | login | register: Kofile/GovOS CountyFusion countyfusion14.govos.com |
| SC | Lexington | usps_vacancy | 32,471 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Lexington | probate | 31,585 | CAPTCHA | probate: www.lex-co.com |
| NC | Gaston | usps_vacancy | 26,673 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Lincoln | heir_naming_publication | 18,931 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Lincoln | multi_year_delinquent_tax | 18,931 | CAPTCHA | tax/property card: www.lincolncountytax.com |
| NC | Lincoln | quiet_title | 18,931 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Lincoln | usps_vacancy | 18,931 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Charleston | atty_rod_lien_checked | 13,590 | CAPTCHA | register: Charleston County ROD document search (county-buil |
| SC | Charleston | liens | 13,590 | CAPTCHA | register: Charleston County ROD document search (county-buil |
| SC | Charleston | usps_vacancy | 13,590 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wake | atty_rod_lien_checked | 12,977 | CAPTCHA | register: Tyler Technologies Self-Service (recorder search,  |
| NC | Wake | liens | 12,977 | CAPTCHA | register: Tyler Technologies Self-Service (recorder search,  |
| NC | Wake | usps_vacancy | 12,977 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Transylvania | usps_vacancy | 12,534 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Buncombe | usps_vacancy | 12,515 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Guilford | usps_vacancy | 12,399 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Rutherford | usps_vacancy | 11,222 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Forsyth | usps_vacancy | 10,786 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Brunswick | heir_naming_publication | 9,247 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Brunswick | liens | 9,247 | CAPTCHA | register: Internet Technologies Inc. (Inttek) 'Recording-Pro |
| NC | Brunswick | quiet_title | 9,247 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Brunswick | usps_vacancy | 9,247 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Catawba | usps_vacancy | 8,339 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Horry | usps_vacancy | 6,691 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Randolph | atty_rod_lien_checked | 6,357 | CAPTCHA | register: Courthouse Computer Systems (CCS) public web searc |
| NC | Randolph | liens | 6,357 | CAPTCHA | register: Courthouse Computer Systems (CCS) public web searc |
| NC | Randolph | usps_vacancy | 6,357 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Durham | usps_vacancy | 6,139 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Greenville | usps_vacancy | 6,007 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | New Hanover | usps_vacancy | 5,952 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Cumberland | usps_vacancy | 5,883 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Pickens | usps_vacancy | 5,795 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Sumter | usps_vacancy | 5,718 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Davidson | usps_vacancy | 5,513 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Pitt | usps_vacancy | 5,244 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Spartanburg | sos_dissolution | 5,136 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Onslow | usps_vacancy | 4,899 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Rowan | usps_vacancy | 4,763 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Orangeburg | atty_rod_lien_checked | 4,712 | login | register: County-run 'Register Of Deeds Remote Access Site'  |
| SC | Orangeburg | usps_vacancy | 4,712 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Berkeley | usps_vacancy | 4,620 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Colleton | usps_vacancy | 4,440 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Beaufort | usps_vacancy | 4,297 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Harnett | atty_rod_lien_checked | 4,242 | CAPTCHA | register: Courthouse Computer Systems LRSearch (MVC) at us6  |
| NC | Harnett | heir_naming_publication | 4,242 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Harnett | liens | 4,242 | CAPTCHA | register: Courthouse Computer Systems LRSearch (MVC) at us6  |
| NC | Harnett | quiet_title | 4,242 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Harnett | usps_vacancy | 4,242 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Henderson | usps_vacancy | 3,989 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Duplin | usps_vacancy | 3,984 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Beaufort | probate | 3,946 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Lee | usps_vacancy | 3,912 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Oconee | usps_vacancy | 3,889 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Florence | usps_vacancy | 3,884 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Williamsburg | atty_deed_ref | 3,868 | login | register index: williamsburgsc.avenuinsights.com |
| SC | Williamsburg | atty_rod_lien_checked | 3,868 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Williamsburg | liens | 3,868 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Williamsburg | usps_vacancy | 3,868 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Charleston | sos_dissolution | 3,846 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| SC | Richland | usps_vacancy | 3,761 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Duplin | probate | 3,706 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Laurens | usps_vacancy | 3,624 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Johnston | usps_vacancy | 3,572 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | McDowell | multi_year_delinquent_tax | 3,548 | CAPTCHA | tax/property card: www.bttaxpayerportal.com |
| NC | McDowell | rollback_exposure | 3,548 | CAPTCHA | tax/property card: www.bttaxpayerportal.com |
| NC | McDowell | usps_vacancy | 3,548 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hoke | heir_naming_publication | 3,475 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hoke | quiet_title | 3,475 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hoke | usps_vacancy | 3,475 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Cherokee | usps_vacancy | 3,423 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Darlington | atty_rod_lien_checked | 3,400 | login | register: Cott Systems RECORDhub recordhub.cottsystems.com |
| SC | Darlington | liens | 3,400 | login | register: Cott Systems RECORDhub recordhub.cottsystems.com |
| SC | Darlington | usps_vacancy | 3,400 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Anderson | multi_year_delinquent_tax | 3,388 | login | tax/property card: acpass.andersoncountysc.org |
| SC | Anderson | usps_vacancy | 3,388 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Polk | usps_vacancy | 3,386 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Union | usps_vacancy | 3,169 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hyde | heir_naming_publication | 3,153 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hyde | quiet_title | 3,153 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Hyde | usps_vacancy | 3,153 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Orange | heir_naming_publication | 3,054 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Orange | quiet_title | 3,054 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Orange | usps_vacancy | 3,054 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Scotland | usps_vacancy | 3,008 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Cabarrus | usps_vacancy | 2,998 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hoke | probate | 2,942 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Iredell | atty_rod_lien_checked | 2,895 | CAPTCHA | register: Courthouse Computer Systems LRSearch (new, since 2 |
| NC | Iredell | liens | 2,895 | CAPTCHA | register: Courthouse Computer Systems LRSearch (new, since 2 |
| NC | Iredell | usps_vacancy | 2,895 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Alamance | usps_vacancy | 2,884 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Hyde | probate | 2,665 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Moore | usps_vacancy | 2,652 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Dorchester | usps_vacancy | 2,619 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Anson | usps_vacancy | 2,601 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Barnwell | usps_vacancy | 2,586 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Pasquotank | usps_vacancy | 2,480 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Carteret | heir_naming_publication | 2,469 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Carteret | quiet_title | 2,469 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Carteret | usps_vacancy | 2,469 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | McDowell | atty_tax_verified_confirmed | 2,468 | CAPTCHA | tax/property card: www.bttaxpayerportal.com |
| NC | Rockingham | usps_vacancy | 2,311 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Orange | probate | 2,289 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Harnett | probate | 2,260 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Lincoln | atty_tax_verified_confirmed | 2,228 | CAPTCHA | tax/property card: www.lincolncountytax.com |
| NC | Bertie | multi_year_delinquent_tax | 2,186 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | rollback_exposure | 2,186 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | two_year_delinquent | 2,186 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | usps_vacancy | 2,186 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Kershaw | atty_deed_ref | 2,182 | login | register index: kershawsc.avenuinsights.com |
| SC | Kershaw | atty_rod_lien_checked | 2,182 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Kershaw | liens | 2,182 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Kershaw | usps_vacancy | 2,182 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Washington | usps_vacancy | 2,177 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Nash | usps_vacancy | 2,107 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Moore | probate | 2,086 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Burke | multi_year_delinquent_tax | 2,077 | CAPTCHA | tax/property card: lrcpwa.ncptscloud.com |
| NC | Burke | usps_vacancy | 2,077 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Georgetown | multi_year_delinquent_tax | 2,072 | CAPTCHA | tax/property card: georgetowncountysctax.com |
| SC | Georgetown | rollback_exposure | 2,072 | CAPTCHA | tax/property card: georgetowncountysctax.com |
| SC | Georgetown | tax_aging_surfaced | 2,072 | CAPTCHA | tax/property card: georgetowncountysctax.com |
| SC | Georgetown | usps_vacancy | 2,072 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Beaufort | usps_vacancy | 2,044 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Horry | sos_dissolution | 1,995 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Granville | usps_vacancy | 1,957 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Perquimans | usps_vacancy | 1,896 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Marlboro | usps_vacancy | 1,874 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wayne | usps_vacancy | 1,860 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Jasper | atty_rod_lien_checked | 1,846 | CAPTCHA | register: Courthouse Computer Systems (CCHS) Registrar us6.c |
| SC | Jasper | usps_vacancy | 1,846 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Yadkin | usps_vacancy | 1,756 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Madison | usps_vacancy | 1,715 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Person | heir_naming_publication | 1,699 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Person | quiet_title | 1,699 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Person | usps_vacancy | 1,699 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Robeson | usps_vacancy | 1,684 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Clarendon | usps_vacancy | 1,673 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Craven | liens | 1,658 | CAPTCHA | register: Courthouse Computer Systems LRSearch (us5.courthou |
| NC | Craven | usps_vacancy | 1,658 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Union | probate | 1,638 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Cleveland | multi_year_delinquent_tax | 1,619 | CAPTCHA | tax/property card: www.clevelandcountytaxes.com |
| NC | Cleveland | rollback_exposure | 1,619 | CAPTCHA | tax/property card: www.clevelandcountytaxes.com |
| NC | Cleveland | usps_vacancy | 1,619 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Chesterfield | usps_vacancy | 1,613 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Lancaster | usps_vacancy | 1,593 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Greenville | sos_dissolution | 1,570 | SC Secretary of State search is CAPTCHA-walled | statewide: SC Secretary of State search is CAPTCHA-walled |
| NC | Chatham | usps_vacancy | 1,565 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Bertie | atty_tax_verified_confirmed | 1,562 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Pender | heir_naming_publication | 1,550 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Pender | quiet_title | 1,550 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Pender | usps_vacancy | 1,550 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Aiken | usps_vacancy | 1,547 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Dillon | usps_vacancy | 1,536 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Bertie | tax_aging_surfaced | 1,535 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| NC | Bertie | lt_tax_lien | 1,534 | CAPTCHA | tax/property card: bertie.webtaxpay.com |
| SC | Union | usps_vacancy | 1,496 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Wilson | usps_vacancy | 1,404 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Perquimans | probate | 1,394 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Bertie | probate | 1,378 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Franklin | usps_vacancy | 1,377 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Stanly | usps_vacancy | 1,353 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Calhoun | usps_vacancy | 1,338 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Washington | probate | 1,323 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| SC | Greenwood | usps_vacancy | 1,303 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Caswell | usps_vacancy | 1,294 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Surry | heir_naming_publication | 1,287 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Surry | quiet_title | 1,287 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Surry | usps_vacancy | 1,287 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Haywood | usps_vacancy | 1,268 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Newberry | atty_deed_ref | 1,253 | login | register index: newberrysc.avenuinsights.com |
| SC | Newberry | atty_rod_lien_checked | 1,253 | login | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Newberry | usps_vacancy | 1,253 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Granville | probate | 1,183 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Jones | heir_naming_publication | 1,182 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jones | quiet_title | 1,182 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jones | usps_vacancy | 1,182 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Chowan | usps_vacancy | 1,177 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Edgecombe | heir_naming_publication | 1,083 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Edgecombe | quiet_title | 1,083 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Edgecombe | usps_vacancy | 1,083 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Columbus | multi_year_delinquent_tax | 1,079 | CAPTCHA | tax/property card: secure.webtaxpay.com |
| NC | Columbus | repeat_tax_loss | 1,079 | CAPTCHA | tax/property card: secure.webtaxpay.com |
| NC | Columbus | rollback_exposure | 1,079 | CAPTCHA | tax/property card: secure.webtaxpay.com |
| NC | Columbus | tax_aging_surfaced | 1,079 | CAPTCHA | tax/property card: secure.webtaxpay.com |
| NC | Columbus | two_year_delinquent | 1,079 | CAPTCHA | tax/property card: secure.webtaxpay.com |
| NC | Columbus | usps_vacancy | 1,079 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| SC | Edgefield | usps_vacancy | 1,076 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Caldwell | multi_year_delinquent_tax | 1,068 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | repeat_tax_loss | 1,068 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | tax_aging_surfaced | 1,068 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | two_year_delinquent | 1,068 | CAPTCHA | tax/property card: www.caldwellcountynctax.com |
| NC | Caldwell | usps_vacancy | 1,068 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Person | probate | 1,064 | CAPTCHA | probate: portal-nc.tylertech.cloud |
| NC | Sampson | usps_vacancy | 1,041 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |
| NC | Jackson | quiet_title | 981 | no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled | statewide: no Column paper in this county; ncnotices.com bod |
| NC | Jackson | usps_vacancy | 981 | HUD USPS vacancy data needs a registered login | statewide: HUD USPS vacancy data needs a registered login |

...and 309 more rows in this pile (full set in the source gap_list CSV, filtered to this reason pattern).

## 2. Bot-wall, build in-house -- Cloudflare/WAF, not Hermes

100 cells, 581,496 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | York | multi_year_delinquent_tax | 81,358 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | York | rollback_exposure | 81,358 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | York | tax_aging_surfaced | 81,358 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | York | two_year_delinquent | 81,358 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | York | beds_baths | 80,668 | bot check (Cloudflare/WAF) | tax/property card: www.yorkcountysc.gov |
| SC | Charleston | multi_year_delinquent_tax | 13,590 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Charleston | rollback_exposure | 13,590 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| NC | Rutherford | multi_year_delinquent_tax | 11,222 | bot check (Cloudflare/WAF) | tax/property card: rutherfordcountync.gov |
| SC | Charleston | atty_tax_verified_confirmed | 7,518 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| NC | Rowan | atty_rod_lien_checked | 4,763 | bot check (Cloudflare/WAF) | register: rod.rowancountync.gov (atty_rod_lien_checked: bloc |
| NC | Rowan | liens | 4,763 | bot check (Cloudflare/WAF) | register: rod.rowancountync.gov (liens: blocked) |
| SC | Orangeburg | assessed_value | 4,569 | Cloudflare check on the county property card | county GIS: gis2.orangeburgcounty.org |
| SC | Charleston | lt_tax_sale | 4,156 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| NC | Lee | rollback_exposure | 3,912 | bot check (Cloudflare/WAF) | tax/property card: taxaccess.leecountync.gov |
| SC | Florence | assessed_value | 3,838 | Cloudflare check on the county property card | county GIS: services1.arcgis.com |
| SC | Richland | multi_year_delinquent_tax | 3,761 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | rollback_exposure | 3,761 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | tax_aging_surfaced | 3,761 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Richland | two_year_delinquent | 3,761 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Polk | multi_year_delinquent_tax | 3,386 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Polk | rollback_exposure | 3,386 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Polk | tax_aging_surfaced | 3,386 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| SC | Colleton | assessed_value | 3,323 | Cloudflare check on the county property card | county GIS: services1.arcgis.com |
| NC | Union | multi_year_delinquent_tax | 3,169 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | repeat_tax_loss | 3,169 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | rollback_exposure | 3,169 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | tax_aging_surfaced | 3,169 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Union | two_year_delinquent | 3,169 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Polk | atty_tax_verified_confirmed | 2,752 | bot check (Cloudflare/WAF) | tax/property card: www.polknc.gov |
| NC | Moore | atty_rod_lien_checked | 2,652 | bot check (Cloudflare/WAF) | register: Aumentum Recorder web access (Harris Recording Sol |
| NC | Moore | liens | 2,652 | bot check (Cloudflare/WAF) | register: Aumentum Recorder web access (Harris Recording Sol |
| NC | Washington | atty_rod_lien_checked | 2,177 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Washington | liens | 2,177 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Kershaw | probate | 1,920 | bot check (Cloudflare/WAF) | probate: www.kershaw.sc.gov |
| NC | Chatham | multi_year_delinquent_tax | 1,565 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Chatham | repeat_tax_loss | 1,565 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Chatham | tax_aging_surfaced | 1,565 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Chatham | two_year_delinquent | 1,565 | bot check (Cloudflare/WAF) | tax/property card:  |
| SC | Lancaster | assessed_value | 1,551 | Cloudflare check on the county property card | county GIS: services3.arcgis.com |
| SC | Aiken | atty_rod_lien_checked | 1,547 | bot check (Cloudflare/WAF) | register:  www.aikencountysc.gov |
| SC | Aiken | liens | 1,547 | bot check (Cloudflare/WAF) | register:  www.aikencountysc.gov |
| NC | Union | atty_tax_verified_confirmed | 1,509 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Wilson | multi_year_delinquent_tax | 1,404 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | repeat_tax_loss | 1,404 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | rollback_exposure | 1,404 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | tax_aging_surfaced | 1,404 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| NC | Wilson | two_year_delinquent | 1,404 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| SC | Newberry | lot_size | 1,189 | Cloudflare check on the county property card | county GIS: map.newberrycounty.net |
| SC | Newberry | assessed_value | 1,092 | Cloudflare check on the county property card | county GIS: map.newberrycounty.net |
| NC | Edgecombe | multi_year_delinquent_tax | 1,083 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Edgecombe | repeat_tax_loss | 1,083 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Edgecombe | tax_aging_surfaced | 1,083 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Edgecombe | two_year_delinquent | 1,083 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| SC | Edgefield | lot_size | 1,025 | Cloudflare check on the county property card | county GIS: qpublic.net |
| SC | Edgefield | assessed_value | 1,024 | Cloudflare check on the county property card | county GIS: qpublic.net |
| NC | Halifax | multi_year_delinquent_tax | 974 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | repeat_tax_loss | 974 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | rollback_exposure | 974 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | tax_aging_surfaced | 974 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Halifax | two_year_delinquent | 974 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| NC | Ashe | multi_year_delinquent_tax | 806 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Ashe | repeat_tax_loss | 806 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Ashe | tax_aging_surfaced | 806 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| NC | Ashe | two_year_delinquent | 806 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| SC | Charleston | lt_tax_sale_overage | 752 | bot check (Cloudflare/WAF) | tax/property card: sc-charleston.publicaccessnow.com |
| NC | Chatham | atty_tax_verified_confirmed | 676 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Alleghany | atty_rod_lien_checked | 613 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCHS), new-style host |
| NC | Alleghany | liens | 613 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCHS), new-style host |
| NC | Tyrrell | atty_rod_lien_checked | 537 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Tyrrell | liens | 537 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Chester | probate | 460 | bot check (Cloudflare/WAF) | probate:  |
| NC | Avery | multi_year_delinquent_tax | 372 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | repeat_tax_loss | 372 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | rollback_exposure | 372 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | tax_aging_surfaced | 372 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Avery | two_year_delinquent | 372 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Rockingham | divorce_no_subsequent_deed | 327 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) 'e-Vault' us5.co |
| NC | Tyrrell | marriage_license | 326 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Chester | atty_probate_case | 300 | bot check (Cloudflare/WAF) | probate:  |
| NC | Wilson | atty_tax_verified_confirmed | 268 | bot check (Cloudflare/WAF) | tax/property card: www.wilsoncountync.gov |
| SC | Richland | lt_tax_sale_overage | 208 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Ashe | atty_tax_verified_confirmed | 179 | bot check (Cloudflare/WAF) | tax/property card: qpublic.schneidercorp.com |
| SC | Kershaw | atty_probate_case | 174 | bot check (Cloudflare/WAF) | probate: www.kershaw.sc.gov |
| NC | Gaston | divorce_no_subsequent_deed | 145 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems LRSearch (MVC/DevExpre |
| NC | Avery | atty_tax_verified_confirmed | 128 | bot check (Cloudflare/WAF) | tax/property card: webtax.averycountync.gov |
| NC | Edgecombe | atty_tax_verified_confirmed | 101 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Halifax | atty_tax_verified_confirmed | 85 | bot check (Cloudflare/WAF) | tax/property card: halifaxnctax.com |
| SC | Spartanburg | probate | 75 | bot check (Cloudflare/WAF) | probate: www.spartanburgcounty.gov |
| NC | Moore | divorce_no_subsequent_deed | 58 | bot check (Cloudflare/WAF) | register: Aumentum Recorder web access (Harris Recording Sol |
| SC | Richland | atty_tax_verified_confirmed | 46 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Pender | divorce_no_subsequent_deed | 37 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Pasquotank | divorce_no_subsequent_deed | 20 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Edgecombe | lt_tax_sale | 17 | bot check (Cloudflare/WAF) | tax/property card: taxpa.edgecombecountync.gov |
| NC | Person | divorce_no_subsequent_deed | 15 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Richland | lt_tax_sale | 13 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Perquimans | divorce_no_subsequent_deed | 5 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| NC | Chatham | lt_tax_sale | 4 | bot check (Cloudflare/WAF) | tax/property card:  |
| NC | Tyrrell | divorce_no_subsequent_deed | 3 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |
| SC | Berkeley | atty_probate_case | 2 | bot check (Cloudflare/WAF) | probate: berkeleycountysc.gov |
| NC | Washington | divorce_no_subsequent_deed | 1 | bot check (Cloudflare/WAF) | register: Courthouse Computer Systems (CCS) hosted search us |

## 3. Human judgment call -- NOT a scrape target

293 cells, 441,324 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | York | phone | 81,330 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | York | divorce | 80,807 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Lexington | phone | 32,430 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lexington | divorce | 31,585 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Charleston | phone | 13,504 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Horry | phone | 6,616 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Greenville | phone | 5,840 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Sumter | phone | 5,657 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Sumter | divorce | 4,791 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Orangeburg | phone | 4,678 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Horry | divorce | 4,551 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Berkeley | phone | 4,441 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Colleton | phone | 4,427 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Orangeburg | divorce | 3,974 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Florence | atty_legal_description | 3,884 | only on the deed image | register: search.florencedeeds.com |
| SC | Williamsburg | phone | 3,861 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Oconee | phone | 3,852 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Florence | phone | 3,850 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Richland | atty_deed_ref | 3,761 | paywall | register index: www.richlandcountysc.gov |
| SC | Richland | atty_rod_lien_checked | 3,761 | paywall | register: Richland County 'Online Data Services' subscriptio |
| SC | Richland | liens | 3,761 | paywall | register: Richland County 'Online Data Services' subscriptio |
| SC | Richland | phone | 3,709 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Berkeley | divorce | 3,667 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Laurens | phone | 3,546 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Cherokee | liens | 3,423 | terms forbid automation | register: Avenu Insights / Neumo Records Management (GRIDS), |
| SC | Cherokee | phone | 3,414 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Charleston | tax_aging_surfaced | 3,412 | verifier is a declared wall | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Darlington | phone | 3,383 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Williamsburg | divorce | 3,365 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Anderson | phone | 3,333 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Charleston | lt_tax_lien | 3,285 | verifier is a declared wall | tax/property card: sc-charleston.publicaccessnow.com |
| SC | Florence | divorce | 3,151 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Richland | divorce | 3,071 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Darlington | divorce | 2,978 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Dorchester | atty_legal_description | 2,619 | only on the deed image | register: search.dorchesterdeeds.com |
| SC | Dorchester | phone | 2,587 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Barnwell | phone | 2,575 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Dorchester | divorce | 2,255 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Barnwell | divorce | 2,222 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Kershaw | phone | 2,172 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Georgetown | phone | 2,057 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Beaufort | phone | 1,998 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Kershaw | divorce | 1,920 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| NC | McDowell | tax_aging_surfaced | 1,875 | verifier is a declared wall | tax/property card: www.bttaxpayerportal.com |
| SC | Marlboro | phone | 1,864 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Jasper | phone | 1,840 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | Lincoln | tax_aging_surfaced | 1,804 | verifier is a declared wall | tax/property card: www.lincolncountytax.com |
| SC | Marlboro | divorce | 1,711 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Clarendon | phone | 1,667 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Chesterfield | phone | 1,603 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Jasper | divorce | 1,603 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Lancaster | phone | 1,578 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Aiken | phone | 1,531 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Dillon | phone | 1,520 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Union | phone | 1,486 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Clarendon | divorce | 1,425 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Charleston | lt_lis_pendens | 1,406 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Chesterfield | divorce | 1,389 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Dillon | divorce | 1,364 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Calhoun | atty_deed_ref | 1,338 | paywall | register index: www.titlesearcher.com |
| SC | Calhoun | atty_rod_lien_checked | 1,338 | paywall | register: TitleSearcher (paid subscription); Clerk of Court  |
| SC | Calhoun | liens | 1,338 | paywall | register: TitleSearcher (paid subscription); Clerk of Court  |
| SC | Calhoun | phone | 1,334 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lancaster | divorce | 1,317 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Greenwood | phone | 1,292 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Aiken | divorce | 1,262 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Newberry | phone | 1,232 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Calhoun | divorce | 1,216 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Edgefield | phone | 1,067 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Beaufort | lt_tax_lien | 1,037 | verifier is a declared wall | tax/property card: www.beaufortcountytreasurer.com |
| SC | Edgefield | divorce | 931 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Newberry | divorce | 930 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Spartanburg | lt_lis_pendens | 917 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Bamberg | phone | 872 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Abbeville | phone | 862 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Anderson | lt_lis_pendens | 838 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Pickens | lt_probate_notice | 799 | verifier is a declared wall | probate: www.co.pickens.sc.us |
| SC | Abbeville | divorce | 735 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Bamberg | divorce | 726 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Allendale | phone | 674 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lee | atty_deed_ref | 628 | paywall | register index: leesc.avenuinsights.com |
| SC | Lee | atty_rod_lien_checked | 628 | paywall | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Lee | liens | 628 | paywall | register: Neumo Records Management (formerly Avenu Insights  |
| SC | Lee | phone | 624 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Allendale | divorce | 602 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Saluda | phone | 562 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Chester | phone | 559 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Lee | divorce | 532 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | McCormick | phone | 524 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Saluda | divorce | 493 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Laurens | lt_lis_pendens | 489 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Hampton | phone | 485 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| SC | Chester | divorce | 460 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Cherokee | lt_lis_pendens | 457 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | McCormick | divorce | 452 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Pickens | lt_lis_pendens | 440 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Hampton | divorce | 416 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | Anderson | lt_tax_lien | 411 | verifier is a declared wall | tax/property card: acpass.andersoncountysc.org |
| SC | Oconee | lt_lis_pendens | 393 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Beaufort | lt_lis_pendens | 376 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Cherokee | lt_probate_notice | 344 | verifier is a declared wall | probate: cherokeecountysc.gov |
| NC | Cabarrus | lt_probate_notice | 320 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Greenville | lt_lis_pendens | 316 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Guilford | lt_probate_notice | 309 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | UNKNOWN | lt_probate_notice | 295 | verifier is a declared wall | county missing from the county records matrix |
| NC | Johnston | lt_probate_notice | 285 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Marion | phone | 258 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | Robeson | lt_probate_notice | 244 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Greenwood | lt_probate_notice | 218 | verifier is a declared wall | probate: scportal.hostedbyspartan.com |
| SC | Union | lt_lis_pendens | 214 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Georgetown | lt_tax_lien | 202 | verifier is a declared wall | tax/property card: georgetowncountysctax.com |
| SC | Fairfield | phone | 198 | SC voter list is sold, not free | statewide: SC voter list is sold, not free |
| NC | Forsyth | lt_probate_notice | 195 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Rockingham | lt_probate_notice | 194 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Laurens | lt_probate_notice | 189 | verifier is a declared wall | probate: laurenscountysc.gov |
| SC | Marion | divorce | 171 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | UNKNOWN | lt_probate_notice | 155 | verifier is a declared wall | county missing from the county records matrix |
| SC | Laurens | lt_tax_lien | 151 | verifier is a declared wall | tax/property card: laurenstreasurer.qpaybill.com |
| SC | Beaufort | lt_probate_notice | 143 | verifier is a declared wall | probate: www.beaufortcountysc.gov |
| SC | Fairfield | divorce | 131 | SC family-court index terms forbid automation | statewide: SC family-court index terms forbid automation |
| SC | UNKNOWN | lt_tax_lien | 123 | verifier is a declared wall | county unknown |
| NC | Rutherford | lt_probate_notice | 116 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Spartanburg | lt_probate_notice | 111 | verifier is a declared wall | probate: www.spartanburgcounty.gov |
| NC | Iredell | lt_probate_notice | 107 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Colleton | lt_probate_notice | 102 | verifier is a declared wall | probate: www.southcarolinaprobate.net |
| SC | Newberry | lt_probate_notice | 100 | verifier is a declared wall | probate: scportal.hostedbyspartan.com |
| SC | Anderson | lt_probate_notice | 99 | verifier is a declared wall | probate: acpass.andersoncountysc.org |
| NC | McDowell | lt_probate_notice | 90 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Scotland | lt_probate_notice | 88 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Onslow | lt_probate_notice | 87 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Sampson | lt_probate_notice | 84 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Richmond | lt_probate_notice | 83 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Brunswick | lt_probate_notice | 80 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Spartanburg | divorce | 80 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Gaston | lt_probate_notice | 79 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Bladen | lt_probate_notice | 78 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Greenville | divorce | 76 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Sumter | lt_probate_notice | 76 | verifier is a declared wall | probate: www.southcarolinaprobate.net |
| NC | Catawba | lt_probate_notice | 73 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Aiken | lt_lis_pendens | 70 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Richland | lt_lis_pendens | 70 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Cleveland | tax_aging_surfaced | 66 | verifier is a declared wall | tax/property card: www.clevelandcountytaxes.com |
| NC | Columbus | lt_probate_notice | 62 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Barnwell | lt_probate_notice | 61 | verifier is a declared wall | probate: www.southcarolinaprobate.net |
| NC | Polk | lt_probate_notice | 58 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Pickens | divorce | 56 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Cleveland | lt_probate_notice | 55 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | New Hanover | lt_probate_notice | 53 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Berkeley | lt_lis_pendens | 52 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Edgefield | lt_lis_pendens | 48 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| NC | Burke | lt_probate_notice | 46 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | York | lt_lis_pendens | 45 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Saluda | lt_lis_pendens | 42 | verifier is a declared wall | statewide: SC Public Index terms forbid automated querying |
| SC | Union | lt_tax_lien | 42 | verifier is a declared wall | tax/property card: uniontreasurer.qpaybill.com |
| NC | Anson | lt_probate_notice | 37 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Carteret | lt_probate_notice | 35 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Cherokee | divorce | 33 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Richland | lt_tax_lien | 33 | verifier is a declared wall | tax/property card:  |
| NC | Haywood | lt_probate_notice | 31 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Mecklenburg | lt_probate_notice | 31 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Colleton | lt_lis_pendens | 28 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Oconee | lt_probate_notice | 28 | verifier is a declared wall | probate: www.southcarolinaprobate.net |
| SC | Aiken | lt_probate_notice | 26 | verifier is a declared wall | probate: www.southcarolinaprobate.net |
| SC | Oconee | divorce | 26 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Sumter | lt_lis_pendens | 25 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Henderson | lt_probate_notice | 23 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Union | divorce | 23 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| NC | Dare | lt_lis_pendens | 21 | verifier is a declared wall | statewide: NC eCourts Judgment Search (open JSON) + register |
| SC | Orangeburg | lt_lis_pendens | 21 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Berkeley | lt_probate_notice | 20 | verifier is a declared wall | probate: berkeleycountysc.gov |
| SC | Lancaster | lt_lis_pendens | 19 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| NC | Burke | tax_aging_surfaced | 18 | verifier is a declared wall | tax/property card: lrcpwa.ncptscloud.com |
| SC | Georgetown | lt_lis_pendens | 18 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Anderson | divorce | 17 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Greenwood | lt_lis_pendens | 17 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Laurens | divorce | 17 | verifier is a declared wall | statewide: SC family-court index terms forbid automation |
| SC | Williamsburg | lt_lis_pendens | 17 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Dorchester | lt_lis_pendens | 15 | SC Public Index terms forbid automated querying | statewide: SC Public Index terms forbid automated querying |
| SC | Lancaster | lt_probate_notice | 15 | verifier is a declared wall | probate: www.southcarolinaprobate.net |
| NC | Nash | lt_probate_notice | 12 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Cumberland | lt_probate_notice | 11 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Richland | lt_probate_notice | 11 | verifier is a declared wall | probate: www7.richlandcountysc.gov |
| SC | York | lt_tax_lien | 11 | verifier is a declared wall | tax/property card: www.yorkcountysc.gov |
| SC | Aiken | lt_tax_lien | 10 | verifier is a declared wall | tax/property card: aikencountysctax.com |
| NC | Craven | lt_probate_notice | 9 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Florence | lt_tax_lien | 9 | verifier is a declared wall | tax/property card: web.florenceco.org |
| SC | Union | lt_probate_notice | 9 | verifier is a declared wall | probate:  |
| NC | Randolph | lt_probate_notice | 8 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Alamance | lt_probate_notice | 7 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Transylvania | lt_probate_notice | 7 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Wake | lt_probate_notice | 7 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Durham | lt_probate_notice | 6 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Calhoun | lt_probate_notice | 6 | verifier is a declared wall | probate: govcloud2.hostedbyspartan.com |
| SC | Newberry | lt_tax_lien | 6 | verifier is a declared wall | tax/property card: newberrytreasurer.qpaybill.com |
| SC | Saluda | lt_tax_lien | 6 | verifier is a declared wall | tax/property card: saludacountytreasurer.qpaybill.com |
| NC | Lenoir | lt_probate_notice | 5 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Pitt | lt_probate_notice | 5 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| NC | Rowan | lt_probate_notice | 5 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |
| SC | Jasper | lt_tax_lien | 5 | verifier is a declared wall | tax/property card: jaspercountydelinquenttax.qpaybill.com |
| NC | Warren | lt_probate_notice | 4 | verifier is a declared wall | probate: portal-nc.tylertech.cloud |

...and 93 more rows in this pile (full set in the source gap_list CSV, filtered to this reason pattern).

## 4. Stale scope -- needs a periodic recheck, not a wall

50 cells, 309,796 est_rows_affected combined.

| state | county | column | est_rows | reason | source |
|---|---|---|---|---|---|
| SC | York | heir_naming_publication | 81,358 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | York | quiet_title | 81,358 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Lexington | heir_naming_publication | 32,471 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Lexington | quiet_title | 32,471 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Sumter | heir_naming_publication | 5,718 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Sumter | quiet_title | 5,718 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Berkeley | heir_naming_publication | 4,620 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Berkeley | quiet_title | 4,620 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Williamsburg | heir_naming_publication | 3,868 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Williamsburg | quiet_title | 3,868 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Richland | heir_naming_publication | 3,761 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Richland | quiet_title | 3,761 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Dorchester | heir_naming_publication | 2,619 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Dorchester | quiet_title | 2,619 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Barnwell | heir_naming_publication | 2,586 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Barnwell | quiet_title | 2,586 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Kershaw | heir_naming_publication | 2,182 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Kershaw | quiet_title | 2,182 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Jasper | heir_naming_publication | 1,846 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Jasper | quiet_title | 1,846 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Clarendon | heir_naming_publication | 1,673 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Clarendon | quiet_title | 1,673 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Lancaster | heir_naming_publication | 1,593 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Lancaster | quiet_title | 1,593 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Dillon | heir_naming_publication | 1,536 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Dillon | quiet_title | 1,536 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Greenwood | heir_naming_publication | 1,303 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Greenwood | quiet_title | 1,303 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Newberry | heir_naming_publication | 1,253 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Newberry | quiet_title | 1,253 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Edgefield | heir_naming_publication | 1,076 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Edgefield | quiet_title | 1,076 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Bamberg | heir_naming_publication | 894 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Bamberg | quiet_title | 894 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Abbeville | heir_naming_publication | 870 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Abbeville | quiet_title | 870 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Allendale | heir_naming_publication | 686 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Allendale | quiet_title | 686 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Lee | heir_naming_publication | 628 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Lee | quiet_title | 628 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Chester | heir_naming_publication | 569 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Chester | quiet_title | 569 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Saluda | heir_naming_publication | 564 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Saluda | quiet_title | 564 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | McCormick | heir_naming_publication | 527 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | McCormick | quiet_title | 527 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Hampton | heir_naming_publication | 489 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Hampton | quiet_title | 489 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Fairfield | heir_naming_publication | 208 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
| SC | Fairfield | quiet_title | 208 | Column's SC estate lane only queries 21 of 46 counties per run (19 by exact county match + Orangebur | statewide: Column's SC estate lane only queries 21 of 46 cou |
