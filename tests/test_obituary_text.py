"""obituary_text: survivor lists and probate-notice representatives.

Every name here is made up. The phrasing is modelled on real obituaries and estate notices from
Western NC and Upstate SC papers and funeral-home pages (semicolon lists, shared surnames,
spouses in parentheses, 'and husband Bob', nicknames, all-caps notices, c/o attorney addresses).
"""
from __future__ import annotations

from foreclosure_scraper.obituary_text import (
    clean_text,
    parse_obituary_lede,
    parse_probate_notice,
    parse_survivors,
    relation_of,
    tidy_name,
)


def _names(res, relation=None):
    return [p["name"] for p in res["survivors"] if relation is None or p["relation"] == relation]


def _rel(res, name):
    for p in res["survivors"]:
        if p["name"] == name:
            return p["relation"]
    return None


# --------------------------------------------------------------------------- survivors

def test_classic_semicolon_list():
    t = ("Orvel Quimby Tandry, 84, of Weaverville, passed away Monday, September 28, 2026. "
         "He is survived by his wife of 61 years, Lunetta Brask Tandry; two sons, Corwin Tandry (Delphine) "
         "of Asheville and Bratt Tandry of Marion; a daughter, Wynnie Tandry Holcomb and husband Rudd of "
         "Candler; a sister, Fennimore Tandry Ashby; seven grandchildren; and three great-grandchildren. "
         "A funeral service will be held at 2 PM Thursday.")
    r = parse_survivors(t)
    assert _rel(r, "Lunetta Brask Tandry") == "spouse"
    assert _rel(r, "Corwin Tandry") == "son"
    assert _rel(r, "Bratt Tandry") == "son"
    assert _rel(r, "Wynnie Tandry Holcomb") == "daughter"
    assert _rel(r, "Fennimore Tandry Ashby") == "sister"
    # the daughter's husband is an in-law, kept apart, never a survivor of the decedent's own blood
    inlaw = [p for p in r["survivors"] if p["relation"] == "in_law"]
    assert [p["name"] for p in inlaw] == ["Rudd"]
    assert inlaw[0]["spouse_of"] == "Wynnie Tandry Holcomb"
    # the son's spouse in parentheses is recorded as a note, not as a person
    corwin = next(p for p in r["survivors"] if p["name"] == "Corwin Tandry")
    assert corwin["parenthetical"] == ["Delphine"]
    unnamed = {(u["relation"], u["count"]) for u in r["unnamed"]}
    assert ("grandchild", 7) in unnamed and ("great_grandchild", 3) in unnamed
    # nothing from the service sentence leaks in
    assert all("Thursday" not in p["name"] for p in r["survivors"])


def test_shared_surname_and_comma_list_without_semicolons():
    t = ("She is survived by her husband Delmar Fitch, sons Arlo and Benning Fitch, daughters "
         "Cressida Moyer and Dovie Lark, and a brother, Eamon Pruett. She was preceded in death by "
         "her parents and a sister, Gwendolyn Pruett Salter.")
    r = parse_survivors(t)
    assert _rel(r, "Delmar Fitch") == "spouse"
    assert _rel(r, "Arlo Fitch") == "son"
    arlo = next(p for p in r["survivors"] if p["name"] == "Arlo Fitch")
    assert arlo["surname_from_list"] is True
    assert _rel(r, "Benning Fitch") == "son"
    assert _rel(r, "Cressida Moyer") == "daughter"
    assert _rel(r, "Dovie Lark") == "daughter"
    assert _rel(r, "Eamon Pruett") == "brother"
    assert "Gwendolyn Pruett Salter" not in _names(r)
    assert [p["name"] for p in r["predeceased"]] == ["Gwendolyn Pruett Salter"]


def test_compound_relation_son_and_daughter_in_law():
    t = ("Survivors include a son and daughter-in-law, Haskell and Imogene Varner of Forest City; "
         "a grandson, Jasper Varner; and numerous nieces and nephews.")
    r = parse_survivors(t)
    assert _rel(r, "Haskell Varner") == "son"
    assert _rel(r, "Imogene Varner") == "daughter_in_law"
    assert _rel(r, "Jasper Varner") == "grandchild"
    assert any(u["relation"] == "niece" and u["count"] is None for u in r["unnamed"])


