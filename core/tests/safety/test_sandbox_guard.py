"""S5: the audit-hook guard and the sandbox validity check (02 §10.4, 11 §2.2)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import RunCli, Sandbox

from dayclose.common import errors, paths

PROBE = "/nonexistent-dayclose-guard-probe/x"


def _home_probe(real: Any) -> str:
    # A name under the real home that does not exist and is never created.
    return os.path.join(real.home, ".dayclose-guard-probe-never-created", "f")


def test_guard_blocks_writes_outside_sandbox(_real_home_snapshot: Any) -> None:
    targets = [PROBE, _home_probe(_real_home_snapshot)]
    for target in targets:
        with pytest.raises(errors.SafetyError) as exc:
            open(target, "w")  # noqa: SIM115
        assert exc.value.code == "E_SANDBOX_VIOLATION"
        with pytest.raises(errors.SafetyError):
            os.rename(target, target + ".2")
        with pytest.raises(errors.SafetyError):
            os.mkdir(target)
        with pytest.raises(errors.SafetyError):
            os.remove(target)
        assert not os.path.exists(target)


def test_guard_blocks_reads_of_real_home_and_volumes(_real_home_snapshot: Any) -> None:
    with pytest.raises(errors.SafetyError):
        os.scandir(_real_home_snapshot.home)
    with pytest.raises(errors.SafetyError):
        os.listdir("/Volumes")
    with pytest.raises(errors.SafetyError):
        open(_home_probe(_real_home_snapshot))  # noqa: SIM115
    with pytest.raises(errors.SafetyError):
        os.scandir("/Applications")


def test_guard_allows_sandbox_and_runtime(sandbox: Sandbox) -> None:
    p = sandbox.user / "ok.txt"
    p.write_text("fine")
    assert p.read_text() == "fine"
    os.rename(p, sandbox.user / "ok2.txt")
    with os.scandir(sandbox.user) as it:
        assert [e.name for e in it] == ["ok2.txt"]
    os.listdir(os.path.dirname(os.__file__))  # stdlib reads are allowed


def test_guard_blocks_unlisted_executables(sandbox: Sandbox) -> None:
    with pytest.raises(errors.SafetyError):
        subprocess.run(["/bin/echo", "hi"], check=False)
    with pytest.raises(errors.SafetyError):
        subprocess.run(["/usr/bin/touch", str(sandbox.user / "x")], check=False)
    assert not (sandbox.user / "x").exists()


def test_guard_inside_cli_subprocess(
    cli: RunCli, sandbox: Sandbox, _real_home_snapshot: Any
) -> None:
    """The CLI installs the same guard: a root outside the sandbox is refused."""
    assert cli("init", "--no-default-roots").returncode == 0
    res = cli("root", "add", _real_home_snapshot.home, "--kind", "custom")
    assert res.returncode == 5 and res.envelope["error"]["code"] == "E_SANDBOX_VIOLATION"
    # Nothing about the refused path is echoed back.
    assert _real_home_snapshot.home not in res.stdout


def test_sandbox_home_outside_sandbox_rejected(
    cli: RunCli, sandbox: Sandbox, tmp_path: Path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-home"
    res = cli("init", "--home", str(outside), json_mode=False, env={})
    assert res.returncode == 5 and "E_SANDBOX_VIOLATION" in res.stderr
    assert not outside.exists()  # nothing was created


def test_guard_not_active_without_sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as m:
        m.delenv("DAYCLOSE_SANDBOX")
        assert paths.install_sandbox_guard() is False
        # The (already installed) hook is inert: reading a stdlib-free path is not refused.
        assert os.path.exists(sys.executable)


def test_guard_refuses_sqlite_uri_outside_state_db(sandbox: Sandbox, tmp_path: Path) -> None:
    import sqlite3

    other = tmp_path.parent / f"{tmp_path.name}-uri.db"
    with pytest.raises(errors.SafetyError):
        sqlite3.connect(f"file:{other}?mode=rwc", uri=True)
    assert not other.exists()
    inside = sandbox.root / "not-the-state-db.db"
    with pytest.raises(errors.SafetyError):
        sqlite3.connect(f"file:{inside}?mode=rwc", uri=True)


def test_guard_reads_limited_to_sandbox_not_whole_temp_dir(tmp_path: Path) -> None:
    sibling = tmp_path.parent  # pytest's base temp: under the user temp dir, outside us
    with pytest.raises(errors.SafetyError):
        os.listdir(sibling)
