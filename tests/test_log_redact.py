import logging

from foreclosure_scraper import log_redact

KEY_URL = ("https://maps.googleapis.com/maps/api/streetview/metadata"
           "?location=35.59,-82.55&key=AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE00&size=640x640")


def test_redact_masks_key_and_keeps_the_rest():
    out = log_redact.redact(KEY_URL)
    assert "AIzaSy" not in out
    assert "key=REDACTED" in out and "location=35.59,-82.55" in out and "size=640x640" in out


def test_redact_masks_other_credential_params_case_insensitively():
    out = log_redact.redact("GET /x?Token=abc123&api_key=zzz&page=2")
    assert "abc123" not in out and "zzz" not in out and "page=2" in out


def test_filter_masks_httpx_style_record(caplog):
    lg = logging.getLogger("httpx")
    lg.addFilter(log_redact.RedactSecretsFilter())
    try:
        with caplog.at_level(logging.INFO, logger="httpx"):
            lg.info('HTTP Request: %s %s "%s"', "GET", KEY_URL, "HTTP/1.1 200 OK")
        assert "AIzaSy" not in caplog.text and "key=REDACTED" in caplog.text
    finally:
        for f in list(lg.filters):
            if isinstance(f, log_redact.RedactSecretsFilter):
                lg.removeFilter(f)


def test_structlog_processor_masks_string_values_only():
    ev = log_redact.structlog_processor(None, "info", {"event": "x", "url": KEY_URL, "n": 3})
    assert "AIzaSy" not in ev["url"] and ev["n"] == 3


def test_install_is_idempotent():
    log_redact.install()
    log_redact.install()
    lg = logging.getLogger("httpx")
    assert sum(isinstance(f, log_redact.RedactSecretsFilter) for f in lg.filters) == 1
