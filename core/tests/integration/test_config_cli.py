"""config.get / config.set / config.list through the CLI (10 §2.2)."""

from __future__ import annotations

import tomllib

from conftest import RunCli, Sandbox


def test_config_get_set_list(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    got = cli("config", "get", "review.day_boundary").data
    assert got == {
        "key": "review.day_boundary",
        "value": "04:00",
        "default": "04:00",
        "source": "default",
    }
    res = cli("config", "set", "review.daily_time", "20:30")
    assert res.data == {"key": "review.daily_time", "old_value": "21:00", "value": "20:30"}
    assert cli("config", "get", "review.daily_time").data["source"] == "file"
    res = cli("config", "set", "projects.roots", '["~/dev", "~/src"]')
    assert res.data["value"] == ["~/dev", "~/src"]
    on_disk = tomllib.loads((sandbox.home / "config.toml").read_text())
    assert on_disk["review"]["daily_time"] == "20:30"
    assert on_disk["projects"]["roots"] == ["~/dev", "~/src"]
    listed = cli("config", "list").data
    assert listed["next_cursor"] is None and listed["total"] == len(listed["items"])
    assert {i["key"] for i in listed["items"]} >= {"scan.settle_seconds", "archive.root"}


def test_config_set_errors(initialized: RunCli) -> None:
    cli = initialized
    ro = cli("config", "set", "device_id", "dev_x")
    assert ro.returncode == 2 and ro.envelope["error"]["details"]["reason"] == "read_only"
    fixed = cli("config", "set", "scan.read_dataless", "true")
    assert fixed.returncode == 2  # fixed value (02 §9)
    bad = cli("config", "set", "scan.settle_seconds", '"ten"')
    assert bad.returncode == 6 and bad.envelope["error"]["code"] == "E_CONFIG_INVALID"
    unknown = cli("config", "get", "scan.nope")
    assert unknown.returncode == 2 and "known_prefix" in unknown.envelope["error"]["details"]


def test_config_allow_trash_effective_flag(initialized: RunCli) -> None:
    res = initialized("config", "set", "icloud.allow_trash", "false")
    assert res.returncode == 0 and res.data["effective"] is False  # code gate is still False


def test_unknown_config_key_in_file_warns(initialized: RunCli, sandbox: Sandbox) -> None:
    cli = initialized
    cfg = sandbox.home / "config.toml"
    cfg.write_text(cfg.read_text() + "\n[future]\nthing = 1\n")
    res = cli("root", "list")
    assert res.returncode == 0
    assert [w["code"] for w in res.envelope["warnings"]] == ["W_CONFIG_UNKNOWN_KEY"]
    cfg.write_text(cfg.read_text().replace("thing = 1", "") + '\n[scan]\nsettle_seconds = "x"\n')
    broken = cli("root", "list")
    assert broken.returncode == 6 and broken.envelope["error"]["code"] == "E_CONFIG_INVALID"


def test_audit_rows_for_writes_only(initialized: RunCli, sandbox: Sandbox) -> None:
    import sqlite3

    cli = initialized
    cli("root", "add", str(sandbox.mkdir("Downloads")), "--kind", "downloads")
    cli("root", "list")
    cli("config", "get", "review.daily_time")
    cli("config", "set", "scan.settle_seconds", "oops")
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    rows = conn.execute(
        "SELECT command, channel, ok, error_code, target_ids_json, summary "
        "FROM audit_log ORDER BY id"
    ).fetchall()
    conn.close()
    commands = [r[0] for r in rows]
    assert commands == ["core.init", "root.add", "config.set"]
    assert rows[-1][2:4] == (0, "E_CONFIG_INVALID")
    assert rows[1][4] == '["root_1"]' and str(sandbox.user) not in "".join(r[5] for r in rows)
