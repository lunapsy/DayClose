"""FR-CORE-004: every M1 command emits exactly one schema-valid envelope; exit codes per 02 §5.5.
Contract fixtures regenerate identically (10 §4.2)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from conftest import REPO_DIR, RunCli, Sandbox

SCHEMA = json.loads((REPO_DIR / "contracts" / "envelope.schema.json").read_text())
FIXTURES = REPO_DIR / "contracts" / "fixtures"
EXIT = {
    "E_USAGE": 2,
    "E_NOT_FOUND": 3,
    "E_NOT_INITIALIZED": 3,
    "E_SANDBOX_VIOLATION": 5,
    "E_PROTECTED": 5,
    "E_CONFIG_INVALID": 6,
    "E_VOLUME_UNAVAILABLE": 6,
    "E_LOCKED": 7,
    "E_DB_CORRUPT": 10,
}
M1_COMMANDS = {
    "core.version",
    "core.init",
    "core.doctor",
    "config.get",
    "config.set",
    "config.list",
    "root.list",
    "root.add",
    "root.remove",
}


def _validate(env: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(env)


def test_registry_is_exactly_m1() -> None:
    from dayclose.api import REGISTRY

    assert set(REGISTRY) == M1_COMMANDS


def test_fr_core_004_every_command_envelope(cli: RunCli, sandbox: Sandbox) -> None:
    dl = sandbox.mkdir("Downloads")
    cases: list[tuple[str, tuple[str, ...], str | None]] = [
        ("core.version", ("version",), None),
        ("root.list", ("root", "list"), "E_NOT_INITIALIZED"),
        ("core.doctor", ("doctor",), None),
        ("core.init", ("init", "--no-default-roots"), None),
        ("core.init", ("init", "--device-name", ""), "E_USAGE"),
        ("config.get", ("config", "get", "review.daily_time"), None),
        ("config.get", ("config", "get", "nope.key"), "E_USAGE"),
        ("config.set", ("config", "set", "scan.settle_seconds", "0"), None),
        ("config.set", ("config", "set", "scan.settle_seconds", "soon"), "E_CONFIG_INVALID"),
        ("config.list", ("config", "list"), None),
        ("root.add", ("root", "add", str(dl), "--kind", "downloads"), None),
        ("root.add", ("root", "add", str(dl / "x"), "--kind", "downloads"), "E_NOT_FOUND"),
        ("root.list", ("root", "list"), None),
        ("root.list", ("root", "list", "--cursor", "zz"), "E_USAGE"),
        ("root.remove", ("root", "remove", "root_1"), None),
        ("root.remove", ("root", "remove", "root_1"), "E_NOT_FOUND"),
    ]
    seen = set()
    for command, argv, code in cases:
        res = cli(*argv)
        env = res.envelope  # exactly one stdout line
        _validate(env)
        assert env["command"] == command, argv
        if code is None:
            assert (res.returncode, env["ok"]) == (0, True), (argv, env)
        else:
            assert env["ok"] is False and env["error"]["code"] == code, (argv, env)
            assert res.returncode == EXIT[code], argv
        seen.add(command)
    assert seen == M1_COMMANDS


def test_usage_error_is_json(cli: RunCli) -> None:
    for argv in (("root", "list", "--frobnicate"), ("bogus", "verb"), ()):
        res = cli(*argv)
        env = res.envelope
        _validate(env)
        assert res.returncode == 2 and env["error"]["code"] == "E_USAGE"
    flags_first = cli("--json", "version", json_mode=False)
    assert flags_first.returncode == 0 and flags_first.envelope["command"] == "core.version"


def test_fixtures_are_schema_valid() -> None:
    names = sorted(p.name for p in FIXTURES.glob("*.json"))
    assert {
        "core.version.ok.json",
        "error.E_NOT_INITIALIZED.json",
        "root.list.ok.json",
        "error.E_SANDBOX_VIOLATION.json",
    } <= set(names)
    for name in names:
        text = (FIXTURES / name).read_text()
        assert text.count("\n") == 1 and text.endswith("\n")
        _validate(json.loads(text))


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "gen_fixtures", REPO_DIR / "scripts" / "gen-fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fixtures_regenerate_identically(sandbox: Sandbox, tmp_path: Path) -> None:
    gen = _load_generator()
    envs = gen.generate(tmp_path / "fx")
    for name, env in envs.items():
        committed = (FIXTURES / f"{name}.json").read_text()
        assert gen.dump(env) == committed, name


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_fixtures_have_no_real_paths(name: str, _real_home_snapshot: Any) -> None:
    text = (FIXTURES / name).read_text()
    assert _real_home_snapshot.home not in text and "/Volumes/" not in text
