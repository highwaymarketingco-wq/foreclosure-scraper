"""Deal analysis: all-in cost, max bid, feasibility — the 'is it worth it' layer.

The point the operator made: a low bid on a salvage Porsche is not a cheap car
once you add the repair. These pin the rules that turn a bid into an all-in
number and a go/no-go.
"""
from __future__ import annotations

from porsche_scraper.deal_analysis import analyze, build_comps, _model_of
from porsche_scraper.models import Listing


def _l(**kw) -> Listing:
    return Listing(source=kw.pop("source", "copart"),
                   source_url=kw.pop("url", "https://x/1"), **kw)


def test_model_parsed_from_title_when_field_blank():
    li = _l(title="2014 Porsche Cayenne Platinum", year=2014)
    assert _model_of(li) == "cayenne"
    assert _model_of(_l(title="2007 Porsche 911 Carrera S", year=2007)) == "911"


def test_salvage_bid_is_not_a_cheap_car():
    # A $125 bid on a salvage 911 worth $67k is NOT a $125 car — recon dominates.
    li = _l(source="copart", seller_type="salvage_auction",
            title="2015 Porsche 911 Carrera", model="911", year=2015,
            current_bid_usd=125, title_status="unknown")
    d = analyze(li, comps={}, target=50000)
    assert d["est_recon"] > 15000            # real Porsche repair, not $0
    assert d["all_in"] > 20000               # bid was tiny, recon dominates
    assert d["max_bid_target"] < 30000       # can't bid it up to $50k


def test_copart_unknown_title_treated_as_salvage():
    li = _l(source="copart", seller_type="salvage_auction",
            title="2016 Porsche Cayman", model="cayman", year=2016,
            current_bid_usd=15, title_status="unknown")
    d = analyze(li, comps={}, target=50000)
    # unknown-on-Copart must NOT be priced like a clean retail car (2% recon)
    assert d["est_recon"] > d["est_clean_value"] * 0.2


def test_over_all_in_cap_is_not_feasible():
    # High bid on a salvage car pushes all-in over the cap -> flagged.
    li = _l(source="copart", seller_type="salvage_auction",
            title="2018 Porsche Cayman S", model="cayman", year=2018,
            current_bid_usd=40000, title_status="salvage")
    d = analyze(li, comps={}, target=50000)
    assert d["feasible"] is False
    assert d["all_in"] > 50000


def test_flood_is_a_write_off():
    li = _l(source="copart", title="2016 Porsche 911", model="911", year=2016,
            current_bid_usd=500, title_status="flood")
    d = analyze(li, comps={}, target=50000)
    assert d["feasible"] is False
    assert "flood" in (d.get("disqualified") or d["note"]).lower()


def test_clean_dealer_car_feasible_without_flip_margin():
    li = _l(source="carvana", seller_type="dealer",
            title="2019 Porsche Cayenne", model="cayenne", year=2019,
            price_usd=33000, title_status="unknown")
    d = analyze(li, comps={}, target=50000)
    assert d["feasible"] is True             # under budget, road-ready
    assert d["est_recon"] < 2000             # clean car, minimal recon


def test_max_bid_keeps_all_in_under_target():
    li = _l(source="copart", seller_type="salvage_auction",
            title="2016 Porsche Boxster", model="boxster", year=2016,
            current_bid_usd=100, title_status="salvage")
    d = analyze(li, comps={}, target=50000)
    # bidding exactly max_bid_target should land all-in at/under the cap
    fee = d["max_bid_target"] * 0.12 + 1000
    assert d["max_bid_target"] + fee + d["est_recon"] <= 50000 + 50  # rounding


# --- damage-based recon (Copart/IAA real damage, not a flat guess) ----------

def _dmg(primary, secondary="", retail="", bid=20000):
    li = _l(source="copart", seller_type="salvage_auction",
            title="2018 Porsche Cayman", model="cayman", year=2018,
            current_bid_usd=bid, title_status="unknown")
    li.raw = {"damage": {"primary": primary, "secondary": secondary,
                         "retail": retail}}
    return li


def test_minor_damage_costs_far_less_than_all_over():
    minor = analyze(_dmg("MINOR DENT/SCRATCHES", retail="50000"), {}, 50000)
    allover = analyze(_dmg("ALL OVER", retail="50000"), {}, 50000)
    assert minor["est_recon"] < allover["est_recon"] / 3   # not the same repair
    assert minor["damage"] == "Minor Dent/Scratches"


def test_copart_retail_used_as_clean_value():
    d = analyze(_dmg("FRONT END", retail="70347"), {}, 50000)
    assert d["est_clean_value"] == 70347         # Copart's own ACV, not a comp


def test_flood_damage_reads_as_near_writeoff():
    d = analyze(_dmg("WATER/FLOOD DAMAGE", retail="50000"), {}, 50000)
    assert d["est_recon"] > 50000 * 0.6


def test_secondary_damage_adds_cost():
    one = analyze(_dmg("FRONT END", retail="50000"), {}, 50000)["est_recon"]
    two = analyze(_dmg("FRONT END", "REAR END", retail="50000"), {}, 50000)["est_recon"]
    assert two > one


def test_damage_shows_in_note():
    d = analyze(_dmg("SIDE", "FRONT END", retail="50000"), {}, 50000)
    assert "Side" in d["note"] and "Front End" in d["note"]


# --- hard disqualifiers: salvage Taycan / flood / frame ---------------------

def test_salvage_taycan_disqualified():
    li = _l(source="copart", seller_type="salvage_auction",
            title="2021 Porsche Taycan 4S", model="taycan", year=2021,
            current_bid_usd=15000, title_status="salvage")
    d = analyze(li, {}, 50000)
    assert d["feasible"] is False
    assert "Taycan" in d["disqualified"]


def test_clean_dealer_taycan_is_fine():
    # A non-salvage Taycan from a dealer is NOT disqualified.
    li = _l(source="carvana", seller_type="dealer", title="2021 Porsche Taycan",
            model="taycan", year=2021, price_usd=48000, title_status="unknown")
    d = analyze(li, {}, 50000)
    assert d.get("disqualified") is None
    assert d["feasible"] is True


def test_flood_damage_disqualified():
    li = _l(source="copart", seller_type="salvage_auction",
            title="2016 Porsche 911", model="911", year=2016,
            current_bid_usd=5000, title_status="unknown")
    li.raw = {"damage": {"primary": "WATER/FLOOD", "retail": "60000"}}
    d = analyze(li, {}, 50000)
    assert d["feasible"] is False and "flood" in d["disqualified"].lower()


def test_frame_damage_disqualified():
    li = _l(source="copart", seller_type="salvage_auction",
            title="2016 Porsche Cayman", model="cayman", year=2016,
            current_bid_usd=5000, title_status="unknown")
    li.raw = {"damage": {"primary": "ROLLOVER", "retail": "45000"}}
    d = analyze(li, {}, 50000)
    assert d["feasible"] is False and "frame" in d["disqualified"].lower()
