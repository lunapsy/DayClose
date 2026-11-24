"""FR-CORE-006/007/008: probe deadline, scan lock, dataless, nested roots, root iCloud values.

Tests that need injection (a hung volume, SF_DATALESS) run the api in-process.
"""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
import sqlite3
import sys
import threading
import time
from typing import Any

import pytest
from conftest import RunCli, Sandbox
from fixtures.sandbox import ICLOUD_REL, build_sandbox
from inproc import init, ok, run

from dayclose.collect import fs as fs_collector
from dayclose.common import paths

# --------------------------------------------------------------------------- FR-CORE-006


def test_fr_core_005_scan_tcc_vs_permission(sandbox: Sandbox) -> None:
    """A TCC-denied root and a plain EACCES root are reported with different codes."""
    init()
    tcc = sandbox.mkdir("Desktop")
    plain = sandbox.mkdir("noaccess")
    ok("root.add", path=str(tcc), kind="desktop")
    ok("root.add", path=str(plain), kind="custom")
    real = paths._default_probe_stat

    def probe_stat(path: str) -> None:
        if path == str(tcc):
            raise PermissionError(errno.EPERM, "Operation not permitted", path)
        if path == str(plain):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        real(path)

    paths.probe_stat = probe_stat
    scan, code = run("scan.run")
    assert code == 6 and scan["error"]["code"] == "E_TCC_DENIED"
    assert [w["code"] for w in scan["warnings"]] == ["W_TCC_DENIED", "W_ROOT_UNAVAILABLE"]


def test_fr_core_006_probe_deadline(sandbox: Sandbox) -> None:
    init(scan__volume_probe_timeout_s=1)
    hung = sandbox.mkdir("vol/External")
    ok("root.add", path=str(hung), kind="custom")
    ok("root.add", path=str(sandbox.mkdir("Downloads")), kind="downloads")
    release = threading.Event()
    real = paths._default_probe_stat

    def probe_stat(path: str) -> None:
        if path == str(hung):
            release.wait(30)  # a volume that never answers
        real(path)

    paths.probe_stat = probe_stat
    try:
        start = time.monotonic()
        env, code = run("scan.run")
        elapsed = time.monotonic() - start
    finally:
        release.set()
    assert code == 0 and elapsed <= 1 + 2
    assert env["data"]["status"] == "partial"
    warns = [w for w in env["warnings"] if w["code"] == "W_ROOT_UNAVAILABLE"]
    assert warns and warns[0]["details"] == {"root_id": "root_1", "reason": "timeout"}


def test_fr_core_006_dataless_not_hashed(sandbox: Sandbox) -> None:
    """Cross-volume matching hashes candidates in memory - never a dataless file."""
    big = b"x" * (1024 * 1024 + 1)
    src = sandbox.mkdir("A") / "movie.mov"
    src.write_bytes(big)
    st = src.stat()
    prev = fs_collector.Prev(
        id=1,
        root_id=1,
        path=str(src),
        kind="file",
        size=len(big),
        mtime_ns=st.st_mtime_ns,
        ctime_ns=st.st_ctime_ns,
        birthtime_ns=None,
        dev=999,
        inode=1,
        mode=st.st_mode,
        flags=0,
        sha256="0" * 64,
    )
    dst = sandbox.mkdir("B") / "movie.mov"
    shutil.copyfile(src, dst)
    src.unlink()
    dst_st = dst.stat()
    obs = fs_collector.Obs(
        root_id=2,
        path=str(dst),
        name="movie.mov",
        ext="mov",
        kind="file",
        size=len(big),
        mtime_ns=dst_st.st_mtime_ns,
        ctime_ns=dst_st.st_ctime_ns,
        birthtime_ns=None,
        dev=dst_st.st_dev,
        inode=dst_st.st_ino,
        mode=dst_st.st_mode,
        flags=0,
        nlink=1,
    )
    opened: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args and isinstance(args[0], str) and args[0] == str(dst):
            opened.append(args[0])

    sys.addaudithook(audit)
    fs_collector.flags_hook = lambda p, f: f | paths.SF_DATALESS if p == str(dst) else f
    hasher = fs_collector.make_hasher(64 * 1024 * 1024)
    ch = fs_collector.diff([prev], [obs], {1, 2}, lambda p: False, hasher)
    assert opened == [] and [o.path for o in ch.created] == [str(dst)]
    fs_collector.flags_hook = None
    assert hasher(obs) is not None and opened == [str(dst)]


# --------------------------------------------------------------------------- FR-CORE-007


