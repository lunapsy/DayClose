"""External prefixed IDs <-> integer primary keys (02 §5.1). The only place doing this."""

from __future__ import annotations

from dayclose.common.errors import UsageError

# kind -> prefix. Kinds are the table-ish names used by callers.
PREFIXES: dict[str, str] = {
    "run": "run",
    "entry": "ent",
    "event": "evt",
    "item": "itm",
    "group": "grp",
    "decision": "dec",
    "plan": "pln",
    "op": "op",
    "approval": "apv",
    "asset": "ast",
    "finding": "fnd",
    "project": "prj",
    "app": "app",
    "package": "pkg",
    "protection_rule": "rul",
    "policy_rule": "prl",
    "suppression": "sup",
    "session": "ses",
    "root": "root",
}


def to_ext(kind: str, pk: int) -> str:
    return f"{PREFIXES[kind]}_{pk}"


def opt_ext(kind: str, pk: int | None) -> str | None:
    return None if pk is None else to_ext(kind, pk)


def parse(kind: str, value: str) -> int:
    """Parse `<prefix>_<n>`. Plain integers and other prefixes are E_USAGE (10 §1.1)."""
    prefix = PREFIXES[kind]
    head, sep, tail = value.rpartition("_")
    if not sep or head != prefix or not tail.isdigit() or tail.startswith("0") and tail != "0":
        raise UsageError(
            "ID 형식이 올바르지 않습니다.",
            {"expected_prefix": f"{prefix}_", "value": value[:64]},
        )
    return int(tail)
