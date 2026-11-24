"""Pure snapshot-diff rules (04 §2.4) and exclude globs (04 §2.2)."""

from __future__ import annotations

import pytest

from dayclose.collect.fs import ExcludeRules, diff
from dayclose.store.entries import Obs, Prev


def prev(
    i: int,
    path: str,
    *,
    kind: str = "file",
    size: int = 10,
    mtime: int = 100,
    inode: int | None = None,
    birth: int | None = 1,
    root: int = 1,
    sha: str | None = None,
) -> Prev:
    return Prev(
        id=i,
        root_id=root,
        path=path,
        kind=kind,
        size=size,
        mtime_ns=mtime,
        ctime_ns=0,
        birthtime_ns=birth,
        dev=1,
        inode=inode if inode is not None else i,
        mode=0,
        flags=0,
        sha256=sha,
    )


def obs(
    path: str,
    *,
    kind: str = "file",
    size: int = 10,
    mtime: int = 100,
    inode: int = 0,
    birth: int | None = 1,
    nlink: int = 1,
    root: int = 1,
    dev: int = 1,
) -> Obs:
    name = path.rsplit("/", 1)[-1]
    return Obs(
        root_id=root,
        path=path,
        name=name,
        ext=None,
        kind=kind,
        size=size,
        mtime_ns=mtime,
        ctime_ns=0,
        birthtime_ns=birth,
        dev=dev,
        inode=inode,
        mode=0,
        flags=0,
        nlink=nlink,
    )


def never(_: Prev) -> bool:
    return False


def test_unchanged_rescan_no_events() -> None:
    ch = diff([prev(1, "/r/a")], [obs("/r/a", inode=1)], {1}, never)
    assert (ch.created, ch.modified, ch.moved, ch.deleted) == ([], [], [], [])
    assert len(ch.unchanged) == 1


def test_modified_by_size_or_mtime() -> None:
    ch = diff(
        [prev(1, "/r/a"), prev(2, "/r/b")],
        [obs("/r/a", inode=1, size=11), obs("/r/b", inode=2, mtime=101)],
        {1},
        never,
    )
    assert sorted(p.path for p, _ in ch.modified) == ["/r/a", "/r/b"]


def test_rename_is_one_move() -> None:
    ch = diff([prev(1, "/r/a")], [obs("/r/b", inode=1)], {1}, never)
    assert [(p.path, o.path, e) for p, o, e in ch.moved] == [("/r/a", "/r/b", True)]
    assert ch.created == [] and ch.deleted == []


def test_inode_reuse_with_other_birthtime_is_delete_plus_create() -> None:
    ch = diff([prev(1, "/r/a", birth=1)], [obs("/r/b", inode=1, birth=2)], {1}, never)
    assert [o.path for o in ch.created] == ["/r/b"] and [p.path for p in ch.deleted] == ["/r/a"]


def test_hardlink_not_identity_matched() -> None:
    ch = diff([prev(1, "/r/a")], [obs("/r/b", inode=1, nlink=2)], {1}, never)
    assert ch.moved == [] and len(ch.created) == len(ch.deleted) == 1


def test_safe_save_new_inode_same_path_is_modified() -> None:
    ch = diff([prev(1, "/r/a", inode=1)], [obs("/r/a", inode=9, size=12)], {1}, never)
    assert [(p.inode, o.inode) for p, o in ch.modified] == [(1, 9)]
    assert ch.created == [] and ch.deleted == []


def test_rename_over_existing_path() -> None:
    ch = diff(
        [prev(1, "/r/a", inode=1), prev(2, "/r/b", inode=2)], [obs("/r/b", inode=1)], {1}, never
    )
    assert [(p.path, o.path) for p, o, _ in ch.moved] == [("/r/a", "/r/b")]
    assert [p.id for p in ch.deleted] == [2]


def test_directory_never_modified_and_children_silent_on_move() -> None:
    before = [
        prev(1, "/r/d", kind="dir"),
        prev(2, "/r/d/x", inode=2),
        prev(3, "/r/d/s", kind="dir", inode=3),
        prev(4, "/r/d/s/y", inode=4),
    ]
    after = [
        obs("/r/e", kind="dir", inode=1, mtime=999, nlink=4),
        obs("/r/e/x", inode=2),
        obs("/r/e/s", kind="dir", inode=3, nlink=3),
        obs("/r/e/s/y", inode=4),
    ]
    ch = diff(before, after, {1}, never)
    emitted = [(p.path, o.path) for p, o, e in ch.moved if e]
    assert emitted == [("/r/d", "/r/e")]
    assert len(ch.moved) == 4 and ch.modified == []