def test_fr_core_007_concurrent_scan_one_locked(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    cli("root", "add", str(sandbox.mkdir("Downloads")), "--kind", "downloads")
    fd = os.open(sandbox.home / "state.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # another writer holds the lock
        res = cli("scan", "run", "--wait-lock", "0")
        assert res.returncode == 7
        err = res.envelope["error"]
        assert err["code"] == "E_LOCKED" and err["retryable"] is True
        assert cli("scan", "list").returncode == 0  # reads never take the lock
    finally:
        os.close(fd)
    assert cli("scan", "run", "--wait-lock", "0").returncode == 0


def test_fr_core_007_two_processes(initialized: RunCli, sandbox: Sandbox, now: Any) -> None:
    import subprocess

    cli = initialized
    build_sandbox(sandbox.root, "perf_10k", now=now)
    cli("root", "add", str(sandbox.user / "Downloads"), "--kind", "downloads")
    argv = [sys.executable, "-m", "dayclose", "scan", "run", "--json", "--wait-lock", "0"]
    procs = [
        subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, cwd=sandbox.root)
        for _ in range(2)
    ]
    codes = sorted(p.wait(60) for p in procs)
    for p in procs:
        assert p.stdout is not None
        p.stdout.close()
    assert codes in ([0, 0], [0, 7])  # never both failing, never both writing at once


# --------------------------------------------------------------------------- FR-CORE-008


@pytest.fixture
def icloud_tree(sandbox: Sandbox, now: Any) -> Any:
    m = build_sandbox(sandbox.root, "icloud", now=now)
    dataless = {str(p) for p in m.dataless_paths()}
    fs_collector.flags_hook = lambda p, f: f | paths.SF_DATALESS if p in dataless else f
    return m


def test_fr_core_008_dataless_never_opened(sandbox: Sandbox, icloud_tree: Any) -> None:
    init()
    drive = sandbox.user / ICLOUD_REL
    watched = {str(p) for p in icloud_tree.dataless_paths()} | {str(drive / ".계약서.pdf.icloud")}
    opened: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args and isinstance(args[0], str) and args[0] in watched:
            opened.append(args[0])

    sys.addaudithook(audit)
    ok("root.add", path=str(drive), kind="icloud_drive")
    base, _ = run("scan.run")
    for p in icloud_tree.dataless_paths():
        p.write_bytes(p.read_bytes() + b" grown")  # metadata change must not trigger reads
    opened.clear()
    env, code = run("scan.run")
    assert code == 0 and opened == []
    assert env["data"]["stats"]["dataless_skipped"] == 3
    w = [x for x in env["warnings"] if x["code"] == "W_DATALESS_SKIPPED"]
    assert w and w[0]["details"] == {"count": 3}
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    hashes = conn.execute("SELECT count(*) FROM file_entries WHERE sha256 IS NOT NULL").fetchone()
    conn.close()
    assert hashes[0] == 0


def test_fr_core_008_nested_roots_no_duplicates(sandbox: Sandbox, icloud_tree: Any) -> None:
    init()
    drive = sandbox.user / ICLOUD_REL
    ok("root.add", path=str(drive), kind="icloud_drive")
    ok("root.add", path=str(drive / "Desktop"), kind="desktop")
    ok("scan.run")
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    rows = conn.execute(
        "SELECT root_id, count(*) FROM file_entries WHERE path LIKE ? GROUP BY root_id",
        (str(drive / "Desktop") + "/%",),
    ).fetchall()
    dup = conn.execute(
        "SELECT count(*) FROM (SELECT dev, inode FROM file_entries WHERE present=1 "
        "GROUP BY dev, inode HAVING count(*) > 1)"
    ).fetchone()
    conn.close()
    assert rows == [(2, 1)] and dup[0] == 0


def test_same_directory_registered_twice_scanned_once(sandbox: Sandbox, now: Any) -> None:
    """E11c: two roots with the same (dev, inode) - only the smallest id is traversed."""
    init()
    build_sandbox(sandbox.root, "minimal", now=now)
    dl = sandbox.user / "Downloads"
    alias = sandbox.user / "dl-alias"
    alias.symlink_to(dl)
    ok("root.add", path=str(dl), kind="downloads")
    ok("root.add", path=str(alias), kind="custom")
    data = ok("scan.run")
    assert data["stats"]["duplicate_roots"] == 1 and data["stats"]["baseline_entries"] == 3
    assert data["roots"][1] == {
        "root_id": "root_2",
        "status": "ok",
        "entries_seen": 0,
        "duplicate_of": "root_1",
    }


def test_exclude_globs_relative_to_root(sandbox: Sandbox, icloud_tree: Any) -> None:
    init()
    drive = sandbox.user / ICLOUD_REL
    ok("root.add", path=str(drive), kind="icloud_drive")
    ok("scan.run")
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    names = {r[0] for r in conn.execute("SELECT name FROM file_entries")}
    conn.close()
    # The root lives under ~/Library/... yet is scanned; the inner Library/ folder's interior
    # is excluded by **/Library/** while the folder entry itself is kept.
    assert {"plan.txt", "Library", "Desktop", "on-desktop.txt"} <= names
    assert "inner.txt" not in names


def test_legacy_placeholder_download_is_not_an_event(sandbox: Sandbox, icloud_tree: Any) -> None:
    init()
    drive = sandbox.user / ICLOUD_REL
    ok("root.add", path=str(drive), kind="icloud_drive")
    ok("scan.run")
    placeholder = drive / ".계약서.pdf.icloud"
    placeholder.unlink()
    (drive / "계약서.pdf").write_bytes(b"%PDF-1.4 downloaded")
    data = ok("scan.run")
    s = data["stats"]
    assert (s["created"], s["deleted"], s["moved"]) == (0, 0, 0)


def test_dataless_dir_not_listed(sandbox: Sandbox, now: Any) -> None:
    """E11a: a dataless directory is never scandir'ed; its entries stay present."""
    init()
    drive = sandbox.mkdir(ICLOUD_REL)
    folder = drive / "Photos"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"a")
    ok("root.add", path=str(drive), kind="icloud_drive")
    ok("scan.run")
    listed: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "os.scandir" and args and str(args[0]) == str(folder):
            listed.append(str(args[0]))

    sys.addaudithook(audit)
    fs_collector.flags_hook = lambda p, f: f | paths.SF_DATALESS if p == str(folder) else f
    data = ok("scan.run")
    assert listed == [] and data["stats"]["dataless_dirs"] == 1
    assert data["stats"]["deleted"] == 0


