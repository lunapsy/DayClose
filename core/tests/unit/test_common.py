"""ids, envelope, errors/exit codes, clock, pagination, redaction, run_tool, paths helpers."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import Sandbox
from fixtures.sandbox import install_fake_tool, tool_calls

from dayclose.api import pagination
from dayclose.common import clock, envelope, errors, ids, paths, proc
from dayclose.common import logging as dlog


def test_ids_roundtrip_and_rejects() -> None:
    assert ids.to_ext("run", 12) == "run_12" and ids.parse("run", "run_12") == 12
    assert ids.to_ext("root", 1) == "root_1" and ids.parse("root", "root_1") == 1
    for bad in ("12", "grp_12", "run_", "run_01", "run_1a", "root_-1"):
        with pytest.raises(errors.UsageError):
            ids.parse("run" if not bad.startswith("root") else "root", bad)


def test_error_exit_codes() -> None:
    cases = [
        (errors.UsageError("x"), 2),
        (errors.NotFoundError("E_NOT_INITIALIZED", "x"), 3),
        (errors.StateError("E_STALE", "x"), 4),
        (errors.SafetyError("E_SANDBOX_VIOLATION", "x"), 5),
        (errors.EnvironmentError_("E_TCC_DENIED", "x"), 6),
        (errors.LockError("x"), 7),
        (errors.PartialError("x", data={}), 8),
        (errors.InternalError("E_DB_CORRUPT", "x"), 10),
        (errors.CancelledError("x"), 130),
    ]
    for err, code in cases:
        assert err.exit_code == code
    assert errors.LockError("x").retryable is True
    with pytest.raises(ValueError):
        errors.SafetyError("E_LOCKED", "wrong class")


def test_envelope_shapes() -> None:
    meta = envelope.Meta("req_X", "0.1.0", 1, "dev_1", 3)
    ok = envelope.success("core.version", {"a": 1}, [envelope.Warning_("W_X", "m")], meta)
    assert list(ok) == ["schema", "command", "ok", "data", "warnings", "error", "meta"]
    assert ok["ok"] is True and ok["error"] is None and ok["schema"] == "dayclose.v1"
    assert list(ok["meta"]) == [
        "request_id",
        "core_version",
        "contract_version",
        "db_schema_version",
        "device_id",
        "duration_ms",
    ]
    bad = envelope.failure("scan.run", errors.LockError("busy"), [], meta)
    assert bad["ok"] is False and bad["data"] is None and bad["error"]["retryable"] is True
    partial = envelope.failure("plan.apply", errors.PartialError("p", data={"n": 1}), [], meta)
    assert partial["data"] == {"n": 1}
    line = envelope.dumps(ok)
    assert "\n" not in line and json.loads(line) == ok
    assert re.fullmatch(r"req_[0-9A-HJKMNP-TV-Z]{26}", envelope.new_request_id())


def test_clock_test_now_only_in_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAYCLOSE_TEST_NOW", "2026-11-24T12:00:00Z")
    assert clock.now() == datetime(2026, 11, 24, 12, tzinfo=UTC)
    with monkeypatch.context() as m:  # restored before the env guard re-checks
        m.delenv("DAYCLOSE_SANDBOX")
        assert clock.now() != datetime(2026, 11, 24, 12, tzinfo=UTC)
    assert clock.ms_to_rfc3339(1764000000123) == "2025-11-24T16:00:00.123Z"
    clock.set_clock(lambda: datetime(2030, 1, 1, tzinfo=UTC))
    assert clock.now_ms() == 1893456000000


def test_pagination_cursor() -> None:
    c = pagination.encode([5, 7], {"a": 1})
    assert pagination.decode(c, {"a": 1}, 2) == [5, 7]
    for cursor, filters in ((c, {"a": 2}), ("garbage!", {"a": 1}), (c + "x", {"a": 1})):
        with pytest.raises(errors.UsageError) as exc:
            pagination.decode(cursor, filters, 2)
        assert exc.value.details["reason"] == "cursor_mismatch"
    assert pagination.limit_of({}) == 50
    for bad in (0, 501, -1, True):
        with pytest.raises(errors.UsageError):
            pagination.limit_of({"limit": bad})


@pytest.mark.parametrize(
    "secret",
    [
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2",
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4",
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
        "Zq8x" * 3 + "3kP9vW2mL7nR4tY6uI1oE5aS8dF0gH",
    ],
)
def test_redacting_filter(secret: str) -> None:
    rec = logging.LogRecord(
        "dayclose", logging.INFO, __file__, 1, f"token {secret} end", None, None
    )
    dlog.RedactingFilter().filter(rec)
    assert secret not in rec.getMessage() and dlog.REDACTED in rec.getMessage()


def test_redaction_keeps_paths_and_korean() -> None:
    text = "~/Downloads/스크린샷 2026-11-24 오후 2.02.11.png 스캔 완료 /private/var/folders/x"
    assert dlog.redact(text) == text


def test_log_lines_are_json(sandbox: Sandbox) -> None:
    log = dlog.setup(sandbox.home / "logs" / "core.log", "info")
    log.info("hello", extra={"request_id": "req_1", "command": "core.version", "secret": "x"})
    dlog.shutdown()
    line = json.loads((sandbox.home / "logs" / "core.log").read_text().splitlines()[-1])
    assert line["msg"] == "hello" and line["command"] == "core.version"
    assert "secret" not in line  # only allow-listed fields are written


def test_run_tool_sandbox_fake_and_fixed_env(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_tool(sandbox.root, "defaults", stdout="value\n")
    monkeypatch.setenv("GIT_DIR", "/evil")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/evil.dylib")
    res = proc.run_tool("defaults", ["read", "x", "-rf; rm"], 5)
    assert res.returncode == 0 and res.stdout == b"value\n"
    call = tool_calls(sandbox.root)[-1]
    assert call["argv"] == ["read", "x", "-rf; rm"]  # passed verbatim, no shell
    assert "GIT_DIR" not in call["env"] and "DYLD_INSERT_LIBRARIES" not in call["env"]
    with pytest.raises(ValueError):
        proc.run_tool("rm", ["-rf", "/"], 5)
    with pytest.raises(ValueError):
        proc.run_tool("defaults", [], 0)
    with pytest.raises(errors.EnvironmentError_) as exc:
        proc.run_tool("mdls", [], 5)  # sandbox: only $SANDBOX/bin tools run
    assert exc.value.code == "E_TOOL_MISSING"


def test_run_tool_timeout(sandbox: Sandbox) -> None:
    script = install_fake_tool(sandbox.root, "defaults")
    script.write_text(
        script.read_text().replace(
            "import json, os, sys", "import json, os, sys, time; time.sleep(5)"
        )
    )
    res = proc.run_tool("defaults", [], 0.5)
    assert res.timed_out is True


def test_system_path_outside_sandbox_is_absolute(
    monkeypatch: pytest.MonkeyPatch, sandbox: Sandbox
) -> None:
    install_fake_tool(sandbox.root, "osascript")
    assert paths.system_path("osascript") == str(sandbox.root / "bin" / "osascript")
    assert paths.system_path("volumes_root") == str(sandbox.root / "vol")
    with monkeypatch.context() as m:  # restored before the env guard re-checks
        m.delenv("DAYCLOSE_SANDBOX")
        # Resolution only - nothing is executed.
        assert paths.system_path("osascript") == "/usr/bin/osascript"
        assert paths.system_path("volumes_root") == "/Volumes"
        assert paths.system_path("no-such-tool") is None


def test_display_and_normalize(sandbox: Sandbox) -> None:
    u = str(sandbox.user)
    assert paths.display_path(u + "/Downloads") == "~/Downloads"
    assert paths.display_path(u) == "~" and paths.display_path("/usr/bin") == "/usr/bin"
    assert paths.normalize_user_path("~/x/../y") == u + "/y"
    os.chdir(sandbox.root)
    assert paths.normalize_user_path("rel") == str(sandbox.root / "rel")


def test_effective_icloud_table(sandbox: Sandbox) -> None:
    drive = sandbox.mkdir("Library/Mobile Documents/com~apple~CloudDocs")
    desk = str(sandbox.mkdir("Desktop"))
    dl = str(sandbox.mkdir("Downloads"))
    assert paths.effective_icloud(str(drive), "icloud_drive", "auto") == (1, "detected")
    assert paths.effective_icloud(desk, "desktop", "auto") == (1, "assumed")
    assert paths.effective_icloud(desk, "desktop", "no") == (0, "user")
    assert paths.effective_icloud(dl, "downloads", "yes") == (1, "user")
    assert paths.effective_icloud(dl, "downloads", "auto") == (0, "detected")
    (drive / "Desktop").mkdir()  # S2
    assert paths.effective_icloud(desk, "desktop", "no") == (1, "detected")


def test_legacy_placeholder_and_dataless() -> None:
    assert paths.legacy_placeholder_name(".계약서.pdf.icloud") == "계약서.pdf"
    assert paths.legacy_placeholder_name("a.icloud") is None
    assert paths.legacy_placeholder_name("..icloud") is None
    assert paths.is_dataless("x", paths.SF_DATALESS) and not paths.is_dataless("x", 0)
    assert paths.is_dataless(".x.icloud", 0)


def test_probe_classifies(sandbox: Sandbox) -> None:
    assert paths.probe(str(sandbox.user), 2) == "ok"
    assert paths.probe(str(sandbox.user / "nope"), 2) == "missing"
    f = sandbox.user / "f"
    f.write_text("x")
    assert paths.probe(str(f), 2) == "not_dir"


def test_state_lock_exclusive(sandbox: Sandbox) -> None:
    a = paths.StateLock(sandbox.home, 0)
    a.acquire()
    try:
        with pytest.raises(errors.LockError) as exc:
            paths.StateLock(sandbox.home, 0.1).acquire()
        assert exc.value.details["holder_pid"] == os.getpid()
    finally:
        a.release()
    with paths.StateLock(sandbox.home, 0):
        pass
    assert oct(Path(sandbox.home / "state.lock").stat().st_mode & 0o777) == "0o600"
