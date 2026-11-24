"""Command registry and the single execution path shared by every transport (02 §5, 10 §1).

`execute()` validates the environment (sandbox), opens config/DB, takes the write lock for
W commands, runs the handler, records the audit row and builds the envelope.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dayclose import __version__
from dayclose import config as config_mod
from dayclose.common import clock, envelope, paths
from dayclose.common import logging as dlog
from dayclose.common.envelope import Warning_
from dayclose.common.errors import (
    CancelledError,
    DayCloseError,
    InternalError,
    NotFoundError,
    SafetyError,
    UsageError,
)
from dayclose.plan.approval import AGENT_ENV_MARKERS
from dayclose.store import db as store_db
from dayclose.store import repo

CHANNELS = ("cli", "app", "skill", "mcp", "schedule")
LOG_LEVELS = ("debug", "info", "warn", "error")
AGENT_CHANNELS = ("skill", "mcp")
# 02 §10.3-3: the scheduler may call exactly these; everything else is refused at entry.
SCHEDULE_ALLOWED = frozenset({"scan.run", "review.summary"})
# 02 §10.3-4b / 10 §1.8, M1a part: owner-only commands and config keys.
OWNER_ONLY_COMMANDS = frozenset({"core.init", "root.add", "root.remove"})
OWNER_ONLY_KEY_PREFIXES = ("protection.", "vault.", "icloud.")
OWNER_ONLY_KEYS = frozenset({"scan.exclude_globs", "ai.allow_external"})


@dataclass
class Options:
    home: str | None = None
    channel: str = "cli"
    wait_lock: float = 10.0
    progress: str | None = None
    log_level: str = "info"


@dataclass
class Audit:
    target_type: str | None = None
    target_ids: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class Context:
    command: str
    home: Path
    home_overridden: bool
    channel: str
    requested_channel: str
    wait_lock: float
    progress: bool
    log_level: str
    request_id: str
    warnings: list[Warning_] = field(default_factory=list)
    cfg: config_mod.Config | None = None
    conn: sqlite3.Connection | None = None
    audit: Audit = field(default_factory=Audit)
    lock: paths.StateLock | None = None

    def warn(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.warnings.append(Warning_(code, message, dict(details or {})))

    @property
    def db(self) -> sqlite3.Connection:
        assert self.conn is not None, "command needs an initialized DB"
        return self.conn

    @property
    def config(self) -> config_mod.Config:
        assert self.cfg is not None, "command needs a loaded config"
        return self.cfg

    def emit_progress(self, event: dict[str, Any]) -> None:
        if not self.progress:
            return
        line = {
            "event": "progress",
            "command": self.command,
            **event,
            "ts": clock.ms_to_rfc3339(clock.now_ms()),
        }
        sys.stderr.write(json.dumps(line, ensure_ascii=False) + "\n")
        sys.stderr.flush()

    def acquire_lock(self) -> None:
        if self.lock is None:
            self.lock = paths.StateLock(self.home, self.wait_lock)
            self.lock.acquire()


Handler = Callable[[Context, dict[str, Any]], Any]


@dataclass(frozen=True)
class Command:
    id: str
    handler: Handler
    writes: bool
    needs_init: bool
    cancellable: bool


REGISTRY: dict[str, Command] = {}


def command(
    command_id: str, *, writes: bool = False, needs_init: bool = True, cancellable: bool = False
) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        REGISTRY[command_id] = Command(command_id, fn, writes, needs_init, cancellable)
        return fn

    return deco


# Explicit channels that keep their meaning under an agent marker; any other requested
# channel (cli, app, test) is elevated to `skill` (02 §5.2, §10.3-4b).
_NOT_ELEVATED = frozenset({"skill", "mcp", "schedule"})


def effective_channel(requested: str, env: Mapping[str, str] | None = None) -> str:
    """Agent markers in the environment make the channel `skill` whatever --channel says,
    except an explicit skill/mcp/schedule. The real app spawns the core with a clean,
    allow-listed environment, so it never carries markers (10 §8.5)."""
    environ = os.environ if env is None else env
    if requested not in _NOT_ELEVATED and any(environ.get(m) for m in AGENT_ENV_MARKERS):
        return "skill"
    return requested


def is_owner_only(command_id: str, args: Mapping[str, Any]) -> bool:
    if command_id in OWNER_ONLY_COMMANDS:
        return True
    if command_id == "config.set":
        key = str(args.get("key") or "")
        return key in OWNER_ONLY_KEYS or key.startswith(OWNER_ONLY_KEY_PREFIXES)
    return False


def owner_only_refused(
    command_id: str,
    args: Mapping[str, Any],
    requested: str,
    effective: str,
    sandbox_valid: bool,
) -> bool:
    """02 §10.3-4b. Agent channels may not run owner-only commands.

    Sole exception: inside a valid sandbox, a `skill` channel that came only from marker
    elevation (requested cli/app/test) is allowed, so tests and coding agents can run the
    CLI. An explicit --channel skill|mcp is refused everywhere; outside a valid sandbox
    there is no exception at all.
    """
    if effective not in AGENT_CHANNELS or not is_owner_only(command_id, args):
        return False
    elevated = requested != effective
    return not (elevated and sandbox_valid)


def is_initialized(home: Path) -> bool:
    return store_db.db_path(home).is_file() and config_mod.config_path(home).is_file()


def open_db(ctx: Context) -> None:
    """Open the DB and apply pending migrations under the write lock (06 §7)."""
    path = store_db.db_path(ctx.home)
    try:
        conn = store_db.connect(path)
    except FileNotFoundError:
        raise NotFoundError(
            "E_NOT_INITIALIZED", "먼저 dayclose init 을 실행하세요.", {"home": str(ctx.home)}
        ) from None
    ctx.conn = conn
    if store_db.pending(conn):
        ctx.acquire_lock()
        store_db.migrate(conn, ctx.home)


def _setup_logging(ctx: Context) -> None:
    if not ctx.home.is_dir():
        return
    try:
        level = ctx.log_level
        dlog.setup(dlog.log_path(ctx.home, ctx.home_overridden, paths.user_home()), level)
    except OSError:
        pass  # logging must never break a command


def _meta_db_version(ctx: Context) -> int | None:
    if ctx.conn is not None:
        try:
            return store_db.user_version(ctx.conn)
        except sqlite3.Error:
            return None
    return store_db.read_user_version(store_db.db_path(ctx.home))


def _device_id(ctx: Context) -> str | None:
    if ctx.cfg is not None and ctx.cfg.device_id:
        return ctx.cfg.device_id
    try:
        cfg, _ = config_mod.load(ctx.home)
    except DayCloseError:
        return None
    return cfg.device_id or None


def _audit_summary(ctx: Context) -> str:
    """audit_log.channel holds the effective channel; the requested one goes in the summary
    when it differs (no DDL column for it)."""
    summary = ctx.audit.summary or ctx.command
    if ctx.requested_channel != ctx.channel:
        summary += f" requested_channel={ctx.requested_channel}"
    return summary


def _record_audit(ctx: Context, ok: bool, error_code: str | None) -> None:
    if ctx.conn is None or ctx.lock is None:
        return
    try:
        repo.insert_audit(
            ctx.conn,
            ts=clock.now_ms(),
            request_id=ctx.request_id,
            command=ctx.command,
            channel=ctx.channel,
            ok=ok,
            error_code=error_code,
            target_type=ctx.audit.target_type,
            target_ids=ctx.audit.target_ids,
            summary=_audit_summary(ctx),
        )
    except sqlite3.Error:
        dlog.get_logger().warning(
            "audit write failed", extra={"request_id": ctx.request_id, "command": ctx.command}
        )


def execute(command_id: str, args: dict[str, Any], options: Options) -> tuple[dict[str, Any], int]:
    """Run one command; returns (envelope, exit_code). Never raises for command errors."""
    started = clock.monotonic()
    home = paths.resolve_home(options.home)
    ctx = Context(
        command=command_id,
        home=home,
        home_overridden=paths.home_was_overridden(options.home),
        channel=options.channel,
        requested_channel=options.channel,
        wait_lock=options.wait_lock,
        progress=options.progress == "ndjson",
        log_level=options.log_level,
        request_id=envelope.new_request_id(),
    )
    data: Any = None
    error: DayCloseError | None = None
    restore_sigint: Any = None
    home_ok = False
    try:
        paths.set_active_home(home)
        paths.check_home_in_sandbox(home)
        home_ok = True
        paths.install_sandbox_guard()
        if options.channel not in CHANNELS:
            raise UsageError("알 수 없는 채널입니다.", {"allowed": list(CHANNELS)})
        ctx.channel = effective_channel(options.channel)
        cmd = REGISTRY.get(command_id)
        if cmd is None:
            raise UsageError("알 수 없는 명령입니다.", {"command": command_id})
        if ctx.channel == "schedule" and command_id not in SCHEDULE_ALLOWED:
            raise SafetyError(
                "E_PROTECTED",
                "예약 실행 채널에서는 이 명령을 쓸 수 없습니다.",
                {"reason": "channel_not_allowed"},
            )
        if owner_only_refused(
            command_id, args, options.channel, ctx.channel, paths.sandbox_status(home).valid
        ):
            raise SafetyError(
                "E_PROTECTED", "이 명령은 소유자만 실행할 수 있습니다.", {"reason": "owner_only"}
            )
        if cmd.needs_init:
            if not is_initialized(home):
                raise NotFoundError(
                    "E_NOT_INITIALIZED", "먼저 dayclose init 을 실행하세요.", {"home": str(home)}
                )
            ctx.cfg, cfg_warnings = config_mod.load(home)
            ctx.warnings.extend(cfg_warnings)
        _setup_logging(ctx)
        if not cmd.cancellable and threading.current_thread() is threading.main_thread():
            # Short commands finish their write instead of stopping halfway (10 §1.3).
            restore_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
        if cmd.needs_init:
            open_db(ctx)
        if cmd.writes and cmd.needs_init:
            ctx.acquire_lock()  # core.init takes the lock itself once the home exists
        data = cmd.handler(ctx, args)
        _record_audit(ctx, True, None)
    except DayCloseError as exc:
        error = exc
        _record_audit(ctx, False, exc.code)
    except KeyboardInterrupt:
        error = CancelledError("사용자가 취소했습니다.")
        _record_audit(ctx, False, error.code)
    except sqlite3.DatabaseError as exc:
        error = InternalError(
            "E_DB_CORRUPT",
            "DB 파일이 손상되었습니다. 백업에서 복원하세요.",
            {"reason": type(exc).__name__},
        )
    except Exception:
        error = InternalError(
            "E_INTERNAL", "예상치 못한 오류가 발생했습니다.", {"request_id": ctx.request_id}
        )
        dlog.get_logger().error(
            "unexpected exception",
            exc_info=True,
            extra={"request_id": ctx.request_id, "command": command_id, "channel": ctx.channel},
        )
        _record_audit(ctx, False, error.code)
    finally:
        if restore_sigint is not None:
            signal.signal(signal.SIGINT, restore_sigint)
    meta = envelope.Meta(
        request_id=ctx.request_id,
        core_version=__version__,
        # A home outside the sandbox is never touched, not even to fill `meta`.
        db_schema_version=_meta_db_version(ctx) if home_ok else None,
        device_id=_device_id(ctx) if home_ok else None,
        duration_ms=int((clock.monotonic() - started) * 1000),
    )
    if ctx.lock is not None:
        ctx.lock.release()
    if ctx.conn is not None:
        ctx.conn.close()
    dlog.get_logger().info(
        "command finished",
        extra={
            "request_id": ctx.request_id,
            "command": command_id,
            "channel": ctx.channel,
            "ok": error is None,
            "code": None if error is None else error.code,
            "duration_ms": meta.duration_ms,
        },
    )
    dlog.shutdown()
    paths.set_active_home(None)
    if error is None:
        return envelope.success(command_id, data, ctx.warnings, meta), 0
    return envelope.failure(command_id, error, ctx.warnings, meta), error.exit_code