def test_dataless_flag_flip_is_not_an_event(sandbox: Sandbox, icloud_tree: Any) -> None:
    """E11b: downloaded <-> dataless with the same inode/size/mtime -> flags only."""
    init()
    drive = sandbox.user / ICLOUD_REL
    ok("root.add", path=str(drive), kind="icloud_drive")
    ok("scan.run")
    fs_collector.flags_hook = None  # everything is "downloaded" now
    data = ok("scan.run")
    assert data["stats"]["modified"] == 0 and data["stats"]["dataless_skipped"] == 1
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    flagged = conn.execute("SELECT count(*) FROM file_entries WHERE flags & 1073741824").fetchone()
    conn.close()
    assert flagged[0] == 0


def test_icloud_root_flag_recomputed_each_scan(sandbox: Sandbox) -> None:
    init()
    desk = sandbox.mkdir("Desktop")
    ok("root.add", path=str(desk), kind="desktop", icloud_synced="no")
    roots = ok("root.list")["items"]
    assert (roots[0]["icloud_synced"], roots[0]["icloud_synced_source"]) == (False, "user")
    sandbox.mkdir(ICLOUD_REL + "/Desktop")  # S2 live signal appears
    ok("scan.run")
    roots = ok("root.list")["items"]
    assert (roots[0]["icloud_synced"], roots[0]["icloud_synced_source"]) == (True, "detected")


def test_icloud_synced_desktop_documents(sandbox: Sandbox) -> None:
    """ "Desktop & Documents" sync mimicked with symlinks into CloudDocs (root values only)."""
    init()
    drive = sandbox.mkdir(ICLOUD_REL)
    for name in ("Desktop", "Documents"):
        (drive / name).mkdir()
        (sandbox.user / name).symlink_to(drive / name)
    ok("root.add", path=str(sandbox.user / "Desktop"), kind="desktop")
    ok("root.add", path=str(sandbox.user / "Documents"), kind="documents")
    ok("scan.run")
    roots = {r["kind"]: r for r in ok("root.list")["items"]}
    for kind in ("desktop", "documents"):
        assert (roots[kind]["icloud_synced"], roots[kind]["icloud_synced_source"]) == (
            True,
            "detected",
        )


def test_plain_desktop_not_synced_only_when_user_says_no(sandbox: Sandbox) -> None:
    """Without any signal a desktop root is *assumed* synced (V17 undecided); `no` -> 0."""
    init()
    desk = sandbox.mkdir("Desktop")
    ok("root.add", path=str(desk), kind="desktop")
    ok("scan.run")
    root = ok("root.list")["items"][0]
    assert (root["icloud_synced"], root["icloud_synced_source"]) == (True, "assumed")
    other = sandbox.mkdir("Desk2")
    ok("root.add", path=str(other), kind="desktop", icloud_synced="no")
    ok("scan.run")
    second = ok("root.list")["items"][1]
    assert (second["icloud_synced"], second["icloud_synced_source"]) == (False, "user")


