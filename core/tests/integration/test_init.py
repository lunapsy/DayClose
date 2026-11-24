"""FR-CORE-001 / FR-CORE-002: init, default roots, root add/remove/list."""

from __future__ import annotations

import os
import stat
from datetime import datetime

from conftest import RunCli, Sandbox
from fixtures.sandbox import ICLOUD_REL, install_fake_tool, tool_calls


def _mode(p: str) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_fr_core_001_init_idempotent(cli: RunCli, sandbox: Sandbox) -> None:
    first = cli("init", "--no-default-roots", "--device-name", "Test Mac")
    assert first.returncode == 0, first.stdout
    d1 = first.data
    assert d1["created"] is True and d1["migrated_from"] is None
    assert d1["db_schema_version"] == 1 and d1["device_name"] == "Test Mac"
    config_before = (sandbox.home / "config.toml").read_bytes()
    second = cli("init", "--no-default-roots", "--device-name", "Other")
    assert second.returncode == 0
    d2 = second.data
    assert d2["created"] is False
    assert d2["device_id"] == d1["device_id"]
    assert d2["device_name"] == "Test Mac"  # existing config is never overwritten
    assert (sandbox.home / "config.toml").read_bytes() == config_before
    assert first.envelope["meta"]["device_id"] == d1["device_id"]


