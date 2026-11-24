"""Sandbox enforcement for every test (11 §2.1). Do not disable or bypass these fixtures."""

from __future__ import annotations

import json
import os
import pwd
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import settings

from dayclose.collect import fs as fs_collector
from dayclose.common import clock, paths
from dayclose.plan.approval import AGENT_ENV_MARKERS

TESTS_DIR = Path(__file__).resolve().parent
CORE_DIR = TESTS_DIR.parent
REPO_DIR = CORE_DIR.parent

# Hypothesis must not write its example database outside the sandbox (11 §5).
settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, database=None)
settings.register_profile("nightly", max_examples=5000, deadline=None, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


@dataclass(frozen=True)
class RealPaths:
    home: str
    repo: str


@pytest.fixture(scope="session", autouse=True)
def _real_home_snapshot() -> RealPaths:
    return RealPaths(home=os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir), repo=str(REPO_DIR))


@dataclass
class Sandbox:
    root: Path
    home: Path
    user: Path

    def mkdir(self, rel: str) -> Path:
        p = self.user / rel
        p.mkdir(parents=True, exist_ok=True)
        return p


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Sandbox]:
    root = Path(os.path.realpath(tmp_path))
    for sub in ("home", "user", "sys", "bin", "vol"):
        (root / sub).mkdir()
    (root / paths.SANDBOX_MARKER).touch()
    user = root / "user"
    monkeypatch.setenv("DAYCLOSE_SANDBOX", str(root))
    monkeypatch.setenv("DAYCLOSE_HOME", str(root / "home"))
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CFFIXED_USER_HOME", str(user))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PATH", f"{root / 'bin'}:{os.environ.get('PATH', '')}")
    # Agent markers (e.g. CLAUDECODE) are deliberately left as they are: tests run like the
    # real development environment (11 §10 M1a). Use `no_agent_markers` where needed.
    for var in ("DAYCLOSE_TEST_APPROVE", "DAYCLOSE_TEST_NOW", "DAYCLOSE_TEST_FAULT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user))
    real_expanduser = os.path.expanduser

    def _expanduser(p: Any) -> Any:
        s = os.fspath(p)
        if isinstance(s, str) and (s == "~" or s.startswith("~/")):
            return str(user) + s[1:]
        return real_expanduser(p)

    monkeypatch.setattr(os.path, "expanduser", _expanduser)
    paths.set_active_home(None)
    yield Sandbox(root=root, home=root / "home", user=user)
    paths.set_active_home(None)
    clock.set_clock(None)
    fs_collector.flags_hook = None
    paths.probe_stat = paths._default_probe_stat


@pytest.fixture(autouse=True)
def _guard_env(sandbox: Sandbox, tmp_path: Path) -> Iterator[None]:
    def check() -> None:
        sb = os.environ.get("DAYCLOSE_SANDBOX", "")
        home = os.environ.get("DAYCLOSE_HOME", "")
        base = os.path.realpath(tmp_path)
        assert sb and paths.is_under(os.path.realpath(sb), base), "DAYCLOSE_SANDBOX changed"
        assert home and paths.is_under(os.path.realpath(home), base), "DAYCLOSE_HOME changed"

    check()
    yield
    check()


@pytest.fixture(autouse=True)
def _audit_guard(_guard_env: None, sandbox: Sandbox) -> Iterator[None]:
    """Turn on the core audit-hook guard in this process (11 §2.2)."""
    paths.allow_extra_for_tests(
        executables=[sys.executable, os.path.realpath(sys.executable)],
        read_roots=[
            str(TESTS_DIR),
            str(REPO_DIR / "scripts"),
            str(REPO_DIR / "contracts"),
            str(REPO_DIR / "docs"),
        ],
    )
    assert paths.install_sandbox_guard()
    yield


class _Net:
    active = False
    installed = False


def _net_hook(event: str, args: tuple[Any, ...]) -> None:
    if not _Net.active:
        return
    if event == "socket.connect":
        sock = args[0] if args else None
        if getattr(sock, "family", None) != socket.AF_UNIX:
            raise RuntimeError("network access in tests is forbidden (NFR-PRIV-002)")
    elif event == "socket.getaddrinfo":
        raise RuntimeError("network access in tests is forbidden (NFR-PRIV-002)")


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    if not _Net.installed:
        sys.addaudithook(_net_hook)
        _Net.installed = True
    _Net.active = True
    yield
    _Net.active = False


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def envelope(self) -> dict[str, Any]:
        lines = self.stdout.splitlines()
        assert len(lines) == 1, f"expected exactly one stdout line, got {len(lines)}"
        env: dict[str, Any] = json.loads(lines[0])
        return env

    @property
    def data(self) -> Any:
        return self.envelope["data"]


RunCli = Callable[..., CliResult]


@pytest.fixture
def cli(sandbox: Sandbox) -> RunCli:
    def run(
        *argv: str, env: dict[str, str] | None = None, json_mode: bool = True, timeout: float = 60
    ) -> CliResult:
        full = [sys.executable, "-m", "dayclose", *argv]
        if json_mode:
            full += ["--json", "--home", str(sandbox.home)]
        proc = subprocess.run(
            full,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=sandbox.root,
            env={**os.environ, **(env or {})},
        )
        return CliResult(proc.returncode, proc.stdout, proc.stderr)

    return run


# Performance measurements (11 §7, 12 M1b "측정값 기록"): collected during the run and
# written after the session (outside every test's sandbox guard) to PERF_RESULTS_FILE.
PERF_RESULTS_FILE = CORE_DIR / ".perf-results" / "m1-perf.jsonl"
_PERF: list[dict[str, Any]] = []


@pytest.fixture
def record_perf() -> Callable[[dict[str, Any]], None]:
    def record(result: dict[str, Any]) -> None:
        print(json.dumps(result))
        _PERF.append(result)

    return record


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _PERF:
        return
    PERF_RESULTS_FILE.parent.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PERF_RESULTS_FILE, "a", encoding="utf-8") as fh:
        for r in _PERF:
            fh.write(
                json.dumps({"measured_at": stamp, "python": sys.version.split()[0], **r}) + "\n"
            )


@pytest.fixture
def no_agent_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove agent environment markers so the effective channel stays `cli`."""
    for marker in AGENT_ENV_MARKERS:
        monkeypatch.delenv(marker, raising=False)


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def initialized(cli: RunCli) -> RunCli:
    res = cli("init", "--no-default-roots")
    assert res.returncode == 0, res.stdout + res.stderr
    return cli
