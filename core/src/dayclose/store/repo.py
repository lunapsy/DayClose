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


# --------------------------------------------------------------------------- scan_runs


@dataclass
class RunRow:
    id: int
    started_at: int
    finished_at: int | None
    status: str
    trigger: str
    collectors: list[str]
    stats: dict[str, Any]
    error_code: str | None


_RUN_COLS = (
    'id, started_at, finished_at, status, "trigger", collectors_json, stats_json, error_code'
)


def _run(row: Sequence[Any]) -> RunRow:
    return RunRow(
        id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
        trigger=row[4],
        collectors=json.loads(row[5]),
        stats=json.loads(row[6]),
        error_code=row[7],
    )


def interrupt_running_runs(conn: sqlite3.Connection, now_ms: int) -> int:
    cur = conn.execute(
        "UPDATE scan_runs SET status='interrupted', finished_at=COALESCE(finished_at, ?) "
        "WHERE status='running'",
        (now_ms,),
    )
    return cur.rowcount


def create_run(
    conn: sqlite3.Connection,
    *,
    started_at: int,
    trigger: str,
    collectors: list[str],
    request_id: str,
) -> int:
    cur = conn.execute(
        'INSERT INTO scan_runs(started_at, status, "trigger", collectors_json, request_id) '
        "VALUES (?, 'running', ?, ?, ?)",
        (started_at, trigger, json.dumps(collectors), request_id),
    )
    return int(cur.lastrowid or 0)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    finished_at: int,
    stats: dict[str, Any],
    error_code: str | None,
) -> None:
    conn.execute(
        "UPDATE scan_runs SET status=?, finished_at=?, stats_json=?, error_code=? WHERE id=?",
        (status, finished_at, json.dumps(stats, ensure_ascii=False), error_code, run_id),
    )


def get_run(conn: sqlite3.Connection, run_id: int) -> RunRow | None:
    row = conn.execute(f"SELECT {_RUN_COLS} FROM scan_runs WHERE id=?", (run_id,)).fetchone()
    return None if row is None else _run(row)


def latest_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT max(id) FROM scan_runs").fetchone()
    return None if row is None or row[0] is None else int(row[0])


def list_runs(
    conn: sqlite3.Connection, *, limit: int, after: tuple[int, int] | None
) -> tuple[list[RunRow], int]:
    where = ""
    params: list[Any] = []
    if after is not None:
        where = " WHERE (started_at < ? OR (started_at = ? AND id < ?))"
        params = [after[0], after[0], after[1]]
    rows = conn.execute(
        f"SELECT {_RUN_COLS} FROM scan_runs{where} ORDER BY started_at DESC, id DESC LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    total = int(conn.execute("SELECT count(*) FROM scan_runs").fetchone()[0])
    return [_run(r) for r in rows], total


def traversed_root_ids(conn: sqlite3.Connection) -> set[int]:
    """Roots that some finished run traversed (ok/partial) - the baseline test (04 §3.4)."""
    rows = conn.execute(
        "SELECT DISTINCT json_extract(j.value, '$.root_id') FROM scan_runs r, "
        "json_each(r.stats_json, '$.root_results') j "
        "WHERE r.status IN ('completed','partial') "
        "AND json_extract(j.value, '$.traversed') = 1"
    ).fetchall()
    return {int(r[0]) for r in rows if r[0] is not None}


# --------------------------------------------------------------------------- file_events


@dataclass
class EventRow:
    id: int
    run_id: int
    entry_id: int
    event: str
    kind: str
    old_path: str | None
    new_path: str | None
    size_delta: int
    detected_at: int


def list_events(
    conn: sqlite3.Connection,
    *,
    run_id: int | None,
    since_ms: int | None,
    events: list[str] | None,
    root_id: int | None,
    limit: int,
    after: tuple[int, int] | None,
    count_cap: int,
) -> tuple[list[EventRow], int | None]:
    where: list[str] = []
    params: list[Any] = []
    if run_id is not None:
        where.append("ev.run_id = ?")
        params.append(run_id)
    if since_ms is not None:
        where.append("ev.detected_at >= ?")
        params.append(since_ms)
    if events:
        where.append(f"ev.event IN ({','.join('?' * len(events))})")
        params.extend(events)
    if root_id is not None:
        where.append("e.root_id = ?")
        params.append(root_id)
    base = " FROM file_events ev JOIN file_entries e ON e.id = ev.entry_id"
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    page_cond = cond
    page_params = list(params)
    if after is not None:
        page_cond += (" AND " if cond else " WHERE ") + (
            "(ev.detected_at < ? OR (ev.detected_at = ? AND ev.id < ?))"
        )
        page_params += [after[0], after[0], after[1]]
    rows = conn.execute(
        "SELECT ev.id, ev.run_id, ev.entry_id, ev.event, e.kind, ev.old_path, ev.new_path,"
        " ev.size_delta, ev.detected_at"
        + base
        + page_cond
        + " ORDER BY ev.detected_at DESC, ev.id DESC LIMIT ?",
        (*page_params, limit + 1),
    ).fetchall()
    capped = conn.execute(
        f"SELECT count(*) FROM (SELECT 1{base}{cond} LIMIT ?)", (*params, count_cap + 1)
    ).fetchone()[0]
    total: int | None = int(capped) if capped <= count_cap else None
    return [EventRow(*r) for r in rows], total


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
