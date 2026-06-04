"""Structured (key=value) logging setup.

``setup_logging`` configures the package logger so code can do
``log.info("event_name", extra={"id": ...})`` and have the extras rendered as
trailing ``key=value`` pairs, instead of using ``print``.
"""

from __future__ import annotations

import logging
import sys

PACKAGE_LOGGER = "wsb_dd"

# Attribute names present on a vanilla LogRecord; anything else on a record was
# injected via ``extra=`` and should be rendered as a key=value pair.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


def _fmt_value(value: object) -> str:
    text = str(value)
    if text == "" or any(ch.isspace() for ch in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


class KeyValueFormatter(logging.Formatter):
    """Formatter that appends record extras as ``key=value`` pairs."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: val
            for key, val in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        if not extras:
            return base
        rendered = " ".join(f"{key}={_fmt_value(val)}" for key, val in extras.items())
        return f"{base} {rendered}"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the package logger at ``level`` (idempotent)."""
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.setLevel(level.upper())
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(
            KeyValueFormatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    else:
        for handler in logger.handlers:
            handler.setLevel(level.upper())

    return logger
