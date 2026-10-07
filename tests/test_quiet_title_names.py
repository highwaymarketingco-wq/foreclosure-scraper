"""quiet_title.names and quiet_title.taxyears: pure rules. Every name here is made up."""
from datetime import date

from foreclosure_scraper.quiet_title.names import (death_fit, is_entity, name_compat, parse_indexed, parse_roll,
                                                   roll_markers, roll_tokens, split_owners)
from foreclosure_scraper.quiet_title.taxyears import current_levy_year, is_completed, split_years


def test_roll_markers_heirs_and_estate():
    assert roll_markers("ANNA MARIE TESTER (HEIRS)") == ["HEIRS"]
    assert roll_markers("TESTER JOHN Q HEIRS") == ["HEIRS"]
    assert roll_markers("ESTATE OF JOHN Q TESTER") == ["ESTATE OF"]
    assert roll_markers("TESTER JOHN Q ESTATE") == ["ESTATE"]
    assert roll_markers("TESTER JOHN Q") == []
    assert roll_markers(None) == []


def test_parse_indexed_register_form():
    p = parse_indexed("TESTER, ANNA MARIE")
    assert (p.last, p.first, p.middles) == ("TESTER", "ANNA", ["MARIE"])
    assert p.indexed() == "TESTER, ANNA MARIE"
    assert parse_indexed("SAMPLE HOLDINGS LLC") is None
    assert parse_indexed("TESTER") is None


def test_parse_indexed_slash_annotations():
    d = parse_indexed("TESTER, JOHN Q/ DECD")
    assert d.deceased and d.middles == ["Q"] and d.role is None
    j = parse_indexed("TESTER, JOHN QUINCY/ JR")
    assert j.suffix == "JR" and j.middles == ["QUINCY"]
    e = parse_indexed("TESTER, MAY B/ EXRX")
    assert e.role == "EXRX" and e.middles == ["B"]


def test_parse_indexed_old_dash_form_reads_surname_first():
    p = parse_indexed("-SAMPLE ROY W")
    assert (p.last, p.given) == ("SAMPLE", ["ROY", "W"])
    assert parse_indexed("-----") is None


def test_parse_roll_both_orders():
    a = parse_roll("TESTER ANNA MARIE", "last_first")
    assert (a.last, a.given) == ("TESTER", ["ANNA", "MARIE"])
    b = parse_roll("ANNA MARIE TESTER (HEIRS)", "first_last")
    assert (b.last, b.given) == ("TESTER", ["ANNA", "MARIE"])
    assert roll_tokens("ANNA MARIE TESTER (HEIRS)") == {"ANNA", "MARIE", "TESTER"}


def test_split_owners_and_entities():
    assert split_owners("TESTER JOHN;TESTER MAY") == ["TESTER JOHN", "TESTER MAY"]
    assert is_entity("SAMPLE PROPERTIES LLC") and not is_entity("TESTER JOHN Q")


def test_death_fit_only_when_given_middle_and_surname_agree():
    rec = parse_indexed("TESTER, ANNA MARIE")
    assert death_fit(rec, parse_indexed("TESTER, ANNA MARIE")).verdict == "fit"
    diff = death_fit(rec, parse_indexed("TESTER, ANNA JOY"))
    assert diff.verdict == "candidate" and "middle name differs" in diff.reasons[0]
    init = death_fit(rec, parse_indexed("TESTER, ANNA M"))
    assert init.verdict == "candidate" and "initial" in init.reasons[0]
    none_on_entry = death_fit(rec, parse_indexed("TESTER, ANNA"))
    assert none_on_entry.verdict == "candidate" and "entry gives no middle name" in none_on_entry.reasons[0]
    given = death_fit(rec, parse_indexed("TESTER, ANNABEL MARIE"))
    assert given.verdict == "candidate" and "given name differs" in given.reasons[0]
    assert death_fit(rec, parse_indexed("OTHERLY, ANNA MARIE")).verdict == "other_person"


def test_death_fit_record_without_middle_name_never_fits():
    rec = parse_indexed("TESTER, MAY")
    r = death_fit(rec, parse_indexed("TESTER, MAY"))
    assert r.verdict == "candidate" and "neither name has a middle name" in r.reasons[0]
    r2 = death_fit(rec, parse_indexed("TESTER, MAY DELL"))
    assert r2.verdict == "candidate" and "gives no middle name" in r2.reasons[0]


def test_death_fit_mrs_and_suffix():
    rec = parse_indexed("TESTER, JOHN QUINCY")
    assert death_fit(rec, parse_indexed("TESTER, JOHN QUINCY MRS")).verdict == "candidate"
    assert death_fit(rec, parse_indexed("TESTER, JOHN QUINCY/ JR")).verdict == "candidate"


def test_name_compat_for_chain_search():
    s = parse_indexed("TESTER, ANNA MARIE")
    assert name_compat(s, parse_indexed("TESTER, ANNA MARIE")) == "full"
    assert name_compat(s, parse_indexed("TESTER, ANNA M")) == "compatible"
    assert name_compat(s, parse_indexed("TESTER, ANNA")) == "compatible"
    assert name_compat(s, parse_indexed("TESTER, ANNA J")) is None
    assert name_compat(s, parse_indexed("TESTER, ANNE MARIE")) is None


def test_completed_levy_years_turn_on_january_6():
    assert not is_completed(2026, date(2027, 1, 5))
    assert is_completed(2026, date(2027, 1, 6))
    assert current_levy_year(date(2026, 10, 7)) == 2026
    assert current_levy_year(date(2027, 1, 5)) == 2026
    assert current_levy_year(date(2027, 1, 6)) == 2027
    done, pending = split_years([2019, 2022, 2023, 2024, 2025, 2026], date(2026, 10, 7))
    assert done == [2025, 2024, 2023] and pending == [2026]