def test_nested_roots_pruned_by_identity_not_path(sandbox: Sandbox, now: Any) -> None:
    """The iCloud Desktop folder and ~/Desktop (a symlink to it) are one tree, scanned once."""
    init()
    drive = sandbox.mkdir(ICLOUD_REL)
    (drive / "Desktop").mkdir()
    (drive / "Desktop" / "shot.png").write_bytes(b"png")
    (drive / "top.txt").write_text("t")
    (sandbox.user / "Desktop").symlink_to(drive / "Desktop")
    ok("root.add", path=str(drive), kind="icloud_drive")
    ok("root.add", path=str(sandbox.user / "Desktop"), kind="desktop")
    ok("scan.run")
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    rows = conn.execute("SELECT root_id, name FROM file_entries ORDER BY name").fetchall()
    conn.close()
    assert rows == [(2, "shot.png"), (1, "top.txt")]


def test_fr_core_008_legacy_placeholder_is_dataless(sandbox: Sandbox) -> None:
    """`.<name>.icloud` counts as dataless and is never opened (display_name is M2)."""
    init()
    drive = sandbox.mkdir(ICLOUD_REL)
    placeholder = drive / ".계약서.pdf.icloud"
    placeholder.write_bytes(b"bplist00")
    ok("root.add", path=str(drive), kind="icloud_drive")
    opened: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args and args[0] == str(placeholder):
            opened.append(event)

    sys.addaudithook(audit)
    ok("scan.run")
    placeholder.write_bytes(b"bplist00 changed")
    opened.clear()  # the test's own write above
    data = ok("scan.run")
    assert data["stats"]["dataless_skipped"] == 1 and opened == []


def test_root_add_reports_identity_overlap(sandbox: Sandbox) -> None:
    init()
    real = sandbox.mkdir("Desktop")
    alias = sandbox.user / "Alias"
    alias.symlink_to(real)
    first = ok("root.add", path=str(real), kind="desktop")["root"]
    second = ok("root.add", path=str(alias), kind="custom")["root"]
    assert second["overlaps"] == [first["id"]]  # same directory under another spelling
    (real / "sub").mkdir()
    inner = ok("root.add", path=str(alias / "sub"), kind="custom")["root"]
    assert set(inner["overlaps"]) == {first["id"], second["id"]}


def test_selected_duplicate_root_is_not_traversed(sandbox: Sandbox, now: Any) -> None:
    init()
    build_sandbox(sandbox.root, "minimal", now=now)
    dl = sandbox.user / "Downloads"
    alias = sandbox.user / "dl-alias"
    alias.symlink_to(dl)
    ok("root.add", path=str(dl), kind="downloads")
    ok("root.add", path=str(alias), kind="custom")
    ok("scan.run", root_ids=["root_1"])
    data = ok("scan.run", root_ids=["root_2"])
    assert data["roots"] == [
        {"root_id": "root_2", "status": "ok", "entries_seen": 0, "duplicate_of": "root_1"}
    ]
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    owners = {r[0] for r in conn.execute("SELECT root_id FROM file_entries")}
    conn.close()
    assert owners == {1}


def test_state_dir_excluded_by_identity(sandbox: Sandbox) -> None:
    """A root that contains DAYCLOSE_HOME under another spelling still skips it."""
    init()
    link = sandbox.user / "via-link"
    link.symlink_to(sandbox.root)
    ok("root.add", path=str(link), kind="custom")
    ok("scan.run")
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    names = {r[0] for r in conn.execute("SELECT name FROM file_entries")}
    conn.close()
    assert "dayclose.db" not in names and "config.toml" not in names


def test_unreachable_inner_root_not_entered_by_outer(sandbox: Sandbox) -> None:
    init(scan__volume_probe_timeout_s=1)
    outer = sandbox.mkdir("Outer")
    inner = sandbox.mkdir("Outer/Inner")
    (inner / "f.txt").write_text("x")
    ok("root.add", path=str(outer), kind="custom")
    ok("root.add", path=str(inner), kind="custom")
    real = paths._default_probe_stat

    def probe_stat(path: str) -> None:
        if path == str(inner):
            raise PermissionError(errno.EPERM, "denied", path)
        real(path)

    paths.probe_stat = probe_stat
    listed: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "os.scandir" and args and str(args[0]) == str(inner):
            listed.append(event)

    sys.addaudithook(audit)
    env, code = run("scan.run")
    assert code == 0 and listed == []
