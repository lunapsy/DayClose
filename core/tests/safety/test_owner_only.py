"""Owner-only commands on agent channels (02 §10.3-3/4b, 10 §1.8) - M1a part."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from conftest import RunCli, Sandbox

from dayclose.api.runtime import effective_channel, owner_only_refused
from dayclose.plan.approval import AGENT_ENV_MARKERS

PROTECTED_KEYS = [
    ("protection.detect_rrn_in_text", "false"),
    ("protection.patient_filename_patterns", "[]"),
    ("vault.gitleaks", '"off"'),
    ("scan.exclude_globs", '["**"]'),
    ("icloud.allow_trash", "false"),
    ("ai.allow_external", "true"),
]


def _state(sandbox: Sandbox) -> str:
    h = hashlib.sha256()
    for name in ("config.toml",):
        p = sandbox.home / name
        h.update(p.read_bytes() if p.exists() else b"-")
    db = sandbox.home / "dayclose.db"
    if db.exists():
        conn = sqlite3.connect(db)
        for row in conn.execute("SELECT * FROM scan_roots ORDER BY id"):
            h.update(repr(row).encode())
        conn.close()
    return h.hexdigest()


@pytest.mark.parametrize("marker", AGENT_ENV_MARKERS)
def test_effective_channel_elevation(marker: str) -> None:
    assert effective_channel("cli", {marker: "1"}) == "skill"
    assert effective_channel("cli", {}) == "cli"
    # A marker wins over an explicit cli/app/test; explicit agent/scheduler channels stay.
    for requested in ("cli", "app", "test"):
        assert effective_channel(requested, {marker: "1"}) == "skill"
        assert effective_channel(requested, {}) == requested
    for requested in ("skill", "mcp", "schedule"):
        assert effective_channel(requested, {marker: "1"}) == requested


def test_owner_only_marker_outside_sandbox_refused() -> None:
    """Pure decision function with an injected 'outside the sandbox' state: no real home."""
    env = {"CLAUDECODE": "1", "DAYCLOSE_TEST_APPROVE": "1", "DAYCLOSE_TEST_NOW": "x"}
    for requested in ("cli", "app", "test"):
        eff = effective_channel(requested, env)
        for cmd, args in (
            ("core.init", {}),
            ("root.add", {}),
            ("root.remove", {}),
            ("config.set", {"key": "vault.gitleaks"}),
        ):
            assert owner_only_refused(cmd, args, requested, eff, sandbox_valid=False)
            # inside a valid sandbox, marker-only elevation is exempt
            assert not owner_only_refused(cmd, args, requested, eff, sandbox_valid=True)
    eff = effective_channel("cli", env)
    # Non owner-only work is unaffected.
    assert not owner_only_refused("scan.run", {}, "cli", eff, sandbox_valid=False)
    assert not owner_only_refused(
        "config.set", {"key": "review.daily_time"}, "cli", eff, sandbox_valid=False
    )


@pytest.mark.parametrize(
    "argv_factory",
    [
        pytest.param(lambda s: ("init", "--no-default-roots"), id="core_init"),
        pytest.param(
            lambda s: ("root", "add", str(s.mkdir("New")), "--kind", "custom"), id="root_add"
        ),
        pytest.param(lambda s: ("root", "remove", "root_1"), id="root_remove"),
        *[
            pytest.param(lambda s, k=k, v=v: ("config", "set", k, v), id=f"config_set_{k}")
            for k, v in PROTECTED_KEYS
        ],
    ],
)
@pytest.mark.parametrize("channel", ["skill", "mcp"])
def test_owner_only_refused_on_agent_channels(
    cli: RunCli,
    sandbox: Sandbox,
    no_agent_markers: None,
    argv_factory: object,
    channel: str,
) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    assert cli("root", "add", str(sandbox.mkdir("Existing")), "--kind", "custom").returncode == 0
    argv = argv_factory(sandbox)  # type: ignore[operator]
    before = _state(sandbox)
    res = cli(*argv, "--channel", channel)
    assert res.returncode == 5, res.stdout
    err = res.envelope["error"]
    assert err["code"] == "E_PROTECTED" and err["details"] == {"reason": "owner_only"}
    assert _state(sandbox) == before
    ok = cli(*argv)  # the same command on the owner's `cli` channel succeeds
    assert ok.returncode == 0, ok.stdout


def test_owner_only_refused_before_anything_is_created(cli: RunCli, sandbox: Sandbox) -> None:
    res = cli("init", "--channel", "skill")
    assert res.returncode == 5
    assert not (sandbox.home / "dayclose.db").exists()
    assert not (sandbox.home / "config.toml").exists()


def test_owner_only_marker_inside_sandbox_allowed(
    cli: RunCli, sandbox: Sandbox, no_agent_markers: None
) -> None:
    env = {"CLAUDECODE": "1"}
    assert cli("init", "--no-default-roots", env=env).returncode == 0
    assert cli("root", "add", str(sandbox.mkdir("D")), "--kind", "custom", env=env).returncode == 0
    assert cli("config", "set", "vault.gitleaks", '"off"', env=env).returncode == 0
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    channels = {r[0] for r in conn.execute("SELECT DISTINCT channel FROM audit_log")}
    conn.close()
    assert channels == {"skill"}  # the audit log keeps the effective channel


def test_owner_only_explicit_channel_inside_sandbox_refused(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    for channel in ("skill", "mcp"):
        res = cli(
            "root",
            "add",
            str(sandbox.mkdir("X")),
            "--kind",
            "custom",
            "--channel",
            channel,
            env={"CLAUDECODE": "1"},
        )
        assert res.returncode == 5 and res.envelope["error"]["details"]["reason"] == "owner_only"


def test_schedule_channel_refuses_other_commands(cli: RunCli, sandbox: Sandbox) -> None:
    assert cli("init", "--no-default-roots").returncode == 0
    for argv in (
        ("root", "list"),
        ("config", "set", "review.daily_time", '"20:00"'),
        ("doctor",),
        ("version",),
    ):
        res = cli(*argv, "--channel", "schedule")
        assert res.returncode == 5
        assert res.envelope["error"]["details"] == {"reason": "channel_not_allowed"}
