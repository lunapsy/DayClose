"""The JSON envelope (02 §5.4). Key order is fixed (10 §1.2)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from dayclose.common.errors import DayCloseError, PartialError

SCHEMA = "dayclose.v1"
CONTRACT_VERSION = 1
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_request_id() -> str:
    """`req_` + ULID (48-bit ms timestamp + 80 random bits, Crockford base32)."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "req_" + "".join(reversed(chars))


@dataclass
class Warning_:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass
class Meta:
    request_id: str
    core_version: str
    db_schema_version: int | None
    device_id: str | None
    duration_ms: int

    def to_json(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "core_version": self.core_version,
            "contract_version": CONTRACT_VERSION,
            "db_schema_version": self.db_schema_version,
            "device_id": self.device_id,
            "duration_ms": self.duration_ms,
        }


def success(command: str, data: Any, warnings: list[Warning_], meta: Meta) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "command": command,
        "ok": True,
        "data": data,
        "warnings": [w.to_json() for w in warnings],
        "error": None,
        "meta": meta.to_json(),
    }


def failure(
    command: str, err: DayCloseError, warnings: list[Warning_], meta: Meta
) -> dict[str, Any]:
    data = err.data if isinstance(err, PartialError) else None
    return {
        "schema": SCHEMA,
        "command": command,
        "ok": False,
        "data": data,
        "warnings": [w.to_json() for w in warnings],
        "error": {
            "code": err.code,
            "message": err.message,
            "details": err.details,
            "retryable": err.retryable,
        },
        "meta": meta.to_json(),
    }


def dumps(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