def test_fr_core_001_home_0700_db_0600(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    assert _mode(str(sandbox.home)) == 0o700
    assert _mode(str(sandbox.home / "dayclose.db")) == 0o600
    assert _mode(str(sandbox.home / "config.toml")) == 0o600
    for suffix in ("-wal", "-shm"):
        p = str(sandbox.home / "dayclose.db") + suffix
        if os.path.exists(p):
            assert _mode(p) == 0o600


def test_fr_core_002_default_roots_in_fake_home(cli: RunCli, sandbox: Sandbox) -> None:
    for rel in ("Downloads", "Desktop", "Documents", ICLOUD_REL, "dev"):
        sandbox.mkdir(rel)
    install_fake_tool(sandbox.root, "defaults", returncode=1)  # key absent -> Desktop
    res = cli("init")
    assert res.returncode == 0, res.stdout
    added = {r["kind"]: r["path"] for r in res.data["roots_added"]}
    assert added == {
        "downloads": str(sandbox.user / "Downloads"),
        "desktop": str(sandbox.user / "Desktop"),
        "documents": str(sandbox.user / "Documents"),
        "icloud_drive": str(sandbox.user / ICLOUD_REL),
        "projects": str(sandbox.user / "dev"),
    }
    roots = {r["kind"]: r for r in cli("root", "list").data["items"]}
    assert roots["projects"]["file_level"] is False and roots["projects"]["max_depth"] == 2
    assert roots["downloads"]["max_depth"] == 6 and roots["documents"]["max_depth"] == 8
    assert roots["icloud_drive"]["icloud_synced"] is True
    # Re-running init adds nothing new.
    again = cli("init")
    assert again.data["roots_added"] == []


def test_fr_core_002_missing_root_warns(cli: RunCli, sandbox: Sandbox) -> None:
    sandbox.mkdir("Downloads")
    install_fake_tool(sandbox.root, "defaults", returncode=1)
    res = cli("init")
    assert res.returncode == 0
    kinds = [r["kind"] for r in res.data["roots_added"]]
    assert kinds == ["downloads"]
    skipped = {os.path.basename(s["path"]) for s in res.data["roots_skipped"]}
    assert {"Desktop", "Documents", "dev"} <= skipped
    assert all(s["reason"] == "missing" for s in res.data["roots_skipped"])
    codes = [w["code"] for w in res.envelope["warnings"]]
    assert codes.count("W_ROOT_UNAVAILABLE") == len(res.data["roots_skipped"])


def test_fr_core_002_screenshot_location_differs(cli: RunCli, sandbox: Sandbox) -> None:
    for rel in ("Downloads", "Desktop", "Pictures/Screenshots"):
        sandbox.mkdir(rel)
    install_fake_tool(sandbox.root, "defaults", stdout="~/Pictures/Screenshots\n")
    res = cli("init")
    assert res.returncode == 0
    shots = [r for r in res.data["roots_added"] if r["kind"] == "screenshots"]
    assert shots == [
        {
            "id": shots[0]["id"],
            "path": str(sandbox.user / "Pictures/Screenshots"),
            "kind": "screenshots",
        }
    ]
    calls = tool_calls(sandbox.root)
    assert calls[0]["argv"] == ["read", "com.apple.screencapture", "location"]
    # run_tool builds a fixed minimal environment (02 §6): nothing inherited from the caller.
    assert set(calls[0]["env"]) <= {"PATH", "LANG", "HOME", "TMPDIR", "__CF_USER_TEXT_ENCODING"}


def test_fr_core_002_screenshot_inside_desktop_not_registered(
    cli: RunCli, sandbox: Sandbox
) -> None:
    sandbox.mkdir("Desktop/Shots")
    install_fake_tool(sandbox.root, "defaults", stdout=str(sandbox.user / "Desktop/Shots"))
    res = cli("init")
    assert [r["kind"] for r in res.data["roots_added"]] == ["desktop"]


def test_default_roots_never_under_volumes(cli: RunCli, sandbox: Sandbox) -> None:
    for rel in ("Downloads", "Desktop", "Documents", ICLOUD_REL, "dev"):
        sandbox.mkdir(rel)
    install_fake_tool(sandbox.root, "defaults", stdout="/Volumes/External/Shots")
    res = cli("init")
    assert res.returncode == 0
    for r in res.data["roots_added"]:
        assert r["path"].startswith(str(sandbox.user) + "/")
    assert not any(r["kind"] == "screenshots" for r in res.data["roots_added"])


def test_fr_core_002_root_add_remove_list(cli: RunCli, sandbox: Sandbox, now: datetime) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    dl = sandbox.mkdir("Downloads")
    added = cli("root", "add", str(dl), "--kind", "downloads")
    assert added.returncode == 0
    root = added.data["root"]
    assert added.data["created"] is True and root["display_path"] == "~/Downloads"
    assert root["max_depth"] == 6 and root["file_level"] is True
    again = cli("root", "add", str(dl), "--kind", "downloads")
    assert again.data["created"] is False and again.data["root"]["id"] == root["id"]
    inner = sandbox.mkdir("Downloads/inner")
    nested = cli("root", "add", str(inner), "--kind", "custom")
    assert nested.data["root"]["overlaps"] == [root["id"]]
    listed = cli("root", "list").data
    assert listed["total"] == 2 and listed["next_cursor"] is None
    removed = cli("root", "remove", root["id"])
    assert removed.returncode == 0 and removed.data["root_id"] == root["id"]
    assert [r["id"] for r in cli("root", "list").data["items"]] == [nested.data["root"]["id"]]
    with_all = cli("root", "list", "--all").data["items"]
    assert len(with_all) == 2 and with_all[0]["removed_at"] is not None
    assert cli("root", "remove", root["id"]).returncode == 3  # already removed -> E_NOT_FOUND


def test_root_add_max_depth_default_per_kind(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    expected = {
        "downloads": (6, True),
        "desktop": (6, True),
        "screenshots": (2, True),
        "documents": (8, True),
        "icloud_drive": (8, True),
        "projects": (2, False),
        "custom": (6, True),
    }
    for kind, (depth, level) in expected.items():
        root = cli("root", "add", str(sandbox.mkdir(f"k-{kind}")), "--kind", kind).data["root"]
        assert (root["max_depth"], root["file_level"]) == (depth, level), kind
    explicit = cli(
        "root", "add", str(sandbox.mkdir("k-x")), "--kind", "custom", "--max-depth", "1"
    ).data["root"]
    assert explicit["max_depth"] == 1


def test_root_add_stores_icloud_synced_mode(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    for mode in ("auto", "yes", "no"):
        root = cli(
            "root",
            "add",
            str(sandbox.mkdir(f"m-{mode}")),
            "--kind",
            "custom",
            "--icloud-synced",
            mode,
        ).data["root"]
        assert root["icloud_synced_mode"] == mode
    assert (
        cli(
            "root",
            "add",
            str(sandbox.mkdir("m-bad")),
            "--kind",
            "custom",
            "--icloud-synced",
            "maybe",
        ).returncode
        == 2
    )


def test_init_does_not_scan(cli: RunCli, sandbox: Sandbox) -> None:
    import sqlite3

    sandbox.mkdir("Downloads")
    assert cli("init").returncode == 0
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    counts = [
        conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("scan_runs", "file_entries", "file_events")
    ]
    conn.close()
    assert counts == [0, 0, 0]


def test_init_does_not_create_field_key(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    names = {p.name for p in sandbox.home.iterdir()}
    assert not any("key" in n for n in names), names  # no test-field-key / key material
    assert names <= {
        "config.toml",
        "dayclose.db",
        "dayclose.db-wal",
        "dayclose.db-shm",
        "state.lock",
        "logs",
    }


def test_fr_core_007_concurrent_writes_one_locked(cli: RunCli, sandbox: Sandbox) -> None:
    import fcntl
    import os as _os

    assert cli("init", "--no-default-roots").returncode == 0
    fd = _os.open(sandbox.home / "state.lock", _os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        first = cli("root", "add", str(sandbox.mkdir("A")), "--kind", "custom", "--wait-lock", "0")
        second = cli(
            "root", "add", str(sandbox.mkdir("B")), "--kind", "custom", "--wait-lock", "0.2"
        )
        for res in (first, second):
            assert res.returncode == 7 and res.envelope["error"]["code"] == "E_LOCKED"
            assert res.envelope["error"]["retryable"] is True
    finally:
        _os.close(fd)
    assert cli("root", "add", str(sandbox.mkdir("A")), "--kind", "custom").returncode == 0
    assert cli("root", "list").data["total"] == 1


def test_root_add_errors(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    missing = cli("root", "add", str(sandbox.user / "nope"), "--kind", "custom")
    assert (missing.returncode, missing.envelope["error"]["code"]) == (3, "E_NOT_FOUND")
    f = sandbox.user / "file.txt"
    f.write_text("x")
    not_dir = cli("root", "add", str(f), "--kind", "custom")
    assert (not_dir.returncode, not_dir.envelope["error"]["code"]) == (2, "E_USAGE")
    outside = cli("root", "add", "/usr", "--kind", "custom")
    assert (outside.returncode, outside.envelope["error"]["code"]) == (5, "E_SANDBOX_VIOLATION")
    bad_id = cli("root", "remove", "run_1")
    assert (bad_id.returncode, bad_id.envelope["error"]["code"]) == (2, "E_USAGE")


def test_root_icloud_override_precedence(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    plain = sandbox.mkdir("Plain")
    yes = cli("root", "add", str(plain), "--kind", "custom", "--icloud-synced", "yes").data
    assert (yes["root"]["icloud_synced"], yes["root"]["icloud_synced_source"]) == (True, "user")
    drive_sub = sandbox.mkdir(ICLOUD_REL + "/Projects")
    link = sandbox.user / "linked"
    link.symlink_to(drive_sub)
    no = cli("root", "add", str(link), "--kind", "custom", "--icloud-synced", "no").data["root"]
    # A positive live signal (realpath under Mobile Documents) beats the user's `no`.
    assert (no["icloud_synced"], no["icloud_synced_source"]) == (True, "detected")
    other = sandbox.mkdir("Other")
    no2 = cli("root", "add", str(other), "--kind", "custom", "--icloud-synced", "no").data["root"]
    assert (no2["icloud_synced"], no2["icloud_synced_source"]) == (False, "user")
    auto = cli("root", "add", str(sandbox.mkdir("Auto")), "--kind", "custom").data["root"]
    assert (auto["icloud_synced"], auto["icloud_synced_source"]) == (False, "detected")


def test_root_icloud_assumed_default(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    desk = cli("root", "add", str(sandbox.mkdir("Desktop")), "--kind", "desktop").data["root"]
    docs = cli("root", "add", str(sandbox.mkdir("Documents")), "--kind", "documents").data["root"]
    dl = cli("root", "add", str(sandbox.mkdir("Downloads")), "--kind", "downloads").data["root"]
    assert (desk["icloud_synced"], desk["icloud_synced_source"]) == (True, "assumed")
    assert (docs["icloud_synced"], docs["icloud_synced_source"]) == (True, "assumed")
    assert (dl["icloud_synced"], dl["icloud_synced_source"]) == (False, "detected")
    for r in cli("root", "list").data["items"]:
        assert {"icloud_synced", "icloud_synced_mode", "icloud_synced_source"} <= set(r)
