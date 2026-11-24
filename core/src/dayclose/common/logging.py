"""JSON Lines logging with redaction (02 §13).

Line 1 of defence: callers pass only allow-listed fields. Line 2: `RedactingFilter`.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from dayclose.common import clock

LOGGER_NAME = "dayclose"
ALLOWED_FIELDS = (
    "request_id",
    "command",
    "channel",
    "event",
    "code",
    "ok",
    "duration_ms",
    "run_id",
    "root_id",
    "count",
    "status",
)
REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|$)"
    ),
    re.compile(r"-----BEGIN [A-Z0-9 ]+-----"),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
]
_TOKEN = re.compile(r"[A-Za-z0-9+=_\-]{32,}")  # no "/": keeps ordinary paths intact


def _entropy(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def redact(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)

    def _maybe(m: re.Match[str]) -> str:
        tok = m.group(0)
        has_digit = any(c.isdigit() for c in tok)
        has_alpha = any(c.isalpha() for c in tok)
        if has_digit and has_alpha and _entropy(tok) >= 4.0:
            return REDACTED
        return tok

    return _TOKEN.sub(_maybe, text)


class RedactingFilter(logging.Filter):
    """Replaces known key patterns and high-entropy tokens with `[REDACTED]`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        for key in ALLOWED_FIELDS:
            val = getattr(record, key, None)
            if isinstance(val, str):
                setattr(record, key, redact(val))
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(formatted)
            record.exc_info = None
        return True


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": clock.ms_to_rfc3339(int(record.created * 1000)),
            "level": record.levelname.lower(),
        }
        for key in ALLOWED_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                out[key] = val
        out["msg"] = record.getMessage()
        if record.exc_text:
            out["traceback"] = record.exc_text
        return json.dumps(out, ensure_ascii=False)


_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def log_path(home: Path, home_overridden: bool, user_home: Path) -> Path:
    """`DAYCLOSE_HOME/logs` when the home is overridden, else ~/Library/Logs/DayClose (02 §8)."""
    if home_overridden:
        return home / "logs" / "core.log"
    return user_home / "Library/Logs/DayClose" / "core.log"


def setup(path: Path, level: str) -> logging.Logger:
    """Attach a rotating JSON-lines handler (5 MB x 5 files)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_LEVELS.get(level, logging.INFO))
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    old_umask = os.umask(0o077)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
    finally:
        os.umask(old_umask)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonLinesFormatter())
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
    return logger


def shutdown() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
