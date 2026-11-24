"""List conventions: --limit, opaque keyset --cursor (10 §1.4)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from dayclose.common.errors import UsageError

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def limit_of(args: dict[str, Any]) -> int:
    value = args.get("limit")
    if value is None:
        return DEFAULT_LIMIT
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_LIMIT:
        raise UsageError("--limit 은 1~500 사이여야 합니다.", {"min": 1, "max": MAX_LIMIT})
    return value


def _fingerprint(filters: dict[str, Any]) -> str:
    raw = json.dumps(filters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def encode(key: list[Any], filters: dict[str, Any]) -> str:
    raw = json.dumps({"k": key, "f": _fingerprint(filters)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(cursor: str | None, filters: dict[str, Any], arity: int) -> list[Any] | None:
    if cursor is None:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        obj = json.loads(base64.urlsafe_b64decode(cursor + pad))
        key = obj["k"]
        ok = (
            isinstance(key, list)
            and len(key) == arity
            and all(isinstance(x, int) and not isinstance(x, bool) for x in key)
            and obj["f"] == _fingerprint(filters)
        )
    except (ValueError, KeyError, TypeError, binascii.Error):
        ok = False
    if not ok:
        raise UsageError(
            "커서가 올바르지 않거나 다른 필터의 커서입니다.", {"reason": "cursor_mismatch"}
        )
    return list(key)


def page(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    """Rows were fetched with LIMIT limit+1; returns (page, has_more)."""
    return items[:limit], len(items) > limit