def test_left_to_cherish_with_nicknames_titles_and_ages():
    t = ('Left to cherish her memory are her children, Rev. Kellan "Buddy" Ostrom (Marla), '
         "Dr. Lyra Ostrom-Paine, and Mabry Ostrom Jr.; her brother, Nolan Quist (82); and a host of "
         "cousins and friends. Visitation will be from 6 to 8 PM.")
    r = parse_survivors(t)
    assert _rel(r, "Kellan Ostrom") == "child"
    kel = next(p for p in r["survivors"] if p["name"] == "Kellan Ostrom")
    assert kel["nickname"] == "Buddy"
    assert _rel(r, "Lyra Ostrom-Paine") == "child"
    assert _rel(r, "Mabry Ostrom Jr.") == "child"
    nolan = next(p for p in r["survivors"] if p["name"] == "Nolan Quist")
    assert nolan["relation"] == "brother" and nolan["age"] == 82
    assert all(p["name"] not in ("Visitation",) for p in r["survivors"])


def test_spouse_given_name_only_is_marked_surname_not_stated():
    t = "He leaves behind his loving wife of 52 years, Petra; and two daughters, Quinlan Rhee and Sable Rhee."
    r = parse_survivors(t)
    petra = next(p for p in r["survivors"] if p["relation"] == "spouse")
    assert petra["name"] == "Petra" and petra["surname_stated"] is False
    assert _names(r, "daughter") == ["Quinlan Rhee", "Sable Rhee"]


def test_also_surviving_second_sentence_and_all_caps():
    t = ("JOHNSTON TREVETT ABERNATHY, 77, OF SHELBY, DIED OCTOBER 2, 2026. HE IS SURVIVED BY HIS "
         "DAUGHTER, URSULA ABERNATHY KEMP OF KINGS MOUNTAIN. ALSO SURVIVING ARE TWO BROTHERS, "
         "VAUGHN ABERNATHY AND WYLIE ABERNATHY, BOTH OF SHELBY.")
    r = parse_survivors(t)
    assert _rel(r, "Ursula Abernathy Kemp") == "daughter"
    assert _rel(r, "Vaughn Abernathy") == "brother"
    assert _rel(r, "Wylie Abernathy") == "brother"


def test_survivors_colon_and_stepchildren_and_companion():
    t = ("Survivors: stepson, Xander Bolt; stepdaughter, Yara Bolt Cain; companion of 20 years, "
         "Zelda Moss; half-brother, Abel Druid. Memorials may be made to the church.")
    r = parse_survivors(t)
    assert _rel(r, "Xander Bolt") == "stepchild"
    assert _rel(r, "Yara Bolt Cain") == "stepchild"
    assert _rel(r, "Zelda Moss") == "companion"
    assert _rel(r, "Abel Druid") == "half_sibling"


def test_no_survivor_sentence_gives_nothing():
    t = "Bertram Cole, 90, of Arden, died Sunday. A graveside service will be held Friday."
    r = parse_survivors(t)
    assert r["survivors"] == [] and r["clauses"] == 0


def test_html_input_and_entities():
    t = ("<p>She is survived by her son, Cyrus O&#39;Dell&nbsp;of Brevard;</p><p>a granddaughter, "
         "Dahlia McKinnon.</p><p>In lieu of flowers, donations may be made.</p>")
    r = parse_survivors(t)
    assert _rel(r, "Cyrus O'Dell") == "son"
    assert _rel(r, "Dahlia McKinnon") == "grandchild"


def test_friends_and_places_are_not_people():
    t = ("He is survived by many friends at First Baptist Church of Marion and his dog, Rex; "
         "a niece, Ember Fallow of Greenville, SC.")
    r = parse_survivors(t)
    assert _names(r) == ["Ember Fallow"]


def test_relation_of_and_tidy_name():
    assert relation_of("two great-grandsons") == "great_grandchild"
    assert relation_of("his loving wife") == "spouse"
    assert relation_of("sisters-in-law") == "sister_in_law"
    assert tidy_name("Mrs. Faye Gentry of Lake Lure, N.C.")[0] == "Faye Gentry"
    assert tidy_name("numerous nieces")[0] is None
    assert tidy_name("of Asheville")[0] is None


