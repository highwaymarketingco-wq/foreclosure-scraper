"""quiet_title.layups: the five rules and the ranking, on made-up rows and ledger entries."""
from datetime import date

from foreclosure_scraper.quiet_title.layups import LayupScan, iter_candidates_text, tax_finding

TODAY = date(2026, 10, 7)


def entry(dby, verifier="tax_lien_buncombe", verdict="confirmed", pin=None):
    return {"latest": {"verifier": verifier, "verdict": verdict,
                       "evidence": {"delinquent_by_year": dby, "latest_levy_year": 2026, "pin": pin}}}


def row(pin, owner="ANNA MARIE TESTER (HEIRS)", addr=None, signals=(), qa=(), kind="land", lt="tax_lien", **raw):
    return {"county": "Buncombe", "state": "NC", "parcel_id": pin, "owner_name": owner, "street_address": addr,
            "property_kind": kind, "listing_type": lt,
            "raw": {"signal_stack": {"signals": list(signals)}, "qa_flags": list(qa), **raw}}


def scan(ledger, probate=None, court=None, strict=False):
    def key(r):
        return r["parcel_id"][:12]
    return LayupScan(county="Buncombe", state="NC", today=TODAY,
                     find_tax=lambda r: ledger.get(key(r)),
                     find_probate=lambda r: (probate or {}).get(key(r)),
                     find_confirmed_court=lambda r: (court or {}).get(key(r), []), strict=strict)


def test_tax_finding_counts_completed_years_only():
    assert tax_finding(entry({"2025": 10.0, "2024": 20.0}), TODAY).ok
    one = tax_finding(entry({"2025": 10.0, "2026": 50.0}), TODAY)          # 2026 is not late yet
    assert not one.ok and one.years == [2025]
    assert not tax_finding(entry({"2025": 1, "2024": 1}, verifier="tax_lien_ptscloud"), TODAY).ok
    assert not tax_finding(entry({"2025": 1, "2024": 1}, verdict="stale"), TODAY).ok
    assert not tax_finding(None, TODAY).ok


def test_rules_and_ranking():
    led = {"1111-11-1111": entry({"2025": 300.0, "2024": 200.0}),
           "2222-22-2222": entry({"2025": 50.0, "2024": 40.0}),
           "3333-33-3333": entry({"2025": 10.0, "2024": 10.0}),         # foreclosure signal
           "4444-44-4444": entry({"2025": 10.0, "2024": 10.0}),         # no heirs wording
           "5555-55-5555": entry({"2025": 10.0, "2024": 10.0}),         # fused key
           "6666-66-6666": entry({"2025": 10.0, "2024": 10.0}),         # two addresses on one PIN
           "7777-77-7777": entry({"2025": 10.0, "2024": 10.0}),         # confirmed bankruptcy verdict
           "8888-88-8888": entry({"2025": 10.0, "2024": 10.0}, pin="999999999900000")}   # ledger holds another PIN
    s = scan(led, probate={"1111-11-1111": "confirmed"}, court={"7777-77-7777": ["bankruptcy_stay"]})
    rows = [row("1111-11-1111-00000"), row("2222-22-2222-00000", qa=["owner_record_mismatch"]),
            row("3333-33-3333-00000", signals=["tax_lien", "lis_pendens"]),
            row("4444-44-4444-00000", owner="TESTER JOHN Q"),
            row("5555-55-5555-00000", qa=["gis_row_shared"]),
            row("6666-66-6666-00000", addr="10 EXAMPLE RD"), row("6666-66-6666-00000", addr="12 EXAMPLE RD"),
            row("7777-77-7777-00000"), row("8888-88-8888-00000"),
            {"county": "Elsewhere", "state": "NC", "parcel_id": "1111-11-1111-00000"}]
    for r in rows:
        s.add_row(r)
    c = s.candidates()
    # heirs claim confirmed ranks first even with the larger balance; then the smaller balance
    assert [x.pin for x in c] == ["111111111100000", "222222222200000"]
    assert c[1].cautions == ["owner_record_mismatch"]
    lines = list(iter_candidates_text(c, {"111111111100000": "no house number on EXAMPLE RD (situs, county layer)"}))
    assert lines[0].startswith(" 1. PIN 111111111100000 | no house number on EXAMPLE RD")
    assert "probate_heir ledger: confirmed" in lines[1] and "caution: owner_record_mismatch" in lines[4]
    assert "(address on the board" in lines[3]
    assert s.rows_seen == 10 and s.in_county == 9


def test_strict_mode_excludes_owner_record_mismatch_and_condo_units():
    led = {"2222-22-2222": entry({"2025": 50.0, "2024": 40.0}), "9999-99-9999": entry({"2025": 5.0, "2024": 5.0})}
    s = scan(led, strict=True)
    s.add_row(row("2222-22-2222-00000", qa=["owner_record_mismatch"]))
    s.add_row(row("9999-99-9999-C0001"))
    assert s.candidates() == []
    assert any(k.startswith("R5") for k in s.dropped)


def test_a_foreclosure_row_blocks_every_row_of_the_pin():
    led = {"1111-11-1111": entry({"2025": 300.0, "2024": 200.0})}
    s = scan(led)
    s.add_row(row("1111-11-1111-00000"))
    s.add_row(row("1111-11-1111-00000", lt="foreclosure_sale"))
    assert s.candidates() == []
