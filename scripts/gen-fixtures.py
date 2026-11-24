#!/usr/bin/env python3
"""Regenerate contracts/fixtures/*.json from a sandbox scenario (10 §4.2).

Usage (from the repository root):  uv run --project core python scripts/gen-fixtures.py

Everything runs inside a fresh sandbox under the user temp directory. Non-deterministic
fields are normalised so that the committed fixtures diff only when the contract changes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "contracts" / "fixtures"
TEST_NOW = "2026-11-24T12:00:00.000Z"
FILE_TIME = datetime(2026, 11, 24, 10, 0, tzinfo=UTC).timestamp()
AGENT_MARKERS = ("CLAUDECODE", "AI_AGENT", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _env(sandbox: Path, home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}
    env.update(
        DAYCLOSE_SANDBOX=str(sandbox),
        DAYCLOSE_HOME=str(home),
        DAYCLOSE_TEST_NOW=TEST_NOW,
        HOME=str(sandbox / "user"),
    )
    return env


def _run(sandbox: Path, *argv: str, home: Path | None = None) -> dict[str, Any]:
    home = home or sandbox / "home"
    proc = subprocess.run(
        [sys.executable, "-m", "dayclose", *argv, "--json"],
        capture_output=True, text=True, timeout=60, cwd=sandbox, env=_env(sandbox, home),
    )
    env: dict[str, Any] = json.loads(proc.stdout)
    return env


def normalize(value: Any, sandbox: str, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: normalize(v, sandbox, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v, sandbox, key) for v in value]
    if key == "request_id" and isinstance(value, str):
        return "<req>"
    if key == "duration_ms" and isinstance(value, int):
        return 0
    if key in ("device_id", "db_device_id") and isinstance(value, str):
        return "<device>"
    if key == "python" and isinstance(value, str):
        return "<python>"
    if isinstance(value, str):
        if _TIME.match(value):
            return "2026-11-24T00:00:00.000Z"
        return value.replace(sandbox, "/SANDBOX")
    return value


def generate(workdir: Path) -> dict[str, dict[str, Any]]:
    """Run the M1 scenario in `workdir` (a new sandbox) and return normalised envelopes."""
    sandbox = Path(os.path.realpath(workdir))
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / ".dayclose-sandbox").touch()
    downloads = sandbox / "user" / "Downloads"
    downloads.mkdir(parents=True)
    for name in ("report.pdf", "notes.txt"):
        p = downloads / name
        p.write_bytes(b"fixture " + name.encode())
        os.utime(p, (FILE_TIME, FILE_TIME))

    out: dict[str, dict[str, Any]] = {}
    out["error.E_NOT_INITIALIZED"] = _run(sandbox, "root", "list")
    out["error.E_SANDBOX_VIOLATION"] = _run(sandbox, "version",
                                           home=sandbox.parent / "outside-home")
    _run(sandbox, "init", "--no-default-roots", "--device-name", "Fixture Mac")
    out["core.version.ok"] = _run(sandbox, "version")
    _run(sandbox, "root", "add", str(downloads), "--kind", "downloads")
    out["root.list.ok"] = _run(sandbox, "root", "list")
    _run(sandbox, "scan", "run")
    new = downloads / "a.txt"
    new.write_bytes(b"hi\n")
    os.utime(new, (FILE_TIME, FILE_TIME))
    out["scan.run.ok"] = _run(sandbox, "scan", "run")
    new.rename(downloads / "b.txt")
    _run(sandbox, "scan", "run")
    out["change.list.ok"] = _run(sandbox, "change", "list")
    return {name: normalize(env, str(sandbox)) for name, env in out.items()}


def dump(env: dict[str, Any]) -> str:
    return json.dumps(env, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dayclose-fixtures-") as tmp:
        envs = generate(Path(tmp) / "sandbox")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, env in sorted(envs.items()):
        (FIXTURES / f"{name}.json").write_text(dump(env), encoding="utf-8")
        print(f"wrote contracts/fixtures/{name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
