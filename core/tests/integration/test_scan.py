"""FR-CORE-003: incremental change detection through the real CLI (subprocess)."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from conftest import RunCli, Sandbox
from fixtures.sandbox import build_sandbox


def _add_root(cli: RunCli, path: Path, kind: str = "downloads") -> str:
    res = cli("root", "add", str(path), "--kind", kind)
    assert res.returncode == 0, res.stdout
    rid: str = res.data["root"]["id"]
    return rid


def _scan(cli: RunCli, *extra: str) -> dict[str, Any]:
    res = cli("scan", "run", *extra)
    assert res.returncode == 0, res.stdout + res.stderr
    data: dict[str, Any] = res.data
    return data


def _events(cli: RunCli, run_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = cli("change", "list", "--run", run_id).data["items"]
    return items


def _touch_later(p: Path, seconds: float = 5.0) -> None:
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


def test_fr_core_003_create_modify_delete_rename_one_event_each(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "minimal", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    base = _scan(cli)
    assert base["stats"]["baseline_entries"] == 3 and base["stats"]["created"] == 0

    (dl / "new.txt").write_text("hello")
    run = _scan(cli)
    assert (
        run["stats"]["created"],
        run["stats"]["modified"],
        run["stats"]["deleted"],
        run["stats"]["moved"],
    ) == (1, 0, 0, 0)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], e["new_path"]) for e in ev] == [("created", str(dl / "new.txt"))]

    with open(dl / "notes.txt", "ab") as fh:
        fh.write(b"more")
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], e["new_path"], e["size_delta"]) for e in ev] == [
        ("modified", str(dl / "notes.txt"), 4)
    ]

    (dl / "photo.jpg").unlink()
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], e["old_path"]) for e in ev] == [("deleted", str(dl / "photo.jpg"))]

    (dl / "report.pdf").rename(dl / "report-final.pdf")
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], e["old_path"], e["new_path"]) for e in ev] == [
        ("moved", str(dl / "report.pdf"), str(dl / "report-final.pdf"))
    ]
    assert ev[0]["display_path"] == "~/Downloads" and ev[0]["id"].startswith("evt_")


def test_fr_core_003_rescan_no_events(initialized: RunCli, sandbox: Sandbox, now: datetime) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    _add_root(cli, sandbox.user / "Downloads")
    _scan(cli)
    for _ in range(2):
        run = _scan(cli)
        s = run["stats"]
        assert (s["created"], s["modified"], s["deleted"], s["moved"]) == (0, 0, 0, 0)
        assert _events(cli, run["run_id"]) == []


def test_fr_core_003_package_dir_single_entry(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    _scan(cli)
    # Changing a file inside the package is not an event (only the package's own mtime).
    with open(dl / "Thing.app" / "Contents" / "MacOS" / "thing", "ab") as fh:
        fh.write(b"update")
    run = _scan(cli)
    assert run["stats"]["modified"] == 0
    (dl / "Thing.app").rename(dl / "Thing2.app")
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], e["kind"]) for e in ev] == [("moved", "package")]


def test_fr_core_003_excludes_ds_store_node_modules_git(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    base = _scan(cli)
    # a b c, proj, proj/README.md, proj/node_modules (entry, interior skipped), repo (pruned
    # work tree), Thing.app, deep, deep/one, deep/one/two, deep/one/two/three.txt
    assert base["stats"]["baseline_entries"] == 12
    (dl / ".DS_Store").write_bytes(b"\x01" * 16)
    (dl / "proj" / "node_modules" / "left-pad" / "index.js").write_text("changed")
    (dl / "repo" / "src" / "main.py").write_text("print(2)\n")
    (dl / "._a.txt").write_bytes(b"appledouble")
    run = _scan(cli)
    s = run["stats"]
    assert (s["created"], s["modified"], s["deleted"], s["moved"]) == (0, 0, 0, 0)


def test_fr_core_003_safe_save_is_one_modified(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "minimal", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    _scan(cli)
    tmp = dl / ".notes.txt.swp"
    tmp.write_text("rewritten by an editor")
    os.replace(tmp, dl / "notes.txt")  # same path, new inode (E2)
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [e["event"] for e in ev] == ["modified"]


def test_fr_core_003_inode_reuse_is_not_a_move(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    dl = sandbox.mkdir("Downloads")
    _add_root(cli, dl)
    _scan(cli)
    created = []
    for i in range(20):  # make inode reuse likely (E3)
        p = dl / f"x{i}.txt"
        p.write_text("x")
        created.append(p)
    _scan(cli)
    for p in created:
        p.unlink()
    time.sleep(0.01)
    for i in range(20):
        (dl / f"y{i}.txt").write_text("y")
    run = _scan(cli)
    s = run["stats"]
    assert (s["created"], s["deleted"], s["moved"]) == (20, 20, 0)


def test_fr_core_003_hardlink_rename_path_matched(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    dl = sandbox.mkdir("Downloads")
    (dl / "one.txt").write_text("linked")
    os.link(dl / "one.txt", dl / "two.txt")
    _add_root(cli, dl)
    _scan(cli)
    (dl / "two.txt").rename(dl / "three.txt")  # E4: nlink>1 -> no identity matching
    run = _scan(cli)
    ev = sorted(e["event"] for e in _events(cli, run["run_id"]))
    assert ev == ["created", "deleted"]
    assert all(e["old_path"] != str(dl / "one.txt") for e in _events(cli, run["run_id"]))


def test_dir_rename_is_one_event(initialized: RunCli, sandbox: Sandbox, now: datetime) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    _scan(cli)
    (dl / "deep").rename(dl / "shallow")  # E8
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], e["kind"], e["new_path"]) for e in ev] == [
        ("moved", "dir", str(dl / "shallow"))
    ]
    again = _scan(cli)
    assert again["stats"]["created"] == again["stats"]["deleted"] == 0


def test_crdownload_lineage_kept(initialized: RunCli, sandbox: Sandbox) -> None:
    """E7/E7a: an in-progress download is an entry; finishing it is one `moved`."""
    cli = initialized
    dl = sandbox.mkdir("Downloads")
    _add_root(cli, dl)
    _scan(cli)
    part = dl / "big.zip.crdownload"
    part.write_bytes(b"partial")
    run = _scan(cli)
    assert [e["event"] for e in _events(cli, run["run_id"])] == ["created"]
    with open(part, "ab") as fh:
        fh.write(b" more")
    part.rename(dl / "big.zip")
    run = _scan(cli)
    ev = _events(cli, run["run_id"])
    assert [(e["event"], os.path.basename(e["new_path"])) for e in ev] == [("moved", "big.zip")]


def test_settle_never_suppresses_entries_or_events(cli: RunCli, sandbox: Sandbox) -> None:
    """settle_seconds=60 (default) only delays M2 item creation, never entries/events."""
    assert cli("init", "--no-default-roots").returncode == 0
    assert cli("config", "get", "scan.settle_seconds").data["value"] == 60
    dl = sandbox.mkdir("Downloads")
    _add_root(cli, dl)
    _scan(cli)
    (dl / "a.txt").write_text("hi\n")  # the 12 M1b demo order
    run = _scan(cli)
    assert run["stats"]["created"] == 1
    (dl / "a.txt").rename(dl / "b.txt")
    run = _scan(cli)
    assert (run["stats"]["moved"], run["stats"]["created"], run["stats"]["deleted"]) == (1, 0, 0)


def test_permission_denied_subtree_keeps_entries(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    _scan(cli)
    locked = dl / "deep" / "one"
    locked.chmod(0)
    try:
        res = cli("scan", "run")
        assert res.returncode == 0
        run = res.data
        assert run["status"] == "partial" and run["roots"][0]["status"] == "partial"
        assert run["stats"]["deleted"] == 0  # E9: unreadable != deleted
        assert run["stats"]["skipped_unreadable"] == 1
        warns = {w["code"]: w for w in res.envelope["warnings"]}
        assert warns["W_PERMISSION_SKIPPED"]["details"]["count"] == 1
    finally:
        locked.chmod(0o755)
    run = _scan(cli)
    assert (run["stats"]["created"], run["stats"]["deleted"]) == (0, 0)


def test_max_depth_limits_descent(initialized: RunCli, sandbox: Sandbox, now: datetime) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    dl = sandbox.user / "Downloads"
    res = cli("root", "add", str(dl), "--kind", "downloads", "--max-depth", "1")
    assert res.returncode == 0
    run = _scan(cli)
    # depth 1 dirs are entered: a b c proj proj/README proj/node_modules repo Thing.app deep
    # deep/one (dir recorded, not entered)
    assert run["stats"]["baseline_entries"] == 10


def test_truncated_root_does_not_delete(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "tree", now=now)
    _add_root(cli, sandbox.user / "Downloads")
    _scan(cli)
    assert cli("config", "set", "scan.max_entries_per_root", "3").returncode == 0
    res = cli("scan", "run")
    run = res.data
    assert run["status"] == "partial" and run["stats"]["deleted"] == 0
    assert any(w["code"] == "W_TRUNCATED" for w in res.envelope["warnings"])


def test_interrupted_run_is_marked(initialized: RunCli, sandbox: Sandbox) -> None:
    """E21: a run left `running` (crash) becomes `interrupted` at the next scan start."""
    import sqlite3

    cli = initialized
    dl = sandbox.mkdir("Downloads")
    _add_root(cli, dl)
    _scan(cli)
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    conn.execute(
        'INSERT INTO scan_runs(started_at, status, "trigger", collectors_json) '
        "VALUES (1, 'running', 'manual', '[\"fs\"]')"
    )
    conn.commit()
    conn.close()
    _scan(cli)
    statuses = [r["status"] for r in cli("scan", "list").data["items"]]
    assert "interrupted" in statuses and "running" not in statuses


def test_scan_list_show_and_pagination(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    _add_root(cli, sandbox.mkdir("Downloads"))
    runs = [_scan(cli)["run_id"] for _ in range(3)]
    page1 = cli("scan", "list", "--limit", "2").data
    assert [r["run_id"] for r in page1["items"]] == runs[::-1][:2]
    assert page1["total"] == 3 and page1["next_cursor"]
    page2 = cli("scan", "list", "--limit", "2", "--cursor", page1["next_cursor"]).data
    assert [r["run_id"] for r in page2["items"]] == [runs[0]] and page2["next_cursor"] is None
    shown = cli("scan", "show", runs[0]).data
    assert shown["run_id"] == runs[0] and shown["started_at"] and shown["error_code"] is None
    assert shown["roots"][0]["root_id"] == "root_1"
    assert cli("scan", "show", "run_999").returncode == 3
    bad = cli("scan", "list", "--limit", "0")
    assert bad.returncode == 2


def test_change_list_filters(initialized: RunCli, sandbox: Sandbox, now: datetime) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "minimal", now=now)
    dl = sandbox.user / "Downloads"
    other = sandbox.mkdir("Desktop")
    r1 = _add_root(cli, dl)
    r2 = _add_root(cli, other, "custom")
    _scan(cli)
    for i in range(3):
        (dl / f"n{i}.txt").write_text("n")
    (other / "d.txt").write_text("d")
    (dl / "notes.txt").unlink()
    run = _scan(cli)
    latest = cli("change", "list").data
    assert latest["total"] == 5
    created = cli("change", "list", "--event", "created", "--root", r1).data
    assert created["total"] == 3
    in_r2 = cli("change", "list", "--root", r2).data
    assert [e["new_path"] for e in in_r2["items"]] == [str(other / "d.txt")]
    p1 = cli("change", "list", "--run", run["run_id"], "--limit", "2").data
    p2 = cli(
        "change", "list", "--run", run["run_id"], "--limit", "2", "--cursor", p1["next_cursor"]
    ).data
    p3 = cli(
        "change", "list", "--run", run["run_id"], "--limit", "2", "--cursor", p2["next_cursor"]
    ).data
    ids = [e["id"] for e in p1["items"] + p2["items"] + p3["items"]]
    assert len(ids) == len(set(ids)) == 5 and p3["next_cursor"] is None
    mismatch = cli("change", "list", "--event", "deleted", "--cursor", p1["next_cursor"])
    assert mismatch.returncode == 2
    assert mismatch.envelope["error"]["details"]["reason"] == "cursor_mismatch"
    since = cli("change", "list", "--since", "2000-01-01T00:00:00Z").data
    assert since["total"] == 5
    both = cli("change", "list", "--run", run["run_id"], "--since", "2000-01-01")
    assert both.returncode == 2
    assert cli("change", "list", "--event", "renamed").returncode == 2


def test_scan_root_subset_and_unknown_root(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    r1 = _add_root(cli, sandbox.mkdir("Downloads"))
    _add_root(cli, sandbox.mkdir("Desktop"), "custom")
    run = _scan(cli, "--root", r1)
    assert [r["root_id"] for r in run["roots"]] == [r1]
    missing = cli("scan", "run", "--root", "root_99")
    assert missing.returncode == 3
    nyi = cli("scan", "run", "--collectors", "fs,git")
    assert nyi.returncode == 2
    assert nyi.envelope["error"]["details"] == {
        "reason": "not_implemented",
        "collector": "git",
        "milestone": "M2",
    }


def test_missing_root_is_skipped_and_entries_kept(
    initialized: RunCli, sandbox: Sandbox, now: datetime
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "minimal", now=now)
    dl = sandbox.user / "Downloads"
    _add_root(cli, dl)
    keep = sandbox.mkdir("Desktop")
    _add_root(cli, keep, "custom")
    _scan(cli)
    dl.rename(sandbox.user / "Downloads-away")  # E10: like an unplugged volume
    res = cli("scan", "run")
    assert res.returncode == 0
    assert res.data["status"] == "partial" and res.data["stats"]["deleted"] == 0
    assert [w["code"] for w in res.envelope["warnings"]] == ["W_ROOT_UNAVAILABLE"]
    (sandbox.user / "Downloads-away").rename(dl)
    back = _scan(cli)
    assert back["stats"]["created"] == back["stats"]["deleted"] == 0


def test_all_roots_failed_is_an_error(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    dl = sandbox.mkdir("Downloads")
    _add_root(cli, dl)
    dl.rmdir()
    res = cli("scan", "run")
    assert res.returncode == 6
    assert res.envelope["error"]["code"] == "E_VOLUME_UNAVAILABLE"
    assert cli("scan", "list").data["items"][0]["status"] == "failed"


def test_progress_ndjson_on_stderr(initialized: RunCli, sandbox: Sandbox, now: datetime) -> None:
    import json

    cli = initialized
    build_sandbox(sandbox.root, "perf_10k", now=now)
    _add_root(cli, sandbox.user / "Downloads")
    res = cli("scan", "run", "--progress", "ndjson")
    assert res.returncode == 0
    events = [json.loads(line) for line in res.stderr.splitlines() if line.startswith("{")]
    assert events and all(e["event"] == "progress" and e["phase"] == "fs" for e in events)
    assert len(res.stdout.splitlines()) == 1


def test_human_output(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    _add_root(cli, sandbox.mkdir("Downloads"))
    res = cli("scan", "run", "--home", str(sandbox.home), json_mode=False)
    assert res.returncode == 0 and res.stdout.startswith("스캔 run_1 (완료")
    err = cli("scan", "show", "run_9", "--home", str(sandbox.home), json_mode=False)
    assert err.returncode == 3 and err.stdout == ""
    assert err.stderr.startswith("오류(E_NOT_FOUND)")


def test_schedule_channel_may_scan(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    _add_root(cli, sandbox.mkdir("Downloads"))
    ran = cli("scan", "run", "--channel", "schedule")
    assert ran.returncode == 0 and ran.data["trigger"] == "schedule"
