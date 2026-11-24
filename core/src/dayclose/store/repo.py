"""Repository functions for the 0001 tables (06 §5.1). All SQL for M1 lives here."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- transactions


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# --------------------------------------------------------------------------- app_meta


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return None if row is None else str(row[0])


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# --------------------------------------------------------------------------- scan_roots


@dataclass
class RootRow:
    id: int
    path: str
    kind: str
    enabled: bool
    max_depth: int | None
    file_level: bool
    icloud_synced_mode: str
    icloud_synced: bool
    icloud_synced_source: str
    created_at: int
    removed_at: int | None


_ROOT_COLS = (
    "id, path, kind, enabled, max_depth, file_level, icloud_synced_mode, icloud_synced, "
    "icloud_synced_source, created_at, removed_at"
)


def _root(row: Sequence[Any]) -> RootRow:
    return RootRow(
        id=row[0],
        path=row[1],
        kind=row[2],
        enabled=bool(row[3]),
        max_depth=row[4],
        file_level=bool(row[5]),
        icloud_synced_mode=row[6],
        icloud_synced=bool(row[7]),
        icloud_synced_source=row[8],
        created_at=row[9],
        removed_at=row[10],
    )


def insert_root(
    conn: sqlite3.Connection,
    *,
    path: str,
    kind: str,
    max_depth: int | None,
    file_level: bool,
    icloud_mode: str,
    icloud_synced: int,
    icloud_source: str,
    created_at: int,
) -> RootRow:
    cur = conn.execute(
        "INSERT INTO scan_roots(path, kind, enabled, max_depth, file_level, icloud_synced_mode,"
        " icloud_synced, icloud_synced_source, created_at) VALUES (?,?,1,?,?,?,?,?,?)",
        (
            path,
            kind,
            max_depth,
            int(file_level),
            icloud_mode,
            icloud_synced,
            icloud_source,
            created_at,
        ),
    )
    root = get_root(conn, int(cur.lastrowid or 0), include_removed=True)
    assert root is not None
    return root


def get_root(
    conn: sqlite3.Connection, root_id: int, *, include_removed: bool = False
) -> RootRow | None:
    sql = f"SELECT {_ROOT_COLS} FROM scan_roots WHERE id=?"
    if not include_removed:
        sql += " AND removed_at IS NULL"
    row = conn.execute(sql, (root_id,)).fetchone()
    return None if row is None else _root(row)


def active_root_by_path(conn: sqlite3.Connection, path: str) -> RootRow | None:
    row = conn.execute(
        f"SELECT {_ROOT_COLS} FROM scan_roots WHERE path=? AND removed_at IS NULL", (path,)
    ).fetchone()
    return None if row is None else _root(row)


def list_roots(conn: sqlite3.Connection, *, include_removed: bool = False) -> list[RootRow]:
    sql = f"SELECT {_ROOT_COLS} FROM scan_roots"
    if not include_removed:
        sql += " WHERE removed_at IS NULL"
    return [_root(r) for r in conn.execute(sql + " ORDER BY id")]


def remove_root(conn: sqlite3.Connection, root_id: int, removed_at: int) -> None:
    conn.execute("UPDATE scan_roots SET removed_at=? WHERE id=?", (removed_at, root_id))


def update_root_icloud(conn: sqlite3.Connection, root_id: int, synced: int, source: str) -> None:
    conn.execute(
        "UPDATE scan_roots SET icloud_synced=?, icloud_synced_source=? WHERE id=? "
        "AND (icloud_synced<>? OR icloud_synced_source<>?)",
        (synced, source, root_id, synced, source),
    )


# --------------------------------------------------------------------------- audit_log


def insert_audit(
    conn: sqlite3.Connection,
    *,
    ts: int,
    request_id: str,
    command: str,
    channel: str,
    ok: bool,
    error_code: str | None,
    target_type: str | None,
    target_ids: list[str],
    summary: str,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(ts, request_id, command, channel, ok, error_code, target_type,"
        " target_ids_json, summary) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ts,
            request_id,
            command,
            channel,
            int(ok),
            error_code,
            target_type,
            json.dumps(target_ids),
            summary,
        ),
    )
