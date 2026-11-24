# SCRAPER TEST RESULTS - 2026-11-24 Evening

## 🎯 CURRENT STATUS (PARTIAL - Test still running)

**Scrapers tested so far:** ~40-50 of 292  
**Working scrapers:** 28  
**Total listings:** 119,146

Test script running in background (proc_6b52147f1e8c), saves progress to `docs/scraper_test_results.json` after each batch.

---

## 🔥 TOP 10 WORKING SCRAPERS

| Rank | Scraper | Listings | Type |
|------|---------|----------|------|
| 1 | StateContamination | 53,827 | Environmental |
| 2 | GastonVacant | 21,751 | Code Violations |
| 3 | AlbemarleObserverTaxLists | 9,333 | Delinquent Tax |
| 4 | BuncombeElderly | 4,363 | Tax Relief |
| 5 | EpaFrsSites | 3,803 | Environmental |
| 6 | CumberlandDelinquentTax | 3,755 | Delinquent Tax |
| 7 | CharlotteOpenData | 2,737 | Multiple |
| 8 | BuncombeDelinquentTax | 1,181 | Delinquent Tax |
| 9 | GuilfordTaxForeclosures | 969 | Tax Foreclosure |
| 10 | AshevilleSTRPermits | 673 | STR Permits |

---

## ✅ ALL WORKING SCRAPERS (28)

1. StateContamination: 53,827
2. GastonVacant: 21,751
3. AlbemarleObserverTaxLists: 9,333
4. BuncombeElderly: 4,363
5. EpaFrsSites: 3,803
6. CumberlandDelinquentTax: 3,755
7. CharlotteOpenData: 2,737
8. BuncombeDelinquentTax: 1,181
9. GuilfordTaxForeclosures: 969
10. AshevilleSTRPermits: 673
11. AshevilleHeleneDamage: 652
12. RaleighStructureFires: 385
13. HendersonCodeViolations: 176
14. GastonTaxForeclosures: 81
15. CountySitemapWalker: 72
16. HendersonvilleVacantStructures: 51
17. KinstonDemolition: 45
18. AshevilleMinHousing: 29
19. ClarendonForeclosures: 25
20. AshevilleCodeEnforcement: 23
21. HendersonTaxForeclosure: 15
22. DarlingtonForeclosures: 10
23. FlorenceForeclosures: 8
24. CalhounForeclosures: 6
25. HaywoodTaxForeclosures: 3
26. BambergSheriff: 1
27. BarnwellSheriff: 1
28. AndersonSheriff: 1

---

## 📊 CATEGORIES WORKING

### Environmental (57,630 listings)
- State Contamination: 53,827
- EPA FRS Sites: 3,803

### Code Violations / Vacant Properties (22,676 listings)
- Gaston Vacant: 21,751
- Henderson Code Violations: 176
- Hendersonville Vacant: 51
- Asheville Min Housing: 29
- Asheville Code: 23
- Kinston Demolition: 45
- Johnston Tax: 514 (pending batch)
- Lincoln Code: 63 (pending batch)

### Delinquent Tax (14,269 listings)
- Albemarle Observer Tax Lists: 9,333
- Cumberland Delinquent Tax: 3,755
- Buncombe Delinquent Tax: 1,181

### Tax Foreclosures (1,068 listings)
- Guilford Tax Foreclosures: 969
- Gaston Tax Foreclosures: 81
- Henderson Tax Foreclosure: 15
- Haywood Tax Foreclosures: 3

### Storm/Disaster Damage (652 listings)
- Asheville Helene Damage: 652

### Sheriff Sales (12 listings)
- Bamberg, Barnwell, Anderson: 1 each
- Clarendon, Darlington, Florence, Calhoun: 6-25 each

### Open Data (3,194 listings)
- Charlotte Open Data: 2,737
- Raleigh Structure Fires: 385
- County Sitemap Walker: 72

---

## 🔄 NEXT STEPS

1. **Wait for full test completion** (~250 more scrapers to test)
2. **Fix broken scrapers** from error log
3. **Retest with longer timeouts** (some may have timed out)
4. **Claude: NC eCourts on VM** (52K rows potential)
5. **Apply fixes** to Cloudflare-blocked scrapers

---

## 📈 PROJECTION

If 28 working scrapers out of ~50 tested = 56% success rate  
Projected for all 292 scrapers: ~163 working, ~300K+ listings

**Actual results pending full test completion.**
