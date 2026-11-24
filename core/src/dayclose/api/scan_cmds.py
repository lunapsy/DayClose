"""scan.run / scan.list / scan.show / change.list (10 §2.4, 04 §0-§3)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

from dayclose.api import pagination
from dayclose.api.runtime import Context, command
from dayclose.collect import fs
from dayclose.common import clock, ids, paths
from dayclose.common.errors import EnvironmentError_, NotFoundError, UsageError
from dayclose.store import entries, repo

ALL_COLLECTORS = ("fs", "git", "vault", "apps", "brew", "login_items")
IMPLEMENTED_COLLECTORS = ("fs",)
COLLECTOR_MILESTONE = {"git": "M2", "vault": "M3", "apps": "M3", "brew": "M3", "login_items": "M3"}
TRIGGERS = ("manual", "schedule", "app", "agent")
CHANNEL_TRIGGER = {
    "cli": "manual",
    "app": "app",
    "schedule": "schedule",
    "skill": "agent",
    "mcp": "agent",
}
EVENT_TYPES = ("created", "modified", "deleted", "moved")
CHANGE_COUNT_CAP = 10_000
_STATS_KEYS = (
    "roots",
    "entries_seen",
    "created",
    "modified",
    "deleted",
    "moved",
    "skipped_unreadable",
    "dataless_skipped",
    "baseline_entries",
    "duplicate_roots",
    "truncated_sizes",
    "dataless_dirs",
)

_ROOT_FAILURE = {
    "tcc_denied": ("E_TCC_DENIED", "macOS 개인정보 보호 설정이 모든 루트 접근을 막았습니다."),
    "timeout": ("E_VOLUME_TIMEOUT", "모든 루트가 응답하지 않습니다."),
    "missing": ("E_VOLUME_UNAVAILABLE", "스캔할 수 있는 루트가 없습니다."),
    "permission_denied": ("E_PERMISSION", "모든 루트에 접근 권한이 없습니다."),
}


def _str_list(args: dict[str, Any], key: str) -> list[str] | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        value = [v for v in value.split(",") if v]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise UsageError(f"{key} 값이 올바르지 않습니다.")
    return value


def _settings(ctx: Context) -> fs.ScanSettings:
    cfg = ctx.config
    home = paths.user_home()
    builtin = {
        os.path.abspath(ctx.home),
        os.path.join(home, paths.CACHES_REL),
        os.path.join(home, paths.LOGS_REL),
    }
    excluded_ids = set()
    for p in builtin:
        try:
            st = os.stat(p)
        except OSError:
            continue
        excluded_ids.add((st.st_dev, st.st_ino))
    return fs.ScanSettings(
        builtin_excluded_ids=frozenset(excluded_ids),
        excludes=fs.ExcludeRules.compile(cfg.get("scan.exclude_globs")),
        package_dirs_as_files=bool(cfg.get("scan.package_dirs_as_files")),
        max_entries_per_root=int(cfg.get("scan.max_entries_per_root")),
        hash_max_bytes=int(cfg.get("scan.hash_max_bytes")),
        builtin_excluded_paths=frozenset(builtin),
    )


def _run_data(run: repo.RunRow) -> dict[str, Any]:
    stats = {k: run.stats[k] for k in _STATS_KEYS if k in run.stats}
    roots = [
        {
            "root_id": ids.to_ext("root", int(r["root_id"])),
            "status": r["status"],
            "entries_seen": r["entries_seen"],
            **(
                {"duplicate_of": ids.to_ext("root", int(r["duplicate_of"]))}
                if r.get("duplicate_of") is not None
                else {}
            ),
        }
        for r in run.stats.get("root_results", [])
    ]
    return {
        "run_id": ids.to_ext("run", run.id),
        "status": run.status,
        "trigger": run.trigger,
        "collectors": run.collectors,
        "stats": stats,
        "roots": roots,
        "duration_ms": (run.finished_at - run.started_at) if run.finished_at else None,
    }


@command("scan.run", writes=True, cancellable=True)
def scan_run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    collectors = _str_list(args, "collectors") or list(IMPLEMENTED_COLLECTORS)
    for c in collectors:
        if c not in ALL_COLLECTORS:
            raise UsageError("알 수 없는 수집기입니다.", {"allowed": list(ALL_COLLECTORS)})
        if c not in IMPLEMENTED_COLLECTORS:
            raise UsageError(
                "아직 구현되지 않은 수집기입니다.",
                {"reason": "not_implemented", "collector": c, "milestone": COLLECTOR_MILESTONE[c]},
            )
    trigger = args.get("trigger") or CHANNEL_TRIGGER[ctx.channel]
    if trigger not in TRIGGERS:
        raise UsageError("알 수 없는 트리거입니다.", {"allowed": list(TRIGGERS)})
    conn = ctx.db
    active = [r for r in repo.list_roots(conn) if r.enabled]
    root_ids = _str_list(args, "root_ids")
    if root_ids:
        wanted = [ids.parse("root", v) for v in root_ids]
        by_id = {r.id: r for r in active}
        for v, rid in zip(root_ids, wanted, strict=True):
            if rid not in by_id:
                raise NotFoundError("E_NOT_FOUND", "루트를 찾을 수 없습니다.", {"id": v})
        selected = [by_id[rid] for rid in sorted(set(wanted))]
    else:
        selected = active

    started_at = clock.now_ms()
    with repo.transaction(conn):
        repo.interrupt_running_runs(conn, started_at)
        run_id = repo.create_run(
            conn,
            started_at=started_at,
            trigger=trigger,
            collectors=collectors,
            request_id=ctx.request_id,
        )
    ctx.audit.target_type = "run"
    ctx.audit.target_ids = [ids.to_ext("run", run_id)]
    ctx.audit.summary = f"scan.run roots={len(selected)}"
    try:
        result = _scan_fs(ctx, run_id, started_at, selected, active)
    except BaseException:
        with repo.transaction(conn):
            repo.finish_run(
                conn,
                run_id,
                status="interrupted",
                finished_at=clock.now_ms(),
                stats={},
                error_code="E_CANCELLED",
            )
        raise
    run = repo.get_run(conn, run_id)
    assert run is not None
    if result is not None:
        raise result
    return _run_data(run)


def _scan_fs(
    ctx: Context,
    run_id: int,
    started_at: int,
    selected: list[repo.RootRow],
    active: list[repo.RootRow],
) -> EnvironmentError_ | None:
    """Probe -> traverse -> diff -> apply. Returns the all-roots-failed error, if any."""
    conn = ctx.db
    settings = _settings(ctx)
    timeout = float(ctx.config.get("scan.volume_probe_timeout_s"))
    with repo.transaction(conn):
        for r in selected:
            synced, source = paths.effective_icloud(r.path, r.kind, r.icloud_synced_mode)
            repo.update_root_icloud(conn, r.id, synced, source)

    results: dict[int, dict[str, Any]] = {}
    traversals: dict[int, fs.Traversal] = {}
    identities: dict[tuple[int, int], int] = {}
    stats = dict.fromkeys(_STATS_KEYS, 0)
    stats["roots"] = len(selected)
    failures: list[str] = []
    # Probe every active root once (also the unselected ones: their directory identities
    # are needed to prune nested roots, 04 §1.1). A root that does not answer is skipped.
    access_of: dict[int, str] = {}
    root_ident: dict[int, tuple[int, int]] = {}
    for r in active:
        access = paths.probe(r.path, timeout)
        access_of[r.id] = "missing" if access == "not_dir" else access
        if access_of[r.id] == "ok":
            try:
                st = os.stat(r.path)
            except OSError:
                continue
            root_ident[r.id] = (st.st_dev, st.st_ino)
    for r in selected:
        access = access_of.get(r.id, "missing")
        if access != "ok":
            failures.append(access)
            status = "tcc_denied" if access == "tcc_denied" else "unavailable"
            results[r.id] = {"root_id": r.id, "status": status, "entries_seen": 0, "traversed": 0}
            if access == "tcc_denied":
                ctx.warn(
                    "W_TCC_DENIED",
                    "macOS 개인정보 보호 설정 때문에 루트를 건너뛰었습니다.",
                    {"root_id": ids.to_ext("root", r.id)},
                )
            else:
                ctx.warn(
                    "W_ROOT_UNAVAILABLE",
                    "접근할 수 없는 루트를 건너뛰었습니다.",
                    {"root_id": ids.to_ext("root", r.id), "reason": access},
                )
            continue
        ident = root_ident.get(r.id)
        # The smallest active root id with this identity owns it (04 §1.1), even when only a
        # larger duplicate was selected with --root.
        owner = min((k for k, v in root_ident.items() if v == ident), default=r.id)
        if ident is not None and owner != r.id:
            identities.setdefault(ident, owner)
        if ident is not None and ident in identities:
            stats["duplicate_roots"] += 1
            results[r.id] = {
                "root_id": r.id,
                "status": "ok",
                "entries_seen": 0,
                "traversed": 0,
                "duplicate_of": identities[ident],
            }
            continue
        if ident is not None:
            identities[ident] = r.id
        inner = [v for k, v in root_ident.items() if k != r.id]
        unreachable = [o.path for o in active if o.id != r.id and o.id not in root_ident]
        spec = fs.RootSpec(id=r.id, path=r.path, kind=r.kind, max_depth=r.max_depth)

        def progress(root_id: int, done: int) -> None:
            ctx.emit_progress(
                {"phase": "fs", "root_id": ids.to_ext("root", root_id), "done": done, "total": None}
            )

        tr = fs.traverse(spec, settings, inner, progress if ctx.progress else None, unreachable)
        traversals[r.id] = tr
        if not tr.traversed:
            failures.append(tr.access)
            results[r.id] = {
                "root_id": r.id,
                "status": tr.status,
                "entries_seen": 0,
                "traversed": 0,
            }
            code = "W_TCC_DENIED" if tr.status == "tcc_denied" else "W_ROOT_UNAVAILABLE"
            ctx.warn(
                code,
                "접근할 수 없는 루트를 건너뛰었습니다.",
                {"root_id": ids.to_ext("root", r.id), "reason": tr.access},
            )
            continue
        results[r.id] = {
            "root_id": r.id,
            "status": tr.status,
            "entries_seen": tr.entries_seen,
            "traversed": 1,
        }
        _traversal_warnings(ctx, r.id, tr)
        stats["entries_seen"] += tr.entries_seen
        stats["skipped_unreadable"] += tr.permission_skipped + tr.tcc_skipped
        stats["dataless_skipped"] += tr.dataless_files
        stats["dataless_dirs"] += tr.dataless_dirs
        stats["truncated_sizes"] += tr.truncated_sizes

    done = {rid: tr for rid, tr in traversals.items() if tr.traversed}
    counts = entries.ApplyCounts()
    changes: entries.Changes | None = None
    baseline: set[int] = set()
    if done:
        already = repo.traversed_root_ids(conn)
        baseline = {rid for rid in done if rid not in already}
        prev = entries.load_present_entries(conn)
        observations = [o for tr in done.values() for o in tr.obs]
        changes = fs.diff(
            prev,
            observations,
            set(done),
            _safe_predicate(done),
            fs.make_hasher(settings.hash_max_bytes),
        )
    if stats["dataless_skipped"]:
        ctx.warn(
            "W_DATALESS_SKIPPED",
            "iCloud 미다운로드 파일은 메타데이터만 기록했습니다.",
            {"count": stats["dataless_skipped"]},
        )

    all_failed = (
        bool(failures)  # only duplicates selected is not a failure
        and not done
        and len(failures) == len([r for r in results.values() if not r.get("duplicate_of")])
    )
    if all_failed:
        run_status = "failed"
    elif all(r["status"] == "ok" for r in results.values()):
        run_status = "completed"
    else:
        run_status = "partial"
    error: EnvironmentError_ | None = None
    if all_failed:
        code, msg = _ROOT_FAILURE.get(failures[0], _ROOT_FAILURE["missing"])
        error = EnvironmentError_(code, msg, {"run_id": ids.to_ext("run", run_id)})
    with repo.transaction(conn):
        if changes is not None:
            counts = entries.apply_changes(conn, run_id, started_at, changes, baseline)
        for k in ("created", "modified", "deleted", "moved", "baseline_entries"):
            stats[k] = getattr(counts, k)
        stored = {
            **stats,
            "warning_codes": sorted({w.code for w in ctx.warnings}),
            "root_results": [results[r.id] for r in selected],
        }
        repo.finish_run(
            conn,
            run_id,
            status=run_status,
            finished_at=clock.now_ms(),
            stats=stored,
            error_code=error.code if error else None,
        )
    return error


def _safe_predicate(done: dict[int, fs.Traversal]) -> Any:
    def is_safe(p: entries.Prev) -> bool:
        tr = done.get(p.root_id)
        if tr is None:
            return True
        if tr.truncated:
            return True
        return any(paths.is_under(p.path, pre) for pre in tr.safe_prefixes)

    return is_safe


def _traversal_warnings(ctx: Context, root_id: int, tr: fs.Traversal) -> None:
    rid = ids.to_ext("root", root_id)
    if tr.permission_skipped:
        ctx.warn(
            "W_PERMISSION_SKIPPED",
            "읽을 수 없는 하위 경로를 건너뛰었습니다.",
            {"root_id": rid, "count": tr.permission_skipped},
        )
    if tr.tcc_skipped:
        ctx.warn(
            "W_TCC_DENIED",
            "macOS 개인정보 보호 설정 때문에 하위 경로를 건너뛰었습니다.",
            {"root_id": rid, "count": tr.tcc_skipped},
        )
    if tr.partial_dirs:
        ctx.warn(
            "W_PARTIAL_SCAN",
            "항목이 너무 많은 폴더의 하위 폴더는 건너뛰었습니다.",
            {"root_id": rid, "count": tr.partial_dirs},
        )
    if tr.truncated:
        ctx.warn(
            "W_TRUNCATED",
            "루트당 항목 상한에 도달해 순회를 멈췄습니다.",
            {"root_id": rid, "reason": "max_entries_per_root"},
        )
    if tr.truncated_sizes:
        ctx.warn(
            "W_TRUNCATED",
            "패키지 크기 계산을 상한에서 멈췄습니다.",
            {"root_id": rid, "reason": "package_size", "count": tr.truncated_sizes},
        )


@command("scan.show")
def scan_show(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    value = args.get("run_id")
    if not isinstance(value, str):
        raise UsageError("RUN_ID 가 필요합니다.")
    run = repo.get_run(ctx.db, ids.parse("run", value))
    if run is None:
        raise NotFoundError("E_NOT_FOUND", "스캔 기록을 찾을 수 없습니다.", {"id": value})
    data = _run_data(run)
    data["started_at"] = clock.ms_to_rfc3339(run.started_at)
    data["finished_at"] = clock.ms_to_rfc3339(run.finished_at) if run.finished_at else None
    data["error_code"] = run.error_code
    return data


@command("scan.list")
def scan_list(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    limit = pagination.limit_of(args)
    filters: dict[str, Any] = {}
    after = pagination.decode(args.get("cursor"), filters, 2)
    rows, total = repo.list_runs(ctx.db, limit=limit, after=(after[0], after[1]) if after else None)
    page, more = pagination.page(rows, limit)
    items = []
    for run in page:
        items.append(
            {
                "run_id": ids.to_ext("run", run.id),
                "started_at": clock.ms_to_rfc3339(run.started_at),
                "finished_at": clock.ms_to_rfc3339(run.finished_at) if run.finished_at else None,
                "status": run.status,
                "trigger": run.trigger,
                "collectors": run.collectors,
                "stats": {k: run.stats[k] for k in _STATS_KEYS if k in run.stats},
            }
        )
    cursor = pagination.encode([page[-1].started_at, page[-1].id], filters) if more else None
    return {"items": items, "next_cursor": cursor, "total": total}


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _since_ms(ctx: Context, value: str) -> int:
    """`YYYY-MM-DD` = start of that review date (local, day_boundary), or RFC 3339 (10 §1.4)."""
    try:
        if _DATE_RE.match(value):
            hh, mm = (int(x) for x in str(ctx.config.get("review.day_boundary")).split(":"))
            local = datetime.strptime(value, "%Y-%m-%d").astimezone()
            start = local.replace(hour=0, minute=0) + timedelta(hours=hh, minutes=mm)
            return int(start.timestamp() * 1000)
        return int(clock.parse_rfc3339(value).timestamp() * 1000)
    except ValueError:
        raise UsageError("--since 는 YYYY-MM-DD 또는 RFC 3339 시각이어야 합니다.") from None


@command("change.list")
def change_list(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.db
    run_value = args.get("run_id")
    since_value = args.get("since")
    if run_value is not None and since_value is not None:
        raise UsageError("--run 과 --since 는 함께 쓸 수 없습니다.")
    run_id: int | None = None
    since_ms: int | None = None
    if isinstance(run_value, str):
        run_id = ids.parse("run", run_value)
        if repo.get_run(conn, run_id) is None:
            raise NotFoundError("E_NOT_FOUND", "스캔 기록을 찾을 수 없습니다.", {"id": run_value})
    elif isinstance(since_value, str):
        since_ms = _since_ms(ctx, since_value)
    else:
        run_id = repo.latest_run_id(conn)
    events = _str_list(args, "event")
    if events:
        bad = [e for e in events if e not in EVENT_TYPES]
        if bad:
            raise UsageError("알 수 없는 이벤트 종류입니다.", {"allowed": list(EVENT_TYPES)})
    root_id: int | None = None
    root_value = args.get("root_id")
    if isinstance(root_value, str):
        root_id = ids.parse("root", root_value)
        if repo.get_root(conn, root_id, include_removed=True) is None:
            raise NotFoundError("E_NOT_FOUND", "루트를 찾을 수 없습니다.", {"id": root_value})
    limit = pagination.limit_of(args)
    filters = {"run": run_id, "since": since_ms, "event": sorted(events or []), "root": root_id}
    after = pagination.decode(args.get("cursor"), filters, 2)
    if run_id is None and since_ms is None:
        return {"items": [], "next_cursor": None, "total": 0}
    rows, total = repo.list_events(
        conn,
        run_id=run_id,
        since_ms=since_ms,
        events=events,
        root_id=root_id,
        limit=limit,
        after=(after[0], after[1]) if after else None,
        count_cap=CHANGE_COUNT_CAP,
    )
    if total is None:
        ctx.warn(
            "W_TRUNCATED", "변경이 많아 전체 개수를 세지 않았습니다.", {"limit": CHANGE_COUNT_CAP}
        )
    page, more = pagination.page(rows, limit)
    items = [
        {
            "id": ids.to_ext("event", e.id),
            "run_id": ids.to_ext("run", e.run_id),
            "entry_id": ids.to_ext("entry", e.entry_id),
            "event": e.event,
            "kind": e.kind,
            "old_path": e.old_path,
            "new_path": e.new_path,
            "display_path": paths.display_path(os.path.dirname(e.new_path or e.old_path or "")),
            "size_delta": e.size_delta,
            "detected_at": clock.ms_to_rfc3339(e.detected_at),
        }
        for e in page
    ]
    cursor = pagination.encode([page[-1].detected_at, page[-1].id], filters) if more else None
    return {"items": items, "next_cursor": cursor, "total": total}