def test_dir_mtime_change_is_not_modified() -> None:
    ch = diff(
        [prev(1, "/r/d", kind="dir")], [obs("/r/d", kind="dir", inode=1, mtime=5)], {1}, never
    )
    assert ch.modified == []


def test_package_compares_own_mtime_only() -> None:
    ch = diff(
        [prev(1, "/r/A.app", kind="package", size=100)],
        [obs("/r/A.app", kind="package", inode=1, size=200, nlink=3)],
        {1},
        never,
    )
    assert ch.modified == []
    ch = diff(
        [prev(1, "/r/A.app", kind="package")],
        [obs("/r/A.app", kind="package", inode=1, mtime=7, nlink=3)],
        {1},
        never,
    )
    assert len(ch.modified) == 1


def test_unseen_safe_rows_do_not_vanish() -> None:
    rows = [prev(1, "/r/locked/a"), prev(2, "/r/gone")]
    ch = diff(rows, [], {1}, lambda p: p.path.startswith("/r/locked/"))
    assert [p.path for p in ch.deleted] == ["/r/gone"]


def test_rows_of_untraversed_roots_never_vanish() -> None:
    ch = diff([prev(1, "/v/a", root=2)], [], {1}, never)
    assert ch.deleted == []


def test_cross_root_move_by_identity() -> None:
    ch = diff([prev(1, "/dl/a", root=1)], [obs("/desk/a", inode=1, root=2)], {1, 2}, never)
    assert [(p.root_id, o.root_id) for p, o, _ in ch.moved] == [(1, 2)]


def test_cross_device_second_pass_uses_hash() -> None:
    big = 2 * 1024 * 1024
    rows = [prev(1, "/ext/m.mov", size=big, sha="ab" * 32)]
    seen = [obs("/int/m.mov", size=big, inode=50, dev=2)]
    ch = diff(rows, seen, {1}, never, hasher=lambda o: "ab" * 32)
    assert [(p.path, o.path) for p, o, _ in ch.moved] == [("/ext/m.mov", "/int/m.mov")]
    ch = diff(rows, seen, {1}, never, hasher=lambda o: "cd" * 32)
    assert ch.moved == [] and len(ch.created) == len(ch.deleted) == 1
    small = [prev(1, "/ext/s", size=10, sha="ab" * 32)]
    ch = diff(
        small, [obs("/int/s", size=10, inode=50, dev=2)], {1}, never, hasher=lambda o: "ab" * 32
    )
    assert ch.moved == []  # below 1 MiB: never matched


def test_legacy_placeholder_pairs_without_event() -> None:
    ch = diff([prev(1, "/d/.doc.pdf.icloud")], [obs("/d/doc.pdf", inode=7)], {1}, never)
    assert [(p.path, o.path, e) for p, o, e in ch.moved] == [
        ("/d/.doc.pdf.icloud", "/d/doc.pdf", False)
    ]


@pytest.mark.parametrize(
    ("glob", "rel", "is_dir", "verdict"),
    [
        ("**/.DS_Store", ".DS_Store", False, "exclude"),
        ("**/.DS_Store", "a/b/.DS_Store", False, "exclude"),
        ("**/node_modules/**", "x/node_modules", True, "no_descend"),
        ("**/node_modules/**", "node_modules", True, "no_descend"),
        ("**/node_modules/**", "x/node_modules/y.js", False, "exclude"),
        ("**/Library/**", "", True, "keep"),
        ("**/Library/**", "Library", True, "no_descend"),
        ("**/Library/**", "Libraryx", True, "keep"),
        ("*.tmp", "a.tmp", False, "exclude"),
        ("*.tmp", "d/a.tmp", False, "keep"),  # `*` never crosses `/`
        ("**/*.photoslibrary/**", "Pics/P.photoslibrary", True, "no_descend"),
    ],
)
def test_exclude_rules(glob: str, rel: str, is_dir: bool, verdict: str) -> None:
    assert ExcludeRules.compile([glob]).classify(rel, is_dir) == verdict