def test_lede():
    t = ("Harlan Vickery Pope, 87, of Hendersonville, passed away on September 30, 2026, at his home. "
         "He was born on March 2, 1939, in Polk County.")
    lede = parse_obituary_lede(t)
    assert lede["age"] == 87
    assert lede["residence"] == "Hendersonville"
    assert lede["death_date_text"] == "September 30, 2026"
    assert lede["birth_date_text"] == "March 2, 1939"


def test_clean_text():
    assert clean_text("<b>A</b>&amp;<i>B</i>\n\n C") == "A & B C"


# --------------------------------------------------------------------------- probate notices

def test_nc_notice_to_creditors_signature_with_address():
    t = ("NOTICE TO CREDITORS. Having qualified as Executrix of the Estate of Oswin Larkspur Tate, "
         "deceased, late of Buncombe County, North Carolina, this is to notify all persons, firms and "
         "corporations having claims against the estate to present them to the undersigned on or "
         "before January 5, 2027, or this notice will be pleaded in bar of their recovery. All persons "
         "indebted to the estate will please make immediate payment. This the 2nd day of October, 2026. "
         "Philippa Tate Rowan, Executrix, 41 Quarry Hollow Road, Fairview, NC 28730.")
    r = parse_probate_notice(t)
    assert r["decedent"] == "Oswin Larkspur Tate"
    assert r["representatives"] == [{"name": "Philippa Tate Rowan", "role": "executrix",
                                     "address": "41 Quarry Hollow Road, Fairview, NC 28730"}]


def test_nc_notice_undersigned_and_c_o_attorney():
    t = ("ESTATE NOTICE. The undersigned, Quentin Ashford Vale, having qualified as Administrator of "
         "the Estate of Rosalind Vale, deceased, of Henderson County, hereby notifies all persons "
         "having claims... This 25th day of September, 2026. Quentin Ashford Vale, Administrator, "
         "c/o Sorrell Law PLLC, 200 Church Street, Hendersonville, NC 28792.")
    r = parse_probate_notice(t)
    assert r["decedent"] == "Rosalind Vale"
    assert len(r["representatives"]) == 1
    rep = r["representatives"][0]
    assert rep["name"] == "Quentin Ashford Vale" and rep["role"] == "administrator"
    assert rep["address"].startswith("c/o Sorrell Law PLLC")
    assert "attorney" in rep["address_note"]


def test_sc_labelled_notice_without_address_keeps_none():
    t = ("NOTICE TO CREDITORS OF ESTATES. Estate: Theron Mabry Wick Date of Death: 06/19/2026 "
         "Case Number: 2026ES1100303 Personal Representative: Ulla Wick Danner")
    r = parse_probate_notice(t)
    assert r["decedent"] == "Theron Mabry Wick"
    assert r["case_number"] == "2026ES1100303"
    assert r["date_of_death"] == "06/19/2026"
    assert r["representatives"][0]["name"] == "Ulla Wick Danner"
    assert "address" not in r["representatives"][0]


def test_sc_labelled_notice_multiline_address():
    t = ("NOTICE TO CREDITORS\nEstate: Velma Juno Crisp\nDate of Death: May 10, 2026\n"
         "Case Number: 2026ES3900446\nPersonal Representative:\nWalt Crisp\nAddress: 18 Pine Knob Dr, "
         "Easley, SC 29640\n")
    r = parse_probate_notice(t)
    assert r["decedent"] == "Velma Juno Crisp"
    rep = r["representatives"][0]
    assert rep["name"] == "Walt Crisp"
    assert rep["address"] == "18 Pine Knob Dr, Easley, SC 29640"


def test_co_executors_and_no_creditor_language():
    t = ("Having qualified as Co-Executors of the Estate of Xavia Plum, deceased... "
         "Yancey Plum, Co-Executor, 9 Elm St, Shelby, NC 28150. Zora Plum Hart, Co-Executor, "
         "PO Box 12, Lawndale, NC 28090.")
    r = parse_probate_notice(t)
    names = [(x["name"], x.get("address")) for x in r["representatives"]]
    assert ("Yancey Plum", "9 Elm St, Shelby, NC 28150") in names
    assert ("Zora Plum Hart", "PO Box 12, Lawndale, NC 28090") in names
    assert parse_probate_notice("City council approved the budget.")["representatives"] == []
