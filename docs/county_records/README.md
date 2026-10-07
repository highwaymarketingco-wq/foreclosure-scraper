# County records matrix: what is free to read, county by county (NC + SC)

Built 2026-10-07 by reading each county's own portals (read-only, polite, no CAPTCHA/login/paywall touched). Source data: `nc_batch1.json`, `nc_batch2.json`, `nc_batch3.json`, `sc_batch1.json`, `sc_batch2.json`, merged in `county_records_matrix.json`. Purpose: a title check per lead needs the legal description, the last deed and a few deeds back, the taxpayer, heirs and probate. This says, per county, what we can fetch for free and where a person (or the attorney's own subscription) is needed.

Known gaps: McCormick SC is missing (the older county registry has a junk row in its place). `docs/county_systems_registry.json` word-matches 'login'/'CAPTCHA' and is wrong for several counties; this matrix supersedes it where they disagree. Probate: every NC estate search is the statewide eCourts portal (free to a person, CAPTCHA to scripts, so a person does it). 'We read it' is the repo state on 2026-10-07.

| county | st | deed index | back to | images free | legal desc online | bots banned by terms | we read it | a person needed |
|---|---|---|---|---|---|---|---|---|
| Pamlico | NC | free index (Cott Systems eSearch v4 (cot) | 1872 | unknown | yes | no | no | If a deed image will not open or is illegible, or the chain runs before 1872, a person must view the books at ... |
| Pasquotank | NC | walled (Courthouse Computer Systems ) |  | unknown | ? | no | no | A person must open the CCS deed search in a normal browser (it shows a Cloudflare check to scripts) or visit t... |
| Pender | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | no | no | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Burga... |
| Perquimans | NC | walled (Courthouse Computer Systems ) |  | unknown | ? | no | no | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Hertf... |
| Person | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | no | no | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Roxbo... |
| Pitt | NC | free index (Cott Systems eSearch (county) |  | unknown | yes | no | no | Free by guest sign-in; a person should check the Certified Dates page for the index start and visit the Greenv... |
| Polk | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | no | yes | Free index works; a person must view or buy the deed images (or visit the Columbus office) to read the full le... |
| Randolph | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | unknown | no | A person must pass the CAPTCHA on the CCS deed search (or visit the Asheboro office) to pull deeds, old index ... |
| Richmond | NC | walled (Courthouse Computer Systems ) |  | unknown | ? | no | no | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Rocki... |
| Robeson | NC | free index (Business Information Systems) | 1787 | unknown | yes | no | no | Pre-1974 searches mean paging through scanned old index books online; anything older than the books or illegib... |
| Rockingham | NC | walled (Courthouse Computer Systems ) | 1787 | unknown | yes | no | no | A person must open the e-Vault in a normal browser (scripts get a Cloudflare check) and, for 1787-1995, page t... |
| Rowan | NC | free index (Cott Systems eSearch (county) | 1753 | unknown | yes | no | no | Sign in as guest for the index; if images or older books need a paid subscription, a person must view them at ... |
| Rutherford | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | no | no | Sign in as guest for the index; images and older books not confirmed free, so a person may need the Rutherford... |
| Sampson | NC | free index (Logan Systems Public Records) | 1785 | yes | yes | no | no | Free online covers the whole chain; a person is needed only for illegible images or to confirm the scanned pre... |
| Scotland | NC | free index (Cott Systems eSearch (cottho) | 1978 | unknown | yes | no | no | For deeds before 1978 a person must open the pre-1978 site in a normal browser (scripts get a Cloudflare check... |
| Stanly | NC | free index (Courthouse Computer Systems ) | 1985 | yes | yes | no | no | Free online view covers 1985 forward plus scanned old index books; to print copies or check deed books 396-482... |
| Stokes | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | no | no | A person must pass the CAPTCHA on the CCS deed search (or visit the Danbury office) to pull deeds, old index b... |
| Surry | NC | free index (Courthouse Computer Systems ) | 1958 | yes | ? | no | no | Search and view online for free; to print certified or plain copies a person needs a print login or a visit to... |
| Swain | NC | free index (Logan Systems remote access ) | 1871 | yes | yes | no | no | Free online covers deed images back to 1871; a person must visit the Bryson City office only for deed of trust... |
| Transylvania | NC | free index ('The Lookup' land record sea) | 1973 | yes | yes | no | yes | For deeds recorded before 1973 a person must use the books at the Brevard register of deeds office or an abstr... |
| Tyrrell | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | no | no | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or call/visit the ... |
| Union | NC | free index (Logan Systems Public Records) | 1842 | yes | yes | no | no | Deeds are free online, but deeds of trust and other security instruments are withheld online, so a person must... |
| Vance | NC | free index (Logan Systems remote access ) | 1881 | yes | ? | no | no | Free online covers the full deed chain back to 1881; a person is needed only for illegible images or certified... |
| Wake | NC | walled (Tyler Technologies Self-Serv) |  | unknown | yes | no | no | A person must tick the reCAPTCHA on the Wake deed search to read deeds and legal descriptions (or visit the Ra... |
| Warren | NC | free index (Logan Systems remote access ) | 1764 | yes | yes | no | no | Free online covers the whole chain; a person is needed only for illegible images or certified copies at the Wa... |
| Washington | NC | walled (Courthouse Computer Systems ) | 1996 | unknown | ? | no | no | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check); for any deed befo... |
| Watauga | NC | free index (Courthouse Computer Systems ) | 1889 | unknown | yes | no | no | Free online covers the index back to 1889; a person must visit the Boone office for record books 2046-2405 (no... |
| Wayne | NC | free index (Cott Systems eSearch v4 (cou) |  | unknown | yes | no | no | Free index via guest access; a person may need the Goldsboro office for deed images if online viewing is paid,... |
| Wilkes | NC | free index (Logan Systems Public Records) | 1927 | yes | ? | no | no | For deeds before 1970 (Book 511 and earlier) or index entries before 1927 a person must use the Wilkesboro reg... |
| Wilson | NC | free index (Cott Systems eSearch (county) | 1974 | unknown | yes | no | no | Sign in as guest for the index; for pre-1974 deeds or images not yet scanned, a person must use the Wilson reg... |
| Yadkin | NC | free index (Logan Systems remote access ) | 1791 | yes | ? | no | no | Free online covers the chain back past 1907; a person is needed only for illegible pages, certified copies, or... |
| Yancey | NC | free index ('The Lookup' land record sea) | 1833 | unknown | yes | no | yes | Free online covers index books back to 1833; anything older, missing years, or illegible pages need the Burnsv... |
| alamance | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | unknown | no |  |
| alexander | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | unknown | no |  |
| alleghany | NC | walled (Courthouse Computer Systems ) |  | unknown | ? | unknown | no | A person opens alleghanync.courthousecomputersystems.com in a normal browser (passes the Cloudflare check) to ... |
| anson | NC | free index (Logan Systems 'Remote Access) | 1749 | yes | ? | no | no |  |
| ashe | NC | free index (Logan Systems 'Remote Access) | 1799 | yes | yes | no | no | Taxpayer and tax-bill status need a person on qPublic in a browser; NC OneMap gives owner and deed book/page f... |
| avery | NC | free index ('The Lookup' (search.averyde) | 1912 | yes | yes | no | no |  |
| beaufort | NC | free index (Courthouse Computer Systems ) | 1981 | unknown | yes | no | no |  |
| bertie | NC | free index ('The Lookup' (search.bertied) |  | yes | yes | no | no | Tax-bill status needs a person on the webtaxpay site (human check); deeds, legal and chain are free in the Loo... |
| bladen | NC | free index (Logan Systems 'Remote Access) | 1739 | yes | yes | no | no | Tax bill status and taxpayer need a person to call or visit the Bladen tax office (online tax site not reached... |
| brunswick | NC | walled (Internet Technologies Inc. () |  | unknown | yes | unknown | no | A person passes the math question on the Inttek public login to pull deeds and the chain; legal description an... |
| buncombe | NC | free index (Cott eSearch v4 / Aumentum L) |  | no | yes | unknown | yes | Deed images (needed for the full legal description) are pay-per-view on the ROD site; a person buys the few pa... |
| burke | NC | free index (Courthouse Computer Systems ) |  | yes | ? | no | yes |  |
| cabarrus | NC | free index (Logan Systems Public Records) | 1938 | yes | yes | no | no |  |
| caldwell | NC | free index (Courthouse Computer Systems ) | 1841 | yes | ? | no | no | Tax bill status needs a person on the Caldwell tax site in a browser. |
| camden | NC | free index (Courthouse Computer Systems ) | 1999 | unknown | ? | no | no | Deeds before May 1999 need a person at the Camden ROD (or a paid abstractor); tax bill status needs a call to ... |
| carteret | NC | free index (Aumentum Recorder web access) |  | yes | yes | no | no |  |
| caswell | NC | free index (Courthouse Computer Systems ) |  | unknown | ? | no | no |  |
| catawba | NC | free index (Logan Systems Public Records) | 1842 | yes | yes | no | no |  |
| chatham | NC | free index (Logan Systems Public Records) | 1771 | yes | yes | no | no | Taxpayer and bill status need a person on the Chatham tax site in a browser (county site blocks scripts); NC O... |
| cherokee | NC | free index (Logan Systems 'Remote Access) | 1993 | yes | yes | no | no | Tax bill status needs a call to the Cherokee County NC tax office or a person on the GIS viewer; pre-1993 gran... |
| chowan | NC | free index (Courthouse Computer Systems ) |  | unknown | yes | no | no |  |
| clay | NC | free index ('The Lookup' (search.claydee) | 1870 | yes | yes | no | yes |  |
| cleveland | NC | free index (Courthouse Computer Systems ) |  | yes | ? | no | yes | Taxpayer/bill status needs a person on the Avalon tax site (reCAPTCHA). Current deed book/page is not in any f... |
| columbus | NC | free index ('The Lookup' (search.columbu) | 1800 | yes | yes | unknown | no | Tax-due status needs a person on webtaxpay (human check) or a call to the Columbus tax office. |
| craven | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | unknown | no | Deeds, legal descriptions and chain need a person to pass the reCAPTCHA on the CCHS site (or visit the New Ber... |
| cumberland | NC | free index (Logan Systems Public Records) | 1741 | yes | yes | no | no |  |
| currituck | NC | free index (Courthouse Computer Systems ) |  | unknown | yes | no | no |  |
| dare | NC | free index (Courthouse Computer Systems ) | 1976 | yes | ? | no | no | Deeds before 1976 need the books at the Manteo ROD or an abstractor. |
| davidson | NC | free index (Business Information Service) | 1984 | unknown | yes | no | no | For deeds before 1984 (or images, if not free on the public site) a person uses the paid davidsonportal.com su... |
| davie | NC | free index (Logan Systems 'Remote Access) | 1837 | yes | yes | no | no |  |
| duplin | NC | free index (Courthouse Computer Systems ) |  | unknown | ? | no | no |  |
| durham | NC | free index (Tyler Technologies Recorder ) |  | unknown | ? | no | no | Taxpayer and bill status need a person on the Durham tax site (lookup not located by script). |
| edgecombe | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | no | no |  |
| forsyth | NC | free index (Business Information Service) |  | yes | ? | no | no |  |
| franklin | NC | free index (Courthouse Computer Systems ) | 1950 | yes | yes | no | no | If the CCHS window is challenged, a person opens the Franklin ROD site in a browser, accepts the disclaimer, s... |
| gaston | NC | walled (Courthouse Computer Systems ) |  | no | yes | unknown | partial | A person opens gastonnc.courthousecomputersystems.com in a browser to search the index; the deed image (for th... |
| gates | NC | free index (Courthouse Computer Systems ) |  | yes | yes | no | no | Index and images reachable free in a browser; records before the pre-1995 index start need the office or an ab... |
| graham | NC | free index (Cott Systems eSearch v4 (cot) | 1872 | unknown | yes | no | no | If images need purchase, a person or the attorney's account buys the most recent deed copy from the Cott cart ... |
| granville | NC | free index (Cott Systems eSearch v4 (cou) |  | unknown | yes | no | no | If deed images are not free, a person buys the most recent deed copy (or the attorney uses his account); pre-1... |
| greene | NC | walled (Courthouse Computer Systems ) |  | unknown | ? | no | no | A person opens the Greene ROD site, ticks the reCAPTCHA, then searches by name and views the deed; the legal d... |
| guilford | NC | free index (County-hosted PHP name searc) |  | unknown | yes | no | no | A person accepts the Guilford ROD disclaimer in a browser and searches by name; if images are not free, the at... |
| halifax | NC | free index (Cott Systems eSearch (cottho) |  | unknown | yes | unknown | no | Tax bills and assessor cards need a person in a browser (Cloudflare-gated tax site, qPublic terms bar automati... |
| harnett | NC | walled (Courthouse Computer Systems ) | 1973 | yes | yes | no | no | A person ticks the reCAPTCHA on the Harnett ROD site, searches by name, and views/prints deed images free; pre... |
| haywood | NC | free index ('The Lookup' PHP index (sear) | 1986 | yes | yes | no | yes | Pre-1986 chains need the office's older books or an abstractor; if image links turn out to cost, a person orde... |
| henderson | NC | free index (Courthouse Computer Systems ) | 1966 | yes | yes | no | yes | Deeds before book 200 / 1966 need the office's older books or an abstractor; otherwise free online. |
| hertford | NC | free index (Courthouse Computer Systems ) | 1901 | yes | yes | no | no | Little needed: index and images from 1901 are free online; pre-1901 chains go to an abstractor. |
| hoke | NC | unclear (Logan Systems Public Records) |  | unknown | ? | unknown | no | A person must open hokencrod.org in a browser to find the vesting deed (no free legal or deed reference exists... |
| hyde | NC | free index (Courthouse Computer Systems ) | 1991 | yes | yes | no | no | The legal description must come from the deed image (statewide GIS legal is mostly blank for Hyde); pre-1991 i... |
| iredell | NC | walled (Courthouse Computer Systems ) |  | unknown | yes | unknown | no | A person passes the CAPTCHA on the new Iredell ROD site and also checks the old Cott guest site for pre-1964 r... |
| jackson | NC | free index (Cott Systems eSearch v4 (cou) | 1851 | unknown | yes | no | no | Index from 1851 is free as guest; if images need purchase, the attorney's account or a copy order supplies the... |
| johnston | NC | free index (Tyler EagleWeb (erec.johnsto) |  | unknown | ? | no | no | A person acknowledges the EagleWeb disclaimer as guest and reads the deed; the legal description must come fro... |
| jones | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | unknown | no | Pre-1978 deeds need the CCHS site when it is up, otherwise the office or an abstractor; the legal must come fr... |
| lee | NC | unclear (Logan Systems Public Records) |  | unknown | yes | unknown | no | A person opens leencrod.org in a browser to search the index and view the deed; the assessor's legal fields an... |
| lenoir | NC | free index (Cott Systems eSearch (county) |  | unknown | yes | unknown | no | Guest index search is free; if images cost, the attorney's account or a copy order supplies the deed text. |
| lincoln | NC | free index (Courthouse Computer Systems ) |  | yes | yes | no | yes | Rarely needed: index and deed images are free; very old books are imaged but the verified index start is uncle... |
| macon | NC | free index (Logan Systems 'The Lookup' P) |  | unknown | yes | no | no | A person accepts the Macon disclaimer and searches by name; if images cost or are missing, a copy order or the... |
| madison | NC | free index (Courthouse Computer Systems ) | 1987 | yes | yes | no | partial | Pre-1987 links in the chain require reading the imaged deed books by book/page (free) or an abstractor when th... |
| martin | NC | free index (County 'Register Of Deeds Re) |  | yes | ? | no | no | A person acknowledges the Martin disclaimer in a browser and reads the deed for the legal (no free GIS legal f... |
| mcdowell | NC | free index (Logan Systems 'The Lookup' P) |  | yes | yes | no | yes | Rarely needed; older gaps go to an abstractor. |
| mecklenburg | NC | free index (Aumentum Recorder web access) | 1763 | no | yes | no | partial | For deeds after Feb 1990 the image is a paid copy: the attorney's account or a copy order supplies the legal; ... |
| mitchell | NC | free index (Logan Systems 'The Lookup' P) |  | yes | yes | no | yes | Legal description must be read off the free deed image (no GIS legal text for Mitchell). |
| montgomery | NC | free index (Courthouse Computer Systems ) | 1792 | yes | yes | no | no | Little needed: free index from 1792 and free images; a person only steps in when a book is missing from the im... |
| moore | NC | free index (Aumentum Recorder web access) |  | yes | yes | no | no | For pre-1988 chain links a person checks the index books at the office (online back-fill incomplete) or uses a... |
| nash | NC | free index (Cott Systems eSearch v4 (cot) |  | unknown | yes | unknown | no | Guest index search is free; if images cost, the attorney's account or a copy order supplies the deed text. |
| new-hanover | NC | free index ('Online Record System' PHP n) |  | yes | yes | no | no | Little needed: index, property-description search and images appear free; older chains beyond the online index... |
| northampton | NC | free index (County 'Register Of Deeds Re) | 1741 | yes | yes | no | no | Pre-1991 chain links are found by browsing scanned index books online (free) or by an abstractor; the tax bill... |
| onslow | NC | free index (Cott Systems eSearch (deeds.) |  | unknown | yes | unknown | no | If deed images need the paid subscription, the attorney's account or a copy order supplies the deed; GIS legal... |
| orange | NC | free index (Courthouse Computer Systems ) | 1932 | yes | yes | no | no | Pre-1932 chain links need the office's older books or an abstractor. |
| abbeville | SC | free index (Online Record System (NameSe) | 1978 | yes | ? | no | partial | Index and deed PDFs are free online from about 1978, so a person is needed only for older chain links (abstrac... |
| aiken | SC | walled () |  | unknown | yes | unknown | no | The ROD search sits behind the county's Cloudflare wall, so a person must open aikencountysc.gov/RMC in a brow... |
| allendale | SC | unclear () |  | unknown | ? | unknown | no | No online deed index: a person or the abstractor must search the deed books at the Allendale Clerk of Court; t... |
| anderson | SC | free index (ACPASS (county-built CGI) fo) | 1948 | yes | yes | no | partial | Deeds recorded since 2/21/2026 must be looked up by a person in the new Ingenuity system (its terms forbid aut... |
| bamberg | SC | unclear (Avenu Insights / Neumo Recor) |  | unknown | ? | unknown | no | Deed searches go through the Avenu/Neumo portal, which we leave to a person in a browser (or the abstractor) b... |
| barnwell | SC | free index (Online Record System (NameSe) |  | yes | yes | no | partial | ROD index and deed PDFs are free; a person is needed only for chain links older than the online index (start y... |
| beaufort | SC | walled (NewVision Systems BrowserVie) |  | unknown | yes | unknown | no | The ROD search is behind a CAPTCHA on every search, so a person must run deed-chain searches in a browser (or ... |
| berkeley | SC | free index (Online Record System (NameSe) | 1983 | yes | no | no | partial | Deed index and PDFs are free online from about 1983; a person or abstractor is needed for older chain links, a... |
| calhoun | SC | walled (TitleSearcher (paid subscrip) |  | no | ? | unknown | no | Deeds are only on paid TitleSearcher or at the Clerk of Court office, so the attorney's abstractor (or a subsc... |
| charleston | SC | free index (Charleston County ROD docume) | 1978 | yes | yes | no | no | Index from 1978 and images from the mid-1990s are free; earlier chain links need the Archival Room (partly onl... |
| cherokee | SC | unclear (Avenu Insights / Neumo Recor) | 1995 | yes | ? | yes | no | The deed index (1995+) and free images (2002+) are on the Avenu portal, whose terms forbid automation, so a pe... |
| chester | SC | unclear (Avenu Insights / Neumo Recor) |  | unknown | ? | unknown | no | Deed searches must be done by a person in the Avenu portal (or by the abstractor); the county site itself bloc... |
| chesterfield | SC | unclear (Avenu Insights / Neumo Recor) |  | unknown | ? | unknown | no | Deed searches must be done by a person in the Avenu portal (or by the abstractor); parcel details come from th... |
| clarendon | SC | walled (Harris AcclaimWeb) |  | yes | ? | unknown | no | A person can search the free AcclaimWeb index and view deed images back to 1988 in a browser (automated reads ... |
| colleton | SC | free index (Online Record System (NameSe) | 1986 | yes | no | no | partial | Index and deed PDFs are free online from about 1986; older links need the abstractor; probate is office-only. |
| darlington | SC | walled (Cott Systems RECORDhub) |  | unknown | yes | yes | no | The deed index is on Cott RECORDhub (account/subscription, no automation allowed), so the chain must come from... |
| dillon | SC | unclear (Avenu Insights / Neumo Recor) |  | unknown | ? | unknown | no | Deed searches by a person in the Avenu portal or by the abstractor; parcel facts from the WTH viewer by hand; ... |
| dorchester | SC | free index (Online Record System (NameSe) |  | yes | no | no | partial | Deed index and PDFs are free on the Online Record System; older links (start year not published) need the abst... |
| edgefield | SC | unclear (Avenu Insights / Neumo Recor) |  | unknown | ? | unknown | no | Deed searches by a person in the Avenu portal (digital from 1996) and by the abstractor before that; parcel ca... |
| fairfield | SC | unclear (Avenu Insights / Neumo Recor) |  | unknown | ? | unknown | no | Deed searches by a person in the Avenu portal or by the abstractor; parcel card on Beacon in a normal browser;... |
| florence | SC | free index (Online Record System (NameSe) | 1889 | yes | no | no | partial | Free typed index, deed PDFs and scanned index books back to 1889 cover most chains; a person is needed to page... |
| georgetown | SC | free index (Online Record System (NameSe) | 1977 | yes | yes | no | partial | Index from 1977 and deed PDFs are free; earlier links need the abstractor; probate and current tax bills need ... |
| greenville | SC | free index (GovOS (Kofile) Cloud Search ) | 1787 | unknown | yes | unknown | no | Everything back to 1787 is indexed and imaged online, so a person can pull the full chain in a browser; probat... |
| greenwood | SC | free index (County-built 'Greenwood Coun) | 1897 | yes | yes | no | no | Free route covers deed chain, legal description and plats back to 1897; a person (or the abstractor) is only n... |
| hampton | SC | walled (Neumo Records Management (fo) | 2000 | yes | ? | unknown | no | A person signs up for a free Neumo account (or the abstractor searches) to read the ROD index and images from ... |
| horry | SC | free index (Harris AcclaimWeb) |  | unknown | yes | no | no | Deed chain and legal description are free after the disclaimer click; a person may need to buy a copy if a cle... |
| jasper | SC | walled (Courthouse Computer Systems ) | 2007 | unknown | ? | no | no | A person must open the CCHS ROD site and pass its CAPTCHA by hand (or the abstractor searches); records before... |
| kershaw | SC | walled (Neumo Records Management (fo) | 1990 | unknown | ? | yes | no | A person (not a script: the site's terms forbid robots) logs in with a free Neumo account to read the 1990+ in... |
| lancaster | SC | free index ('Online Record System' (same) |  | unknown | yes | no | no | Index, deed chain and lot/subdivision legal are free after a plain disclaimer GET; a person is needed only if ... |
| laurens | SC | free index ('Online Record System' (Name) |  | yes | yes | no | partial | Free route gives deed chain, property-description legal and images; a person is needed to confirm/check probat... |
| lee | SC | walled (Neumo Records Management (fo) | 1902 | no | ? | yes | no | ROD search needs a paid subscription ($5/day) and the terms forbid robots, so a person (or the attorney's abst... |
| lexington | SC | walled (Kofile/GovOS CountyFusion) | 1984 | yes | yes | unknown | no | GIS gives the legal and current deed book/page free; walking the deed chain needs a person with a free CountyF... |
| marion | SC | none/unreachable () |  | no | ? | unknown | no | Everything is manual: a person or the abstractor searches the deed books at the Clerk of Court in Marion, prob... |
| marlboro | SC | free index (Cott Systems eSearch (cottho) |  | no | ? | unknown | no | The deed index can be read free as a guest; a person (or the abstractor) must buy copies of the deeds to read ... |
| newberry | SC | walled (Neumo Records Management (fo) | 1983 | no | ? | unknown | no | A person with a free Neumo account reads the 1983+ index; deed images (2003+) cost $5/day, so the legal descri... |
| oconee | SC | free index (Kofile PublicSearch (now bra) | 1955 | unknown | yes | unknown | partial | GIS gives legal and current deed book/page free and the index is open; a person may need to buy clean copies, ... |
| orangeburg | SC | walled (County-run 'Register Of Deed) |  | yes | ? | no | no | A person with a free ROD account reads the index and PDF deeds; probate needs a call or visit; GIS was down to... |
| pickens | SC | free index (Harris AcclaimWeb (county pa) |  | unknown | yes | no | partial | Index, TMS search and legal descriptions are free after the disclaimer click; a person may need to buy images,... |
| richland | SC | walled (Richland County 'Online Data) |  | no | ? | unknown | no | ROD and probate documents need a paid county subscription (the attorney's or abstractor's); a person can use t... |
| saluda | SC | none/unreachable (Cott Systems RecordHub) |  | unknown | yes | unknown | no | GIS gives legal, current deed and the prior deed reference free; deeper chain needs a person on Cott RecordHub... |
| spartanburg | SC | free index (Logan Systems 'The Lookup' () | 1785 | yes | yes | no | partial | Free route covers deed chain, legal and plats; a person browses the scanned old index books (1785-1992) by han... |
| sumter | SC | free index (Kofile/GovOS CountyFusion) |  | unknown | yes | unknown | no | GIS gives legal and current deed book/page free; walking the chain is a guest-click CountyFusion search (a per... |
| union | SC | free index (Cott Systems RecordRoom) |  | unknown | yes | unknown | partial | Index and deed chain are free as a guest; a person may need to buy images to read full legal descriptions; pro... |
| williamsburg | SC | walled (Neumo Records Management (fo) |  | no | ? | yes | no | A person registers (free) to search the index, but terms forbid robots and every deed image costs $1/page, so ... |
| york | SC | free index ('Online Record System' (Name) |  | unknown | yes | no | yes | Free route covers deed chain and property legal; a person may need to buy images, read probate documents (paid... |
