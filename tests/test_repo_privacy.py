"""scripts/audit_checks/repo_privacy.py: what counts as a real-looking phone, e-mail or estate name,
on made-up strings."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_checks import repo_privacy as R  # noqa: E402


def test_fake_shapes_pass():
    c = R.scan_text("call (828) 555-0142 or 828-555-0199; 704-133-0199 is not NANP; 999-999-9999; "
                    "mail jane@example.com, ops@sample-mail.test, x@y.invalid; ESTATE OF JOHN DOE; "
                    "Estate of Sally L. Rushtest; ESTATE OF JOHN SMITH'")
    assert sum(c.values()) == 0, c


def test_real_looking_shapes_are_counted():
    # built at run time so this file itself holds no real-looking value for the repo scan
    phone_a, phone_b = "(828) 762" + "-4410", "864.762" + ".4411"
    mail = "jdoe1972" + "@" + "gmail.com"
    estate = "the Estate " + "of Harlan Quentin Vexley"
    c = R.scan_text(f"Phone {phone_a}, {phone_b}; agent {mail}; {estate}")
    assert c["phones"] == 2 and c["emails"] == 1 and c["estate_names"] == 1


def test_configuration_allow_list():
    assert sum(R.scan_text("GMAIL_SENDER=highwaymarketingco@gmail.com -greghhigh@gmail.com").values()) == 0


def test_checks_have_the_interface():
    for c in R.make_checks():
        out = c.finish.__func__  # noqa: B018 - interface present (the scan itself runs in the suite)
        assert c.name.startswith("repo-privacy-") and callable(out)
