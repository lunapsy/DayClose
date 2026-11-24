"""Snapshot row shapes and the diff application for `file_entries`/`file_events` (06 §5.1).

The collector (collect/fs.py) produces `Changes`; this module persists them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Obs:
    root_id: int
    path: str
    name: str
    ext: str | None
    kind: str
    size: int
    mtime_ns: int
    ctime_ns: int
    birthtime_ns: int | None
    dev: int
    inode: int
    mode: int
    flags: int
    nlink: int


@dataclass
class Prev:
    id: int
    root_id: int
    path: str
    kind: str
    size: int
    mtime_ns: int
    ctime_ns: int
    birthtime_ns: int | None
    dev: int
    inode: int
    mode: int
    flags: int
    sha256: str | None


@dataclass
class Changes:
    created: list[Obs] = field(default_factory=list)
    modified: list[tuple[Prev, Obs]] = field(default_factory=list)
    moved: list[tuple[Prev, Obs, bool]] = field(default_factory=list)  # (prev, obs, emit_event)
    deleted: list[Prev] = field(default_factory=list)
    unchanged: list[tuple[Prev, Obs]] = field(default_factory=list)


# --------------------------------------------------------------------------- file_entries


def load_present_entries(conn: sqlite3.Connection) -> list[Prev]:
    return [
        Prev(
            id=r[0],
            root_id=r[1],
            path=r[2],
            kind=r[3],
            size=r[4],
            mtime_ns=r[5],
            ctime_ns=r[6],
            birthtime_ns=r[7],
            dev=r[8],
            inode=r[9],
            mode=r[10],
            flags=r[11],
            sha256=r[12],
        )
        for r in conn.execute(
            "SELECT id, root_id, path, kind, size_bytes, mtime_ns, ctime_ns, birthtime_ns, dev,"
            " inode, mode, flags, sha256 FROM file_entries WHERE present=1"
        )
    ]


@dataclass
class ApplyCounts:
    created: int = 0
    modified: int = 0
    deleted: int = 0
    moved: int = 0
    baseline_entries: int = 0


def _ins_values(o: Obs, run_id: int) -> tuple[Any, ...]:
    return (
        o.root_id,
        o.path,
        o.name,
        o.ext,
        o.kind,
        o.size,
        o.mtime_ns,
        o.ctime_ns,
        o.birthtime_ns,
        o.dev,
        o.inode,
        o.mode,
        o.flags,
        run_id,
        run_id,
    )


def apply_changes(
    conn: sqlite3.Connection,
    run_id: int,
    detected_at: int,
    ch: Changes,
    baseline_roots: set[int],
) -> ApplyCounts:
    """Apply a diff inside the caller's transaction (04 §2.4 entry/event rules).

    Observations in baseline roots are stored without events (04 §3.4).
    Order: deletes, two-phase path moves, updates, inserts - keeps the unique
    `path WHERE present=1` index valid at every statement.
    """
    counts = ApplyCounts()
    events: list[tuple[Any, ...]] = []

    def event(entry_id: int, kind: str, old: str | None, new: str | None, delta: int) -> None:
        events.append((run_id, entry_id, kind, old, new, delta, detected_at))

    conn.executemany(
        "UPDATE file_entries SET present=0, deleted_run_id=? WHERE id=?",
        [(run_id, p.id) for p in ch.deleted],
    )
    for p in ch.deleted:
        if p.root_id in baseline_roots:
            continue
        counts.deleted += 1
        event(p.id, "deleted", p.path, None, -p.size)

    conn.executemany(
        "UPDATE file_entries SET path=? WHERE id=?",
        [(f"\x00moving:{p.id}", p.id) for p, _, _ in ch.moved],
    )
    conn.executemany(
        "UPDATE file_entries SET path=?, name=?, ext=?, root_id=?, kind=?, size_bytes=?,"
        " mtime_ns=?, ctime_ns=?, birthtime_ns=?, dev=?, inode=?, mode=?, flags=?,"
        " last_seen_run_id=? WHERE id=?",
        [
            (
                o.path,
                o.name,
                o.ext,
                o.root_id,
                o.kind,
                o.size,
                o.mtime_ns,
                o.ctime_ns,
                o.birthtime_ns,
                o.dev,
                o.inode,
                o.mode,
                o.flags,
                run_id,
                p.id,
            )
            for p, o, _ in ch.moved
        ],
    )
    for p, o, emit in ch.moved:
        if emit and o.root_id not in baseline_roots:
            counts.moved += 1
            event(p.id, "moved", p.path, o.path, o.size - p.size)

    conn.executemany(
        "UPDATE file_entries SET root_id=?, size_bytes=?, mtime_ns=?, ctime_ns=?,"
        " birthtime_ns=?, dev=?, inode=?, mode=?, flags=?, sha256=NULL, sha256_mtime_ns=NULL,"
        " last_seen_run_id=? WHERE id=?",
        [
            (
                o.root_id,
                o.size,
                o.mtime_ns,
                o.ctime_ns,
                o.birthtime_ns,
                o.dev,
                o.inode,
                o.mode,
                o.flags,
                run_id,
                p.id,
            )
            for p, o in ch.modified
        ],
    )
    for p, o in ch.modified:
        if o.root_id in baseline_roots:
            continue
        counts.modified += 1
        event(p.id, "modified", None, o.path, o.size - p.size)

    # No event, but keep the snapshot current: mode/flags/ctime changes, a directory's own
    # mtime and size, a package's size, a root reassignment (04 §2.4 "조용히 갱신").
    silent = [
        (
            o.root_id,
            o.size,
            o.mtime_ns,
            o.ctime_ns,
            o.birthtime_ns,
            o.dev,
            o.inode,
            o.mode,
            o.flags,
            p.id,
        )
        for p, o in ch.unchanged
        if (
            p.root_id,
            p.size,
            p.mtime_ns,
            p.ctime_ns,
            p.birthtime_ns,
            p.dev,
            p.inode,
            p.mode,
            p.flags,
        )
        != (
            o.root_id,
            o.size,
            o.mtime_ns,
            o.ctime_ns,
            o.birthtime_ns,
            o.dev,
            o.inode,
            o.mode,
            o.flags,
        )
    ]
    conn.executemany(
        "UPDATE file_entries SET root_id=?, size_bytes=?, mtime_ns=?, ctime_ns=?,"
        " birthtime_ns=?, dev=?, inode=?, mode=?, flags=? WHERE id=?",
        silent,
    )
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _seen(id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM _seen")
    conn.executemany("INSERT INTO _seen(id) VALUES (?)", [(p.id,) for p, _ in ch.unchanged])
    conn.execute(
        "UPDATE file_entries SET last_seen_run_id=? WHERE id IN (SELECT id FROM _seen)",
        (run_id,),
    )
    conn.execute("DELETE FROM _seen")

    for o in ch.created:
        cur = conn.execute(
            "INSERT INTO file_entries(root_id, path, name, ext, kind, size_bytes, mtime_ns,"
            " ctime_ns, birthtime_ns, dev, inode, mode, flags, first_seen_run_id,"
            " last_seen_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _ins_values(o, run_id),
        )
        if o.root_id in baseline_roots:
            counts.baseline_entries += 1
        else:
            counts.created += 1
            event(int(cur.lastrowid or 0), "created", None, o.path, o.size)

    conn.executemany(
        "INSERT INTO file_events(run_id, entry_id, event, old_path, new_path, size_delta,"
        " detected_at) VALUES (?,?,?,?,?,?,?)",
        events,
    )
    return counts
