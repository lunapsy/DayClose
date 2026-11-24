"""FR-CORE-005 and 02 §8.1: doctor - root access, TCC vs permission, DB, device identity."""

from __future__ import annotations

import errno
import sqlite3
from pathlib import Path
from typing import Any

from conftest import Sandbox
from inproc import init, ok, run

from dayclose.common import paths

# --------------------------------------------------------------------------- FR-CORE-005


def _eperm_for(target: Path) -> Any:
    real = paths._default_probe_stat

    def probe_stat(path: str) -> None:
        if path == str(target):
            raise PermissionError(errno.EPERM, "Operation not permitted", path)
        if path.endswith("noaccess"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        real(path)

    return probe_stat


def test_fr_core_005_doctor_root_access(sandbox: Sandbox) -> None:
    init()
    desk = sandbox.mkdir("Desktop")
    dl = sandbox.mkdir("Downloads")
    gone = sandbox.mkdir("Gone")
    for p, kind in ((dl, "downloads"), (desk, "desktop"), (gone, "custom")):
        ok("root.add", path=str(p), kind=kind)
    gone.rmdir()
    paths.probe_stat = _eperm_for(desk)
    d = ok("core.doctor")
    access = {r["display_path"]: r["access"] for r in d["roots"]}
    assert access == {"~/Downloads": "ok", "~/Desktop": "tcc_denied", "~/Gone": "missing"}
    assert d["healthy"] is False
    codes = {(i["code"], i["target"]) for i in d["issues"]}
    assert ("W_TCC_DENIED", "root_2") in codes and ("W_ROOT_UNAVAILABLE", "root_3") in codes
    assert d["device"]["missing_roots"] == ["root_3"]
    assert not any(i["code"] == "W_DEVICE_MISMATCH" for i in d["issues"])  # missing != copied
    assert d["db"]["integrity"] == "ok" and d["db"]["mode"] == "0600"
    assert d["db"]["home_mode"] == "0700"


def test_fr_core_005_tcc_vs_permission_distinct(sandbox: Sandbox) -> None:
    init()
    tcc = sandbox.mkdir("Desktop")
    plain = sandbox.mkdir("noaccess")
    ok("root.add", path=str(tcc), kind="desktop")
    ok("root.add", path=str(plain), kind="custom")
    paths.probe_stat = _eperm_for(tcc)
    d = ok("core.doctor")
    assert [r["access"] for r in d["roots"]] == ["tcc_denied", "permission_denied"]
    env, code = run("root.add", path=str(sandbox.mkdir("noaccess2/x/noaccess")), kind="custom")
    assert code == 6 and env["error"]["code"] == "E_PERMISSION"


def test_doctor_healthy_and_uninitialized(sandbox: Sandbox) -> None:
    d = ok("core.doctor")
    assert d["healthy"] is False and d["db"] is None
    init()
    ok("root.add", path=str(sandbox.mkdir("Downloads")), kind="downloads")
    d = ok("core.doctor")
    assert d["healthy"] is True and d["issues"] == []


def test_doctor_device_mismatch_copied_db(sandbox: Sandbox) -> None:
    init()
    cfg = sandbox.home / "config.toml"
    original = cfg.read_text()
    # (a) DB copied from another Mac: config device_id differs from app_meta.device_id.
    cfg.write_text(original.replace('device_id = "dev_', 'device_id = "dev_0'))
    d = ok("core.doctor")
    assert d["healthy"] is False and d["device"]["db_device_id"] != d["device"]["device_id"]
    assert any(i["code"] == "W_DEVICE_MISMATCH" for i in d["issues"])
    # (b) is M5: DB and config copied together (same device_id, other host hash). In M1 the
    # host check is reported as skipped and is not an issue.
    cfg.write_text(original)
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    conn.execute("UPDATE app_meta SET value='00' WHERE key='host_uuid_sha256'")
    conn.commit()
    conn.close()
    d = ok("core.doctor")
    assert d["device"]["host_check"] == "skipped"
    assert not any(i["code"] == "W_DEVICE_MISMATCH" for i in d["issues"])


def test_doctor_missing_root_is_access_not_device(sandbox: Sandbox) -> None:
    init()
    gone = sandbox.mkdir("Gone")
    ok("root.add", path=str(gone), kind="custom")
    gone.rmdir()
    d = ok("core.doctor")
    assert d["roots"][0]["access"] == "missing"
    assert [i["code"] for i in d["issues"]] == ["W_ROOT_UNAVAILABLE"]


def test_host_uuid_is_hashed_not_stored(sandbox: Sandbox) -> None:
    init()
    import uuid

    from dayclose.common import fsmeta

    raw = fsmeta._gethostuuid()
    assert raw is not None
    blob = (sandbox.home / "dayclose.db").read_bytes()
    for wal in sandbox.home.glob("dayclose.db-wal"):
        blob += wal.read_bytes()
    assert raw not in blob and str(uuid.UUID(bytes=raw)).encode() not in blob
    conn = sqlite3.connect(sandbox.home / "dayclose.db")
    stored = conn.execute("SELECT value FROM app_meta WHERE key='host_uuid_sha256'").fetchone()
    conn.close()
    assert stored[0] == fsmeta.host_uuid_sha256()


def test_corrupt_db_reported(sandbox: Sandbox) -> None:
    init()
    db = sandbox.home / "dayclose.db"
    for side in ("dayclose.db-wal", "dayclose.db-shm"):
        (sandbox.home / side).unlink(missing_ok=True)
    data = bytearray(db.read_bytes())
    data[0:16] = b"\x00" * 16  # destroy the header
    db.write_bytes(bytes(data))
    env, code = run("root.list")
    assert code == 10 and env["error"]["code"] == "E_DB_CORRUPT"
    d = ok("core.doctor")  # doctor never returns E_DB_CORRUPT (10 §2.1)
    assert d["healthy"] is False and d["db"]["integrity"] == "failed"
