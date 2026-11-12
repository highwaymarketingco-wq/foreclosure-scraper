import asyncio, sys, json, re
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper.http_client import client

LAYER = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"

addrs = [
    "44 Haw Creek Cir", "80 Webb Cove Rd", "7 Brushwood Rd", "1 Pensacola Hts",
    "4 Heather Way", "140 Old Leicester Rd", "3 Windy Hollow Rd", "8 Hemlock Rd",
    "7 Woodbury Rd", "117 Lookout Rd", "35 McKinney Rd", "47 Timberwood Dr",
    "205 Linden St", "3 View St", "22 Waters Rd",
]

def split_addr(a):
    m = re.match(r"^\s*(\d+)\s+(.*)$", a)
    if not m:
        return None, a
    num, rest = m.groups()
    street = re.split(r"\b(ST|AVE|RD|DR|LN|CT|BLVD|HWY|WAY|PL|CIR|TER|HTS|LOOP)\b", rest.upper(), maxsplit=1)[0].strip()
    return num, street or rest.upper()

async def main():
    async with client(timeout=20) as c:
        for a in addrs:
            num, street = split_addr(a)
            where = f"HouseNumber='{num}' AND UPPER(streetname) LIKE '%{street}%'"
            r = await c.get(LAYER, params={"where": where, "outFields": "pinnum,Address,CityName,SalePrice,DeedDate,TotalMarketValue,owner", "returnGeometry":"false","f":"json","resultRecordCount":"5"})
            d = r.json()
            feats = d.get("features", [])
            print(a, "->", where, "-> n:", len(feats))
            for f in feats:
                print("   ", f["attributes"])

asyncio.run(main())
