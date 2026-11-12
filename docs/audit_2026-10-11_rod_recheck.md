# ROD access re-check, 2026-10-11

One plain GET per county ROD url from docs/county_records/county_records_matrix.json, ordinary Chrome User-Agent header, no TLS impersonation, redirects followed, nothing clicked or solved, at least 2.5 s between requests to one host. A landing-page GET cannot see gates that sit behind a search click (CAPTCHA on search, paid images), so "changed" is only marked where today's response contradicts the recorded status.

Checked: 146 counties (144 with a url). Changed: 2.

| county | state | url | old status | new status | changed? | notes |
|---|---|---|---|---|---|---|
| alamance | NC | https://cotthosting.com/NCALAMANCEEXTERNAL/User/Login.aspx | disclaimer_click | 200 sign-in page with guest button | no |  |
| alexander | NC | https://cotthosting.com/ncalexander/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| alleghany | NC | https://alleghanync.courthousecomputersystems.com/ | blocked | 403 Cloudflare challenge | no |  |
| anson | NC | https://www.ansonncrod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| ashe | NC | https://www.ashencrod.org/opening.asp | disclaimer_click | 200 disclaimer/landing page | no |  |
| avery | NC | https://search.averydeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| beaufort | NC | https://us5.courthousecomputersystems.com/BeaufortNC2/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| bertie | NC | https://search.bertiedeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| bladen | NC | https://www.bladenncrod.org/opening.asp | disclaimer_click | 200 disclaimer/landing page | no |  |
| brunswick | NC | https://brunswick-live.inttek.net/ | captcha | 200 page loads, no challenge | no |  |
| buncombe | NC | https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| burke | NC | https://us5.courthousecomputersystems.com/burkenc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| cabarrus | NC | https://www.cabarrusncrod.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| caldwell | NC | https://us3.courthousecomputersystems.com/CaldwellNC/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| camden | NC | https://us5.courthousecomputersystems.com/CamdenNC/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| carteret | NC | https://deeds.carteretcountync.gov/ | disclaimer_click | 200 page with login form | no |  |
| caswell | NC | https://us5.courthousecomputersystems.com/caswellnc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| catawba | NC | https://www.catawbarod.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| chatham | NC | https://www.chathamncrod.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| cherokee | NC | https://www.cherokeencrod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| chowan | NC | https://us4.courthousecomputersystems.com/ChowanNC/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| clay | NC | https://search.claydeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| cleveland | NC | https://us5.courthousecomputersystems.com/clevelandnc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| columbus | NC | https://search.columbusdeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| craven | NC | https://us5.courthousecomputersystems.com/CravenNC2/ | captcha | 200 CAPTCHA widget on page | no |  |
| cumberland | NC | https://www.ccrodinternet.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| currituck | NC | https://us3.courthousecomputersystems.com/currituckNC/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| dare | NC | https://us5.courthousecomputersystems.com/DareNC/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| davidson | NC | https://www.davidsondeeds.com/davidsonNameSearch.php | disclaimer_click | 200 disclaimer/landing page | no |  |
| davie | NC | https://www.daviencrod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| duplin | NC | https://courthousecomputersystems.com/DuplinCountyROD/?page_id=200 | disclaimer_click | 200 disclaimer/landing page | no |  |
| durham | NC | https://rodweb.dconc.gov/web/ | disclaimer_click | 200 CAPTCHA widget on page | no |  |
| edgecombe | NC | https://cotthosting.com/ncedgecombeexternal/User/Login.aspx | disclaimer_click | 200 sign-in page with guest button | no |  |
| forsyth | NC | https://forsythdeeds.com/disclaimer.php | disclaimer_click | 200 disclaimer/landing page | no |  |
| franklin | NC | https://us4.courthousecomputersystems.com/franklinnc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| gaston | NC | https://gastonnc.courthousecomputersystems.com/ | blocked | 403 Cloudflare challenge | no | cf-mitigated: challenge, cType interactive. Still blocked to a script. |
| gates | NC | https://us5.courthousecomputersystems.com/gatesnc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| graham | NC | https://cotthosting.com/ncgraham/LandRecords/protected/v4/SrchName.aspx | open | 200 disclaimer/landing page | no |  |
| granville | NC | http://www.granvillecountydeeds.org/External/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| greene | NC | https://greenenc.courthousecomputersystems.com/ | captcha | 200 CAPTCHA widget on page | no |  |
| guilford | NC | https://rdlxweb.guilfordcountync.gov/guilfordNameSearch.php | disclaimer_click | 200 disclaimer/landing page | no |  |
| halifax | NC | https://cotthosting.com/NCHALIFAXEXTERNAL | disclaimer_click | 200 sign-in page with guest button | no |  |
| harnett | NC | https://us6.courthousecomputersystems.com/HarnettNC/ | captcha | 200 CAPTCHA widget on page | no |  |
| haywood | NC | https://search.haywooddeeds.com/index.php?Accept=Accept | disclaimer_click | 200 page loads, no challenge | no |  |
| henderson | NC | https://us4.courthousecomputersystems.com/hendersonnc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| hertford | NC | https://us4.courthousecomputersystems.com/hertfordnc/ | open | 200 disclaimer/landing page | no |  |
| hoke | NC | https://www.hokencrod.org/ | none | 200 page loads, no challenge | no |  |
| hyde | NC | https://us4.courthousecomputersystems.com/Hydenc/ | open | 200 disclaimer/landing page | no |  |
| iredell | NC | https://iredellnc.courthousecomputersystems.com/ | captcha | 200 CAPTCHA widget on page | no |  |
| jackson | NC | http://deeds.jacksonnc.org/External/LandRecords/protected/v4/SrchName.aspx | open | 200 disclaimer/landing page | no |  |
| johnston | NC | https://erec.johnstonnc.com/recorder/web/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| jones | NC | https://cotthosting.com/ncjones/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| lee | NC | https://www.leencrod.org/ | none | 200 page loads, no challenge | no |  |
| lenoir | NC | http://cottweb.co.lenoir.nc.us/external/LandRecords/protected/SrchQuickName.aspx | disclaimer_click | 200 sign-in page with guest button | no |  |
| lincoln | NC | https://us4.courthousecomputersystems.com/LincolnNCNW/realestatesearch.asp | disclaimer_click | 200 page with login form | no |  |
| macon | NC | https://search.macondeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| madison | NC | https://us4.courthousecomputersystems.com/MadisonNCNW/realestatesearch.asp | disclaimer_click | 200 page with login form | no |  |
| martin | NC | https://www.martinrod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| mcdowell | NC | https://search.mcdowelldeeds.com/index.php | disclaimer_click | 200 disclaimer/landing page | no |  |
| mecklenburg | NC | https://meckrod.manatron.com/ | disclaimer_click | 200 page with login form | no |  |
| mitchell | NC | https://search.mitchelldeeds.com/index.php | disclaimer_click | 200 disclaimer/landing page | no |  |
| montgomery | NC | https://us4.courthousecomputersystems.com/montgomerync/ | open | 200 disclaimer/landing page | no |  |
| moore | NC | https://rod.moorecountync.gov/ | blocked | 200 page with login form | no | Landing 200 as on 10-07; the recorded block is on the disclaimer postback, not re-tested. |
| nash | NC | https://cotthosting.com/NCNashExternal/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| new-hanover | NC | https://search.newhanoverdeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 disclaimer/landing page | no |  |
| northampton | NC | https://northamptonrod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| onslow | NC | https://deeds.onslowcountync.gov/External/User/Login.aspx | disclaimer_click | 200 sign-in page with guest button | no |  |
| orange | NC | https://rod.orangecountync.gov/orangenc/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| Pamlico | NC | https://cotthosting.com/ncpamlicoexternal/LandRecords/protected/v4/SrchName.aspx | open | 200 disclaimer/landing page | no |  |
| Pasquotank | NC | https://us4.courthousecomputersystems.com/pasquotankncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Pender | NC | https://us5.courthousecomputersystems.com/penderncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Perquimans | NC | https://us5.courthousecomputersystems.com/Perquimansncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Person | NC | https://us5.courthousecomputersystems.com/personncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Pitt | NC | https://regdeeds.pittcountync.gov/external/ | disclaimer_click | 200 sign-in page with guest button | no |  |
| Polk | NC | https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| Randolph | NC | https://us5.courthousecomputersystems.com/RandolphNC2 | captcha | 200 CAPTCHA widget on page | no |  |
| Richmond | NC | https://us5.courthousecomputersystems.com/richmondncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Robeson | NC | https://robeson.bislandrecords.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| Rockingham | NC | https://us5.courthousecomputersystems.com/RockinghamNCNW/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Rowan | NC | https://rod.rowancountync.gov/external/ | disclaimer_click | 200 sign-in page with guest button | yes | Wall card said script gets a challenge (10-07, 10-09); today a clean sign-in page. Likely intermittent. |
| Rutherford | NC | https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4/SrchName.aspx | disclaimer_click | 200 sign-in page with guest button | no |  |
| Sampson | NC | https://www.sampsonrod.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| Scotland | NC | https://cotthosting.com/ncscotlandexternal | disclaimer_click | 200 sign-in page with guest button | no |  |
| Stanly | NC | http://72.15.246.186/stanlyncnw/application.asp | open | 200 page loads, no challenge | no |  |
| Stokes | NC | https://us6.courthousecomputersystems.com/StokesNC/ | captcha | 200 CAPTCHA widget on page | no |  |
| Surry | NC | http://rod.surryinfo.net/surryncnwpub/application.asp?resize=true | disclaimer_click | 200 page loads, no challenge | no |  |
| Swain | NC | https://www.swaincorod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| Transylvania | NC | https://search.transylvaniadeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| Tyrrell | NC | https://us4.courthousecomputersystems.com/Tyrrellncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Union | NC | https://www.unionconcrod.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| Vance | NC | https://www.vancencrod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| Wake | NC | https://rodrecords.wake.gov/web/ | captcha | 200 CAPTCHA widget on page | no |  |
| Warren | NC | https://warrenrod.org/opening.asp | disclaimer_click | 200 disclaimer/landing page | no |  |
| Washington | NC | https://us4.courthousecomputersystems.com/Washingtonncnw/application.asp?resize=true | blocked | 403 Cloudflare challenge | no |  |
| Watauga | NC | https://us3.courthousecomputersystems.com/WataugaNC2 | disclaimer_click | 200 disclaimer/landing page | no |  |
| Wayne | NC | http://rod.waynegov.com/External/LandRecords/protected/v4/SrchName.aspx | open | 200 page loads, no challenge | no |  |
| Wilkes | NC | https://www.wilkesncrod.org/ | disclaimer_click | 200 page loads, no challenge | no |  |
| Wilson | NC | http://rod.wilson-co.com/External/LandRecords/protected/v4/SrchName.aspx | disclaimer_click | 200 sign-in page with guest button | no |  |
| Yadkin | NC | https://www.yadkincorod.org/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| Yancey | NC | https://search.yanceydeeds.com/ | disclaimer_click | 200 disclaimer/landing page | no |  |
| abbeville | SC | https://search.abbevilledeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| aiken | SC | https://www.aikencountysc.gov/RMC/ | blocked | 403 Attention Required! | Cloudflare | no |  |
| allendale | SC |  | none | no url on file | no |  |
| anderson | SC | https://acpass.andersoncountysc.org/deed.cgi | open | 200 disclaimer/landing page | no |  |
| bamberg | SC | https://bambergsc.avenuinsights.com/ | none | 200 page loads, no challenge | no |  |
| barnwell | SC | https://barnwelldeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| beaufort | SC | https://rod.beaufortcountysc.gov/searchng/ | captcha | TLS cert expired | yes | Certificate expired; script cannot connect. Still CAPTCHA behind it. |
| berkeley | SC | https://search.berkeleydeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| calhoun | SC | https://www.titlesearcher.com/index.php | payment | 200 page with login form | no |  |
| charleston | SC | https://www.charlestoncounty.gov/departments/rod/rodsearch.php | captcha | 200 disclaimer/landing page | no |  |
| cherokee | SC | https://cherokeesc.avenuinsights.com/ | none | 200 page loads, no challenge | no |  |
| chester | SC | https://chestersc.avenuinsights.com/ | none | 200 page loads, no challenge | no |  |
| chesterfield | SC | https://chesterfieldsc.avenuinsights.com/ | none | 200 page loads, no challenge | no |  |
| clarendon | SC | https://acclaimprod.clarendoncountygov.org/acclaimweb | blocked | 403 Cloudflare challenge | no |  |
| colleton | SC | https://search.colletondeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| darlington | SC | https://recordhub.cottsystems.com/DarlingtonSC/Portal/ | login | 200 page loads, no challenge | no |  |
| dillon | SC | https://dillonsc.avenuinsights.com/ | none | 200 page loads, no challenge | no |  |
| dorchester | SC | https://search.dorchesterdeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| edgefield | SC | https://edgefieldsc.avenuinsights.com/ | none | 200 page loads, no challenge | no |  |
| fairfield | SC | https://fairfieldsc.avenuinsights.com/Home/index.html | none | 200 page loads, no challenge | no |  |
| florence | SC | https://search.florencedeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| georgetown | SC | https://georgetowndeeds.com/NameSearch.php?Accept=Accept | disclaimer_click | 200 page with login form | no |  |
| greenville | SC | https://www.greenvillecounty.org/rod/searchrecords.aspx | open | 200 disclaimer/landing page | no |  |
| greenwood | SC | https://www.greenwoodsc.gov/docsearchrod/ | disclaimer_click | 200 page loads, no challenge | no |  |
| hampton | SC | https://hamptonsc.avenuinsights.com/Public/HamptonSC/ | login | 200 page with login form | no |  |
| horry | SC | https://acclaimweb.horrycounty.org/AcclaimWeb | disclaimer_click | 200 sign-in page with guest button | no |  |
| jasper | SC | https://us6.courthousecomputersystems.com/jasperSC | captcha | 200 CAPTCHA widget on page | no |  |
| kershaw | SC | https://kershawsc.avenuinsights.com/Public/KershawSC/ | login | 200 page with login form | no |  |
| lancaster | SC | https://lancasterscdeeds.com/NameSearch.php | disclaimer_click | 200 page with login form | no |  |
| laurens | SC | https://search.laurensdeeds.com/NameSearch.php | disclaimer_click | 200 page with login form | no |  |
| lee | SC | https://leesc.avenuinsights.com/Public/LeeSC/ | payment | 200 page with login form | no |  |
| lexington | SC | https://countyfusion14.govos.com/countyweb/loginDisplay.action?countyname=LexingtonSC | login | 200 sign-in page with guest button | no |  |
| marion | SC |  | unreachable | no url on file | no |  |
| marlboro | SC | http://www.cotthosting.com/scmarlboro/LandRecords/protected/SrchQuickName.aspx | open | 200 page loads, no challenge | no |  |
| mccormick | SC | https://mccormickcountysc.org/departments/clerk_of_court.php | unreachable | 200 disclaimer/landing page | no | URL is a county info page; no online ROD index exists (unchanged). |
| newberry | SC | https://newberrysc.avenuinsights.com/Public/NewberrySC/ | login | 200 page with login form | no |  |
| oconee | SC | https://oconee.sc.publicsearch.us/ | open | 200 disclaimer/landing page | no |  |
| orangeburg | SC | https://www.orangeburgscrod.org/ | login | 200 page with login form | no |  |
| pickens | SC | https://www.pickensscrod.us/AcclaimWeb | disclaimer_click | 200 page with login form | no |  |
| richland | SC | https://www.richlandcountysc.gov/Online-Services/Online-Data-Services | payment | 403 Access Denied | no | Akamai Access Denied, same as 10-07. |
| saluda | SC | https://recordhub.cottsystems.com/SaludaSC/ | unreachable | connect timeout | no | Vendor redirects to plain http on port 80, which times out. |
| spartanburg | SC | https://search.spartanburgdeeds.com/index.php | disclaimer_click | 200 disclaimer/landing page | no |  |
| sumter | SC | https://countyfusion2.kofiletech.us/countyweb/loginDisplay.action?countyname=SumterSC | disclaimer_click | 200 sign-in page with guest button | no |  |
| union | SC | https://recordroom.cottsystems.com/unionsc/guest/Search/records | open | 200 page loads, no challenge | no |  |
| williamsburg | SC | https://williamsburgsc.avenuinsights.com/Public/WilliamsburgSC/ | login | 200 page with login form | no |  |
| york | SC | https://search.yorkdeeds.com/NameSearch.php | disclaimer_click | 200 page with login form | no |  |
