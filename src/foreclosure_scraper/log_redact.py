"""Mask credentials in log output.

httpx logs every request URL at INFO, so a Street View call wrote the full Google Maps API key
into the VM run log 679 times (found 2026-10-06). This masks secret-looking query parameters in
stdlib log records and in structlog event values.
"""
from __future__ import annotations

import logging
import re

_SECRET_PARAM = re.compile(
    r"(?i)\b(key|api_key|apikey|token|access_token|auth|signature|sig|client_secret|password)"
    r"=([^&\s\"'<>]+)")


def redact(text: str) -> str:
    return _SECRET_PARAM.sub(lambda m: f"{m.group(1)}=REDACTED", text)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 -- a malformed record must still log
            return True
        masked = redact(msg)
        if masked != msg:
            record.msg, record.args = masked, ()
        return True


def structlog_processor(_logger, _method, event_dict: dict) -> dict:
    for k, v in event_dict.items():
        if isinstance(v, str) and "=" in v:
            event_dict[k] = redact(v)
    return event_dict


def install() -> None:
    """Attach the filter to the root handlers and the HTTP client loggers. Idempotent."""
    targets = list(logging.getLogger().handlers) + [
        logging.getLogger(n) for n in ("httpx", "httpcore", "urllib3")]
    for t in targets:
        if not any(isinstance(f, RedactSecretsFilter) for f in t.filters):
            t.addFilter(RedactSecretsFilter())
