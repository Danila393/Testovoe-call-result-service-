"""Logging setup: one JSON object per line on stdout."""

from __future__ import annotations

import io
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Attributes every LogRecord has; anything else was passed through ``extra=`` and is emitted.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formats a record as a single-line JSON object, including ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    """Route root logging to stdout as JSON. Idempotent.

    Messages keep non-ASCII text readable (``ensure_ascii=False``); a console that cannot encode
    a character (legacy Windows code pages) gets an escape instead of a logging error.
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # aiormq logs every connection hiccup at ERROR with tracebacks; our consumer logs them once.
    logging.getLogger("aiormq").setLevel(logging.CRITICAL)
    logging.getLogger("aio_pika").setLevel(logging.WARNING)
