# CAPTCHA & Walled Sources Work Plan — 2026-11-11

Generated from gap_list_2026-11-11.csv "Hermes lane" bucket (635 cells, 917K est_rows).

## Priority tiers

### Tier 1: Existing scrapers, needs CAPTCHA solver wired (quick wins)

| Source | Counties | Est rows | CAPTCHA type | Fix |
|---|---|---|---|---|
| `nc_rod_captcha` | Wake, Iredell, Brunswick | 12,945 + 2,841 + 9,225 = 25,011 | reCAPTCHA v2 | Already wired (`ec2e3151`), needs live test |
| `lexington_probate` | Lexington SC | 2,417 | reCAPTCHA v2 | Already built (`ba316c2c`), needs live test |
| `sc_sos_entity` | Statewide SC (sos_dissolution column) | 5,136 + 3,846 + 1,995 = 10,977 | reCAPTCHA v2 | Already wired (`6b733f99`), production enabled |

**Subtotal: ~38K rows, all should work, just need VM live tests**

### Tier 2: Existing scrapers, needs Playwright rewrite (medium effort)

| Source | Counties | Est rows | Issue | Fix |
|---|---|---|---|---|
| `sc_rod_walled` (Jasper) | Jasper SC | 1,669 | Uses nodriver, incompatible with `solve_recaptcha_v2` | Convert `_fetch_jasper` from nodriver → Playwright |

**Subtotal: ~1.7K rows, 1 rewrite**

### Tier 3: Tyler probate portal — needs A/B WAF test (blocked, Claude's lane per handoff)

| Source | Counties | Est rows | Issue | Fix |
|---|---|---|---|---|
| `nc_ecourts_estates` | Beaufort, Duplin, Hyde, Hoke, Orange, Harnett, Union, Madison, Perquimans, Bertie, Washington, Granville, Wayne, Moore, +20 more | ~30K across 34 NC counties | AWS-WAF 20-puzzle cap | A/B test vs 2026-11-09 working session (Claude has the working fingerprint/timing/headers) |

**Subtotal: ~30K rows, needs Claude**

### Tier 4: New ROD/tax scrapers needed (high effort, high value)

**reCAPTCHA v2 tax portals (can reuse audio solver):**
| County | Portal | Est rows | Columns |
|---|---|---|---|
| Lincoln NC | www.lincolncountytax.com | 18,841 | multi_year_delinquent_tax, rollback_exposure + 2 more |
| Charleston SC ROD | Charleston County ROD | 11,212 | atty_rod_lien_checked, liens |
| Randolph NC ROD | CCS public web | 6,043 | atty_rod_lien_checked, liens |
| Harnett NC ROD | CCS LRSearch MVC | 4,226 | atty_rod_lien_checked, liens |
| McDowell NC tax | www.bttaxpayerportal.com | 3,526 | multi_year_delinquent_tax, rollback_exposure |
| Iredell NC ROD | CCS LRSearch | 2,841 | atty_rod_lien_checked, liens |
| Bertie NC tax | bertie.webtaxpay.com | 2,173 | multi_year_delinquent_tax, rollback_exposure, two_year_delinquent, 2 more |
| Burke NC tax | lrcpwa.ncptscloud.com | 2,019 | multi_year_delinquent_tax |
| Craven NC ROD | CCS LRSearch us5 | 1,608 | liens |
| Cleveland NC tax | www.clevelandcountytaxes.com | 1,606 | multi_year_delinquent_tax, rollback_exposure |
| Caldwell NC tax | www.caldwellcountynctax.com | 1,054 | multi_year_delinquent_tax, repeat_tax_loss, tax_aging_surfaced, two_year_delinquent |
| Georgetown SC tax | georgetowncountysctax.com | 997 | multi_year_delinquent_tax, rollback_exposure, tax_aging_surfaced |

**Subtotal: ~56K rows, 12 new scrapers needed**

**ncnotices.com Column papers (heir/quiet-title, different CAPTCHA pattern):**
| Counties | Est rows | Note |
|---|---|---|
| Lincoln, Brunswick, Harnett, Hoke, Hyde, Orange, Pender, Person, Surry, Jones, Carteret, Edgecombe | ~50K | "no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled" — may need different approach than ROD reCAPTCHA |

### Tier 5: Login-required (need credentials or account setup)

**ACPASS (Anderson SC) — credentials exist:**
| Source | Est rows | Columns |
|---|---|---|
| Anderson SC tax | 3,388 | multi_year_delinquent_tax |

**Other login-required (no credentials):**
| County | Platform | Est rows | Note |
|---|---|---|---|
| Orangeburg SC | County ROD Remote Access | 4,586 × 3 = 13,758 | Need account |
| Lexington SC | Kofile/GovOS CountyFusion | 3,303 × 2 = 6,606 | Need account |
| Williamsburg SC | Neumo Records Management | 2,956 × 3 = 8,868 | Need account |
| Darlington SC | Cott Systems RECORDhub | 2,927 × 2 = 5,854 | Need account |
| Kershaw SC | Neumo Records Management | 2,064 × 3 = 6,192 | Need account |
| Newberry SC | Neumo Records Management | 1,142 × 2 = 2,284 | Need account |

**Subtotal: ~47K rows, 7 sources, only Anderson has credentials**

### Tier 6: HUD USPS vacancy (statewide, likely not free)

| States | Est rows | Note |
|---|---|---|
| NC + SC statewide | ~200K+ | "HUD USPS vacancy data needs a registered login" — probably paid/restricted access, may be out of scope per free-only policy |

---

## Execution plan

1. **Quick wins (Tier 1):** Test existing CAPTCHA scrapers on VM (nc_rod_captcha, lexington_probate, sc_sos_entity)
2. **Jasper rewrite (Tier 2):** Convert sc_rod_walled Jasper from nodriver → Playwright
3. **New tax/ROD scrapers (Tier 4):** Build in order of row count (Lincoln tax 18K, Charleston ROD 11K, Randolph ROD 6K, ...)
4. **Anderson login (Tier 5):** Enable ACPASS tax scraper if not already working
5. **Defer to Claude:** nc_ecourts_estates A/B test, HUD USPS research, login-required sources without credentials

---

*Generated 2026-11-11 by Hermes Agent*
