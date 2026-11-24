"""Sandbox validity (02 §10.4, 11 §2.3a): every refusal case is E_SANDBOX_VIOLATION, exit 5,
and nothing is created. Refused paths are passed as strings only."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import RunCli, Sandbox

from dayclose.common import errors, paths


def _run(cli: RunCli, sandbox_dir: str, home: str, **extra: str) -> tuple[int, str]:
    res = cli(
        "version",
        "--json",
        json_mode=False,
        env={"DAYCLOSE_SANDBOX": sandbox_dir, "DAYCLOSE_HOME": home, **extra},
    )
    env = res.envelope
    if not env["ok"]:
        assert env["meta"]["device_id"] is None  # the refused home was never read
    return res.returncode, env["error"]["details"]["reason"] if not env["ok"] else ""


def test_sandbox_outside_temp_rejected(cli: RunCli) -> None:
    repo_dir = str(Path(__file__).resolve().parents[3])
    assert _run(cli, repo_dir, repo_dir + "/home") == (5, "not_under_temp_dir")


def test_sandbox_equals_real_home_rejected(cli: RunCli, _real_home_snapshot: Any) -> None:
    rh = _real_home_snapshot.home
    assert _run(cli, rh, rh + "/.dayclose-probe-home")[0] == 5


def test_sandbox_equals_real_home_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, _real_home_snapshot: Any
) -> None:
    rh = _real_home_snapshot.home
    touched: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if args and isinstance(args[0], str) and args[0].startswith(rh):
            touched.append(event)

    sys.addaudithook(audit)
    with monkeypatch.context() as m:
        m.setenv("DAYCLOSE_SANDBOX", rh)
        with pytest.raises(errors.SafetyError):
            paths.validate_sandbox(Path(rh) / "home")
    assert touched == []


def test_sandbox_ancestor_of_home_rejected(cli: RunCli) -> None:
    for anc in ("/Users", "/"):
        assert _run(cli, anc, anc.rstrip("/") + "/x")[0] == 5


def test_sandbox_home_env_spoof_rejected(
    cli: RunCli, sandbox: Sandbox, _real_home_snapshot: Any
) -> None:
    """$HOME points into the temp dir, DAYCLOSE_SANDBOX at the real home: pw_dir decides."""
    rh = _real_home_snapshot.home
    code, _ = _run(cli, rh, rh + "/h", HOME=str(sandbox.user))
    assert code == 5


def test_sandbox_contains_volumes_rejected(cli: RunCli) -> None:
    assert _run(cli, "/Volumes", "/Volumes/h")[0] == 5


def test_sandbox_contains_default_home_rejected(
    monkeypatch: pytest.MonkeyPatch, sandbox: Sandbox
) -> None:
    """Rule 2 on its own: a (temp-dir) sandbox that contains the real home / default home."""
    fake_home = sandbox.root / "user"
    monkeypatch.setattr(paths, "real_home", lambda: str(fake_home))
    with pytest.raises(errors.SafetyError) as exc:
        paths.validate_sandbox(sandbox.home)
    assert exc.value.details["reason"] == "contains_protected_location"
    default_home = sandbox.root / "deep" / "Library/Application Support/DayClose"
    monkeypatch.setattr(paths, "real_home", lambda: str(sandbox.root / "deep"))
    with pytest.raises(errors.SafetyError):
        paths.validate_sandbox(sandbox.home)
    assert not default_home.exists()


def test_sandbox_marker_missing_rejected(cli: RunCli, sandbox: Sandbox) -> None:
    bare = sandbox.root / "bare"
    bare.mkdir()
    assert _run(cli, str(bare), str(bare / "home")) == (5, "marker_missing")
    assert not (bare / "home").exists()


def test_sandbox_symlink_escape_rejected(
    cli: RunCli, sandbox: Sandbox, _real_home_snapshot: Any
) -> None:
    link = sandbox.root / "escape"
    link.symlink_to(_real_home_snapshot.home)
    assert _run(cli, str(link), str(link / "home"))[0] == 5


def test_sandbox_home_outside_sandbox_rejected(
    cli: RunCli, sandbox: Sandbox, tmp_path: Path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-home"
    assert _run(cli, str(sandbox.root), str(outside)) == (5, "home_outside_sandbox")
    res = cli("init", "--home", str(outside), json_mode=False)
    assert res.returncode == 5 and "E_SANDBOX_VIOLATION" in res.stderr
    assert not outside.exists()


def test_valid_sandbox_accepted(cli: RunCli, sandbox: Sandbox) -> None:
    assert _run(cli, str(sandbox.root), str(sandbox.home)) == (0, "")
    assert os.path.isfile(sandbox.root / ".dayclose-sandbox")
