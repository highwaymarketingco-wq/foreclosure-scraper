#!/usr/bin/env python
"""Build a FREE manual-skip-trace worksheet: every foreclosure owner with the data we already
have (mailing address, absentee flag, the 160 free voter phones) + click-ready search links
(TruePeopleSearch / FastPeopleSearch) so a HUMAN can rapidly look up phone/email. We generate
links only — no scraping. Output: docs/skiptrace_worksheet.csv (open in Google Sheets/Excel).
"""
import csv, json, re
from pathlib import Path
from urllib.parse import quote
DOCS = Path(__file__).resolve().parent.parent / "docs"

def first_last(owner):
    o = re.sub(r"[^A-Za-z ]", " ", owner or "").strip()
    o = re.sub(r"\s+", " ", o)
    t = o.split(" ")
    if len(t) < 2: return o
    # deed records are usually LAST FIRST -> reorder to First Last for the search
    return f"{t[1].title()} {t[0].title()}"

def main():
    d = json.loads((DOCS / "listings.json").read_text())
    rows = []
    for x in d:
        on = x.get("owner_name")
        if not on: continue
        raw = x.get("raw") or {}
        fl = first_last(on)
        city = x.get("city") or ""; st = x.get("state") or ""
        op = (raw.get("owner_phone") or {}).get("phone", "")
        om = raw.get("owner_mailing") or {}
        mail = om.get("mailing_address") or om.get("address") or ""
        tps = f"https://www.truepeoplesearch.com/results?name={quote(fl)}&citystatezip={quote(city+', '+st)}" if city else f"https://www.truepeoplesearch.com/results?name={quote(fl)}"
        fps = f"https://www.fastpeoplesearch.com/name/{quote(fl.lower().replace(' ','-'))}_{quote(city.lower().replace(' ','-'))}-{st.lower()}" if city else ""
        rows.append({
            "owner_name": on, "search_name": fl, "property_address": x.get("street_address") or "",
            "city": city, "county": x.get("county") or "", "state": st,
            "owner_mailing_address": mail, "absentee": "Y" if om.get("absentee") else "",
            "phone_we_have_free": op, "tier": (raw.get("distress_stack") or {}).get("tier",""),
            "truepeoplesearch_link": tps, "fastpeoplesearch_link": fps,
            "PHONE_found": "", "EMAIL_found": "", "notes": "",
        })
    # sort HOT first, then those we DON'T already have a phone for
    rank = {"HOT":0,"WARM":1,"COLD":2}
    rows.sort(key=lambda r: (rank.get(r["tier"],3), bool(r["phone_we_have_free"])))
    out = DOCS / "skiptrace_worksheet.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    have = sum(1 for r in rows if r["phone_we_have_free"])
    print(f"wrote {out} | {len(rows)} owners | already have free phone: {have} | need manual lookup: {len(rows)-have}")
main()
