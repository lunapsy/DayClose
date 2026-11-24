"""Injectable clock (AGENTS.md §6). `DAYCLOSE_TEST_NOW` is honoured only in sandbox mode."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime

_override: Callable[[], datetime] | None = None


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Install a fixed clock for in-process tests (None restores the real clock)."""
    global _override
    _override = fn


def now() -> datetime:
    """Current time, timezone-aware UTC."""
    if _override is not None:
        return _override()
    if os.environ.get("DAYCLOSE_SANDBOX"):
        fixed = os.environ.get("DAYCLOSE_TEST_NOW")
        if fixed:
            return parse_rfc3339(fixed)
    return datetime.now(UTC)


def now_ms() -> int:
    return int(now().timestamp() * 1000)


def now_ns() -> int:
    n = now()
    return int(n.timestamp()) * 1_000_000_000 + n.microsecond * 1000


def monotonic() -> float:
    """Durations only; never affected by the test clock."""
    return time.monotonic()


def parse_rfc3339(value: str) -> datetime:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("RFC 3339 time needs an offset")
    return dt.astimezone(UTC)


def ms_to_rfc3339(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def ns_to_rfc3339(ns: int) -> str:
    return ms_to_rfc3339(ns // 1_000_000)
