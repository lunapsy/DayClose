"""02 §10.3-4b end to end: outside a sandbox an agent marker always means refusal.

Each case runs the real CLI in a subprocess with DAYCLOSE_SANDBOX removed and a throwaway
DAYCLOSE_HOME under this test's temp dir (never the real home, never the real state dir).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import Sandbox

from dayclose.plan.approval import AGENT_ENV_MARKERS

FLAGS: list[tuple[str, ...]] = [(), ("--channel", "cli"), ("--channel", "app")]


def _env(home: Path, user: Path, marker: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in AGENT_ENV_MARKERS}
    env.pop("DAYCLOSE_SANDBOX", None)
    env.update(DAYCLOSE_HOME=str(home), HOME=str(user))
    if marker:
        env[marker] = "1"
    return env


def _run(home: Path, user: Path, marker: str | None, *argv: str) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, "-m", "dayclose", *argv, "--json"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=home.parent,
        env=_env(home, user, marker),
    )
    return proc.returncode, json.loads(proc.stdout)


def _state(home: Path) -> str:
    h = hashlib.sha256()
    cfg = home / "config.toml"
    h.update(cfg.read_bytes() if cfg.exists() else b"-")
    db = home / "dayclose.db"
    if db.exists():
        conn = sqlite3.connect(db)
        for table in ("scan_roots", "app_meta"):
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1"):
                h.update(repr(row).encode())
        conn.close()
    return h.hexdigest()


@pytest.fixture
def outside(sandbox: Sandbox, tmp_path: Path) -> tuple[Path, Path]:
    """A state dir outside any sandbox, but still inside this test's temp dir."""
    home = tmp_path / "outside" / "home"
    home.parent.mkdir()
    return home, sandbox.user


@pytest.mark.parametrize("flags", FLAGS, ids=["no_flag", "cli", "app"])
@pytest.mark.parametrize("marker", ["CLAUDECODE", "AI_AGENT"])
def test_marker_init_refused_outside_sandbox(
    outside: tuple[Path, Path], flags: tuple[str, ...], marker: str
) -> None:
    home, user = outside
    code, env = _run(home, user, marker, "init", "--no-default-roots", *flags)
    assert code == 5 and env["error"]["code"] == "E_PROTECTED"
    assert env["error"]["details"] == {"reason": "owner_only"}
    assert not home.exists()  # nothing created


def test_marker_test_channel_refused_outside_sandbox(outside: tuple[Path, Path]) -> None:
    """`--channel test` is not a CLI channel: refused (E_USAGE) before anything happens."""
    home, user = outside
    code, env = _run(home, user, "CLAUDECODE", "init", "--no-default-roots", "--channel", "test")
    assert code == 2 and env["error"]["code"] == "E_USAGE"
    assert not home.exists()


@pytest.mark.parametrize("flags", FLAGS, ids=["no_flag", "cli", "app"])
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(lambda d: ("root", "add", str(d), "--kind", "custom"), id="root_add"),
        pytest.param(lambda d: ("root", "remove", "root_1"), id="root_remove"),
        pytest.param(
            lambda d: ("config", "set", "scan.exclude_globs", '["**"]'),
            id="config_set_exclude_globs",
        ),
        pytest.param(
            lambda d: ("config", "set", "protection.detect_rrn_in_text", "false"),
            id="config_set_protection",
        ),
        pytest.param(
            lambda d: ("config", "set", "icloud.allow_trash", "false"), id="config_set_icloud"
        ),
    ],
)
def test_marker_owner_only_refused_outside_sandbox(
    outside: tuple[Path, Path], flags: tuple[str, ...], argv: Any
) -> None:
    home, user = outside
    target = home.parent / "dir"
    target.mkdir()
    # The owner (no marker) initialises the state dir and registers one root.
    assert _run(home, user, None, "init", "--no-default-roots")[0] == 0
    assert _run(home, user, None, "root", "add", str(home.parent), "--kind", "custom")[0] == 0
    before = _state(home)
    code, env = _run(home, user, "CLAUDECODE", *argv(target), *flags)
    assert code == 5 and env["error"]["details"] == {"reason": "owner_only"}
    assert _state(home) == before
    conn = sqlite3.connect(home / "dayclose.db")
    channels = [r[0] for r in conn.execute("SELECT channel FROM audit_log ORDER BY id")]
    conn.close()
    assert channels == ["cli", "cli"]  # the refused call never reached a write


def test_marker_app_read_is_skill_and_audited(outside: tuple[Path, Path]) -> None:
    """Non-owner-only work still runs; the audit log keeps the effective channel and, in the
    summary, the requested one."""
    home, user = outside
    assert _run(home, user, None, "init", "--no-default-roots")[0] == 0
    code, env = _run(
        home,
        user,
        "CLAUDECODE",
        "config",
        "set",
        "review.daily_time",
        '"20:00"',
        "--channel",
        "app",
    )
    assert code == 0
    conn = sqlite3.connect(home / "dayclose.db")
    row = conn.execute("SELECT channel, summary FROM audit_log ORDER BY id DESC").fetchone()
    conn.close()
    assert row == ("skill", "config.set review.daily_time requested_channel=app")


@pytest.mark.parametrize("flags", [("--channel", "schedule")], ids=["schedule"])
def test_marker_schedule_allowlist_holds(
    outside: tuple[Path, Path], flags: tuple[str, ...]
) -> None:
    home, user = outside
    assert _run(home, user, None, "init", "--no-default-roots")[0] == 0
    for argv in (("root", "list"), ("init", "--no-default-roots"), ("doctor",)):
        code, env = _run(home, user, "CLAUDECODE", *argv, *flags)
        assert code == 5 and env["error"]["details"] == {"reason": "channel_not_allowed"}
    # marker + app is elevated to skill, never to a channel with fewer restrictions
    code, env = _run(home, user, "CLAUDECODE", "init", "--no-default-roots", "--channel", "app")
    assert code == 5 and env["error"]["details"] == {"reason": "owner_only"}
