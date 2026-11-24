"""core.version / core.init / core.doctor (10 §2.1)."""

from __future__ import annotations

import os
import platform
import secrets
import sqlite3
from typing import Any

from dayclose import __version__
from dayclose import config as config_mod
from dayclose.api import root_cmds
from dayclose.api.runtime import Context, command, is_initialized
from dayclose.common import clock, envelope, fsmeta, ids, paths, proc
from dayclose.common.errors import DayCloseError, EnvironmentError_, UsageError
from dayclose.store import db as store_db
from dayclose.store import repo

DEFAULTS_TIMEOUT_S = 5.0


@command("core.version", needs_init=False)
def core_version(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    version = store_db.read_user_version(store_db.db_path(ctx.home))
    return {
        "core_version": __version__,
        "contract_version": envelope.CONTRACT_VERSION,
        "db_schema_version": version,
        "db_schema_supported": store_db.latest_version(),
        "python": platform.python_version(),
        "home": str(ctx.home),
        "initialized": is_initialized(ctx.home),
    }


def _default_device_name() -> str:
    name = platform.node()
    return name[: -len(".local")] if name.endswith(".local") else name


def _new_device_id() -> str:
    return "dev_" + secrets.token_hex(4)


def _screenshot_location(ctx: Context) -> str | None:
    """`defaults read com.apple.screencapture location` (09 §10.3)."""
    try:
        res = proc.run_tool(
            "defaults", ["read", "com.apple.screencapture", "location"], DEFAULTS_TIMEOUT_S
        )
    except EnvironmentError_:
        ctx.warn(
            "W_TOOL_MISSING",
            "defaults 도구를 찾을 수 없어 스크린샷 위치를 건너뜁니다.",
            {"tool": "defaults"},
        )
        return None
    if res.timed_out or res.returncode != 0:
        return None
    value = res.stdout.decode("utf-8", errors="replace").strip()
    if not value:
        return None
    if value == "~" or value.startswith("~/"):
        value = str(paths.user_home()) + value[1:]
    if not os.path.isabs(value):
        ctx.warn(
            "W_ROOT_UNAVAILABLE",
            "스크린샷 저장 위치가 절대 경로가 아니어서 무시했습니다.",
            {"kind": "screenshots", "reason": "not_absolute"},
        )
        return None
    return os.path.abspath(value)


def _default_roots(ctx: Context) -> list[tuple[str, str, int | None, bool]]:
    """(path, kind, max_depth, file_level) per 04 §1.1 / FR-CORE-002. Home-relative only."""
    home = str(paths.user_home())
    roots: list[tuple[str, str, int | None, bool]] = [
        (os.path.join(home, "Downloads"), "downloads", 6, True),
        (os.path.join(home, "Desktop"), "desktop", 6, True),
    ]
    shot = _screenshot_location(ctx)
    documents = os.path.join(home, "Documents")
    icloud = os.path.join(home, paths.ICLOUD_DRIVE_REL)
    file_roots = [r[0] for r in roots] + [documents, icloud]
    if shot is not None and not any(paths.is_under(shot, r) for r in file_roots):
        roots.append((shot, "screenshots", 2, True))
    roots.append((documents, "documents", 8, True))
    roots.append((icloud, "icloud_drive", 8, True))
    for proj in ctx.config.get("projects.roots"):
        p = paths.normalize_user_path(proj)
        if paths.is_under(p, home):
            roots.append((p, "projects", 2, False))
    derived = os.path.join(home, "Library/Developer/Xcode/DerivedData")
    if os.path.isdir(derived):
        roots.append((derived, "custom", 1, False))
    return roots


@command("core.init", writes=True, needs_init=False)
def core_init(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    name_arg = args.get("device_name")
    if name_arg is not None and (not isinstance(name_arg, str) or not name_arg.strip()):
        raise UsageError("--device-name 이 비어 있습니다.")
    try:
        home_created = store_db.ensure_home(ctx.home)
    except OSError:
        raise EnvironmentError_(
            "E_PERMISSION", "상태 디렉터리를 만들 수 없습니다.", {"reason": "mkdir_failed"}
        ) from None
    ctx.acquire_lock()
    path = store_db.db_path(ctx.home)
    db_created = not path.exists()
    conn = store_db.connect(path, create=True)
    ctx.conn = conn
    migrated_from = store_db.migrate(conn, ctx.home)
    if db_created:
        migrated_from = None

    cfg_existing, cfg_warnings = config_mod.load(ctx.home)
    ctx.warnings.extend(cfg_warnings)
    cfg_exists = config_mod.config_path(ctx.home).is_file()
    now = clock.now_ms()
    with repo.transaction(conn):
        device_id = repo.meta_get(conn, "device_id")
        if device_id is None:
            device_id = (
                cfg_existing.device_id
                if cfg_exists and cfg_existing.device_id
                else (_new_device_id())
            )
            repo.meta_set(conn, "device_id", device_id)
        if repo.meta_get(conn, "created_at") is None:
            repo.meta_set(conn, "created_at", str(now))
        repo.meta_set(conn, "contract_version", str(envelope.CONTRACT_VERSION))
        if repo.meta_get(conn, "host_uuid_sha256") is None:
            host = fsmeta.host_uuid_sha256()
            if host is not None:
                repo.meta_set(conn, "host_uuid_sha256", host)
    if not cfg_exists:
        values = {
            "schema_version": config_mod.SCHEMA_VERSION,
            "device_id": device_id,
            "device_name": (name_arg or "").strip() or _default_device_name(),
        }
        config_mod.save(ctx.home, values)
    ctx.cfg, more = config_mod.load(ctx.home)
    ctx.warnings.extend(more)

    added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if not args.get("no_default_roots"):
        timeout = float(ctx.config.get("scan.volume_probe_timeout_s"))
        for rpath, kind, depth, level in _default_roots(ctx):
            if repo.active_root_by_path(conn, rpath) is not None:
                continue
            try:
                paths.check_path_in_sandbox(rpath)
            except DayCloseError:
                skipped.append({"path": rpath, "reason": "outside_sandbox"})
                continue
            access = paths.probe(rpath, timeout)
            if access != "ok":
                reason = "missing" if access in ("missing", "not_dir") else access
                skipped.append({"path": rpath, "reason": reason})
                ctx.warn(
                    "W_ROOT_UNAVAILABLE",
                    "기본 루트 경로가 없어 등록하지 않았습니다.",
                    {"kind": kind, "reason": reason},
                )
                continue
            with repo.transaction(conn):
                root, created = root_cmds.register_root(
                    ctx, rpath, kind, depth, "auto", file_level=level
                )
            if created:
                added.append(
                    {"id": ids.to_ext("root", root.id), "path": root.path, "kind": root.kind}
                )
    for suffix in ("-wal", "-shm"):
        p = store_db.db_path(ctx.home).with_name(store_db.DB_NAME + suffix)
        if p.exists():
            os.chmod(p, 0o600)
    ctx.audit.target_type = "device"
    ctx.audit.target_ids = [device_id]
    ctx.audit.summary = f"core.init roots_added={len(added)}"
    return {
        "home": str(ctx.home),
        "created": home_created or db_created,
        "db_schema_version": store_db.user_version(conn),
        "migrated_from": migrated_from,
        "device_id": device_id,
        "device_name": ctx.config.get("device_name"),
        "roots_added": added,
        "roots_skipped": skipped,
    }


# --------------------------------------------------------------------------- doctor


_ACCESS_ISSUES = {
    "tcc_denied": (
        "W_TCC_DENIED",
        "{p} 에 접근할 수 없습니다. 전체 디스크 접근 권한과 앱 재서명 여부를 확인하세요.",
    ),
    "timeout": (
        "W_ROOT_UNAVAILABLE",
        "{p} 가 응답하지 않습니다. 전체 디스크 접근 권한과 앱 재서명 여부를 확인하세요.",
    ),
    "missing": ("W_ROOT_UNAVAILABLE", "{p} 경로가 없습니다."),
    "permission_denied": ("W_PERMISSION_SKIPPED", "{p} 를 읽을 권한이 없습니다(파일 권한)."),
}


def _issue(code: str | None, message: str, target: str | None) -> dict[str, Any]:
    return {"code": code, "message": message, "target": target}


@command("core.doctor", needs_init=False)
def core_doctor(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Root access, DB integrity/permissions, device identity (M1 scope of FR-CORE-005)."""
    issues: list[dict[str, Any]] = []
    if not is_initialized(ctx.home):
        issues.append(_issue(None, "초기화되지 않았습니다. dayclose init 을 실행하세요.", None))
        return {"healthy": False, "issues": issues, "device": None, "roots": [], "db": None}
    cfg, cfg_warnings = config_mod.load(ctx.home)
    ctx.cfg = cfg
    ctx.warnings.extend(cfg_warnings)
    path = store_db.db_path(ctx.home)
    db_info: dict[str, Any] = {
        "path": str(path),
        "integrity": "failed",
        "schema_version": None,
        "mode": paths.mode_string(str(path)),
        "home_mode": paths.mode_string(str(ctx.home)),
        "wal_bytes": _size(str(path) + "-wal"),
    }
    roots_out: list[dict[str, Any]] = []
    device: dict[str, Any] = {
        "device_id": cfg.device_id or None,
        "db_device_id": None,
        "device_name": cfg.get("device_name") or None,
        "host_check": "skipped",
        "missing_roots": [],
    }
    conn: sqlite3.Connection | None = None
    try:
        conn = store_db.connect(path)
        db_info["integrity"] = "ok" if store_db.quick_check(conn) else "failed"
        db_info["schema_version"] = store_db.user_version(conn)
    except (DayCloseError, sqlite3.DatabaseError):
        db_info["integrity"] = "failed"
    if db_info["integrity"] != "ok":
        issues.append(_issue(None, "DB 무결성 검사에 실패했습니다. 백업에서 복원하세요.", None))
    if db_info["mode"] != "0600":
        issues.append(_issue(None, "DB 파일 권한이 0600 이 아닙니다.", None))
    if db_info["home_mode"] != "0700":
        issues.append(_issue(None, "상태 디렉터리 권한이 0700 이 아닙니다.", None))
    if conn is not None and db_info["integrity"] == "ok":
        try:
            db_device = repo.meta_get(conn, "device_id")
            device["db_device_id"] = db_device
            # M1: device_id only. The host-UUID comparison arrives with M5 (10 §2.1).
            if db_device != cfg.device_id:
                issues.append(
                    _issue(
                        "W_DEVICE_MISMATCH",
                        "이 DB 는 다른 Mac 에서 만들어진 것 같습니다. "
                        "이 Mac 에서는 dayclose init 으로 새로 시작하세요.",
                        None,
                    )
                )
            timeout = float(cfg.get("scan.volume_probe_timeout_s"))
            for root in repo.list_roots(conn):
                rid = ids.to_ext("root", root.id)
                access = paths.probe(root.path, timeout)
                if access == "not_dir":
                    access = "missing"
                if access == "missing":
                    device["missing_roots"].append(rid)
                roots_out.append(
                    {
                        "root_id": rid,
                        "display_path": paths.display_path(root.path),
                        "kind": root.kind,
                        "access": access,
                    }
                )
                if access in _ACCESS_ISSUES:
                    code, msg = _ACCESS_ISSUES[access]
                    issues.append(_issue(code, msg.format(p=paths.display_path(root.path)), rid))
        finally:
            conn.close()
    elif conn is not None:
        conn.close()
    return {
        "healthy": not issues,
        "issues": issues,
        "device": device,
        "roots": roots_out,
        "db": db_info,
    }


def _size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0
