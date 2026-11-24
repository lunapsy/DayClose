"""root.list / root.add / root.remove (02 §5.3, 10 §2.3)."""

from __future__ import annotations

import sqlite3
from typing import Any

from dayclose.api import pagination
from dayclose.api.runtime import Context, command
from dayclose.common import clock, ids, paths
from dayclose.common.errors import EnvironmentError_, NotFoundError, UsageError
from dayclose.store import repo

ROOT_KINDS = (
    "downloads",
    "desktop",
    "screenshots",
    "documents",
    "icloud_drive",
    "projects",
    "vault_extra",
    "custom",
)
ICLOUD_MODES = ("auto", "yes", "no")
# kind -> (max_depth, file_level) defaults (04 §1.1 table; custom 6/1; vault_extra per 05 §2.1.1).
KIND_DEFAULTS: dict[str, tuple[int, bool]] = {
    "downloads": (6, True),
    "desktop": (6, True),
    "screenshots": (2, True),
    "documents": (8, True),
    "icloud_drive": (8, True),
    "projects": (2, False),
    "custom": (6, True),
    "vault_extra": (4, False),
}


def root_json(root: repo.RootRow, *, with_removed: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": ids.to_ext("root", root.id),
        "path": root.path,
        "display_path": paths.display_path(root.path),
        "kind": root.kind,
        "enabled": root.enabled,
        "max_depth": root.max_depth,
        "file_level": root.file_level,
        "icloud_synced": root.icloud_synced,
        "icloud_synced_mode": root.icloud_synced_mode,
        "icloud_synced_source": root.icloud_synced_source,
        "created_at": clock.ms_to_rfc3339(root.created_at),
    }
    if with_removed:
        out["removed_at"] = (
            None if root.removed_at is None else clock.ms_to_rfc3339(root.removed_at)
        )
    return out


def overlaps(conn: sqlite3.Connection, root: repo.RootRow) -> list[str]:
    out = []
    for other in repo.list_roots(conn):
        if other.id == root.id:
            continue
        if paths.is_under(other.path, root.path) or paths.is_under(root.path, other.path):
            out.append(ids.to_ext("root", other.id))
    return out


def access_error(access: str) -> EnvironmentError_ | NotFoundError | UsageError | None:
    if access == "ok":
        return None
    if access == "missing":
        return NotFoundError("E_NOT_FOUND", "경로가 없습니다.", {"reason": "missing"})
    if access == "not_dir":
        return UsageError("디렉터리가 아닙니다.", {"reason": "not_a_directory"})
    if access == "tcc_denied":
        return EnvironmentError_(
            "E_TCC_DENIED", "macOS 개인정보 보호 설정이 접근을 막았습니다.", {"reason": "tcc"}
        )
    if access == "timeout":
        return EnvironmentError_(
            "E_VOLUME_TIMEOUT",
            "볼륨이 응답하지 않습니다. 전체 디스크 접근 권한을 확인하세요.",
            {"reason": "probe_timeout"},
        )
    return EnvironmentError_("E_PERMISSION", "접근 권한이 없습니다.", {"reason": "permission"})


def register_root(
    ctx: Context,
    path: str,
    kind: str,
    max_depth: int | None,
    icloud_mode: str,
    file_level: bool | None = None,
) -> tuple[repo.RootRow, bool]:
    """Insert an active root (idempotent by path). The caller has checked access."""
    existing = repo.active_root_by_path(ctx.db, path)
    if existing is not None:
        return existing, False
    default_depth, default_level = KIND_DEFAULTS[kind]
    if max_depth is None:
        max_depth = default_depth
    level = default_level if file_level is None else file_level
    synced, source = paths.effective_icloud(path, kind, icloud_mode)
    root = repo.insert_root(
        ctx.db,
        path=path,
        kind=kind,
        max_depth=max_depth,
        file_level=level,
        icloud_mode=icloud_mode,
        icloud_synced=synced,
        icloud_source=source,
        created_at=clock.now_ms(),
    )
    return root, True


@command("root.list")
def root_list(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    include_removed = bool(args.get("all"))
    limit = pagination.limit_of(args)
    filters = {"all": include_removed}
    after = pagination.decode(args.get("cursor"), filters, 1)
    rows = repo.list_roots(ctx.db, include_removed=include_removed)
    total = len(rows)
    if after is not None:
        rows = [r for r in rows if r.id > after[0]]
    page, more = pagination.page(rows, limit)
    return {
        "items": [root_json(r, with_removed=include_removed) for r in page],
        "next_cursor": pagination.encode([page[-1].id], filters) if more else None,
        "total": total,
    }


@command("root.add", writes=True)
def root_add(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("path")
    kind = args.get("kind")
    if not isinstance(raw, str) or not raw:
        raise UsageError("PATH 가 필요합니다.")
    if kind not in ROOT_KINDS:
        raise UsageError("알 수 없는 루트 종류입니다.", {"allowed": list(ROOT_KINDS)})
    max_depth = args.get("max_depth")
    if max_depth is not None and (
        not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0
    ):
        raise UsageError("--max-depth 는 0 이상의 정수여야 합니다.")
    mode = args.get("icloud_synced") or "auto"
    if mode not in ICLOUD_MODES:
        raise UsageError("--icloud-synced 값이 올바르지 않습니다.", {"allowed": list(ICLOUD_MODES)})
    path = paths.normalize_user_path(raw)
    paths.check_path_in_sandbox(path)
    err = access_error(paths.probe(path, float(ctx.config.get("scan.volume_probe_timeout_s"))))
    if err is not None:
        raise err
    with repo.transaction(ctx.db):
        root, created = register_root(ctx, path, kind, max_depth, mode)
    ctx.audit.target_type = "root"
    ctx.audit.target_ids = [ids.to_ext("root", root.id)]
    ctx.audit.summary = f"root.add kind={root.kind}"
    body = root_json(root)
    body["overlaps"] = overlaps(ctx.db, root)
    return {"root": body, "created": created}


@command("root.remove", writes=True)
def root_remove(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    value = args.get("root_id")
    if not isinstance(value, str):
        raise UsageError("ROOT_ID 가 필요합니다.")
    root_id = ids.parse("root", value)
    root = repo.get_root(ctx.db, root_id)
    if root is None:
        raise NotFoundError("E_NOT_FOUND", "루트를 찾을 수 없습니다.", {"id": value})
    removed_at = clock.now_ms()
    with repo.transaction(ctx.db):
        repo.remove_root(ctx.db, root_id, removed_at)
    ctx.audit.target_type = "root"
    ctx.audit.target_ids = [value]
    ctx.audit.summary = "root.remove"
    # Review items arrive in M2; until then no open item can be affected.
    return {
        "root_id": value,
        "removed_at": clock.ms_to_rfc3339(removed_at),
        "open_items_affected": 0,
    }
