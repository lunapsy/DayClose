"""SQLite connection, PRAGMAs and the forward-only migration runner (06 §1, §7)."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from dayclose.common import clock
from dayclose.common.errors import InternalError

DB_NAME = "dayclose.db"
BACKUP_KEEP = 3
_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def migrations() -> list[Migration]:
    out: list[Migration] = []
    for entry in resources.files("dayclose.store.migrations").iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            out.append(Migration(int(m.group(1)), m.group(2), entry.read_text(encoding="utf-8")))
    out.sort(key=lambda mg: mg.version)
    for i, mg in enumerate(out, start=1):
        if mg.version != i:
            raise RuntimeError(f"migration numbering gap at {mg.version}")
    return out


def latest_version() -> int:
    return len(migrations())


def db_path(home: Path) -> Path:
    return home / DB_NAME


def ensure_home(home: Path) -> bool:
    """Create DAYCLOSE_HOME with mode 0700. Returns True if it was created now."""
    created = not home.exists()
    old = os.umask(0o077)
    try:
        home.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(old)
    os.chmod(home, 0o700)
    return created


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA trusted_schema=OFF")
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    if mode is None or str(mode[0]).lower() != "wal":
        raise InternalError("E_INTERNAL", "DB 를 WAL 모드로 열 수 없습니다.")
    conn.execute("PRAGMA synchronous=NORMAL")


def _map_db_error(exc: sqlite3.DatabaseError) -> InternalError:
    return InternalError(
        "E_DB_CORRUPT", "DB 파일이 손상되었습니다. 백업에서 복원하세요.", {"reason": "sqlite_error"}
    )


def connect(path: Path, *, create: bool = False) -> sqlite3.Connection:
    """Open the DB in autocommit mode (explicit BEGIN where needed) with 06 §1 PRAGMAs."""
    new_file = not path.exists()
    if new_file and not create:
        raise FileNotFoundError(str(path))
    if new_file:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    try:
        conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        if new_file:
            # Must be set before the first table is created (06 §8).
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        _apply_pragmas(conn)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as exc:
        raise _map_db_error(exc) from None
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            os.chmod(p, 0o600)
    return conn


def user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def read_user_version(path: Path) -> int | None:
    """Read-only peek used by `core.version` (never migrates, never creates)."""
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
        try:
            return user_version(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None


def _backup(conn: sqlite3.Connection, home: Path, target_version: int) -> Path:
    backups = home / "backups"
    old = os.umask(0o077)
    try:
        backups.mkdir(exist_ok=True)
    finally:
        os.umask(old)
    stamp = clock.now().astimezone().strftime("%Y%m%d-%H%M%S")
    dest = backups / f"dayclose-{stamp}-pre-v{target_version}.db"
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    existing = sorted(backups.glob("dayclose-*-pre-v*.db"), key=lambda p: p.stat().st_mtime)
    for stale in existing[:-BACKUP_KEEP]:
        stale.unlink()
    return dest


def pending(conn: sqlite3.Connection) -> list[Migration]:
    """Validate applied migrations and return the ones still to apply (06 §7)."""
    known = migrations()
    current = user_version(conn)
    if current > len(known):
        raise InternalError(
            "E_DB_MIGRATION",
            "DB 가 이 core 보다 새 버전입니다. core 를 업데이트하세요.",
            {"reason": "db_newer_than_core", "db_version": current, "supported": len(known)},
        )
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    applied: dict[int, str] = {}
    if has_table:
        applied = {
            int(v): str(c)
            for v, c in conn.execute("SELECT version, checksum FROM schema_migrations")
        }
    for mg in known:
        if mg.version in applied and applied[mg.version] != mg.checksum:
            raise InternalError(
                "E_DB_MIGRATION",
                "적용된 마이그레이션 파일이 변경되었습니다.",
                {"reason": "checksum_mismatch", "version": mg.version},
            )
    return [mg for mg in known if mg.version not in applied]


def migrate(conn: sqlite3.Connection, home: Path) -> int | None:
    """Apply pending migrations, each in its own BEGIN IMMEDIATE transaction.

    Returns the version migrated from (None if nothing was applied).
    """
    todo = pending(conn)
    if not todo:
        return None
    start = user_version(conn)
    backup_path: Path | None = None
    if start >= 1:
        backup_path = _backup(conn, home, todo[0].version)
    for mg in todo:
        now = clock.now_ms()
        script = (
            "BEGIN IMMEDIATE;\n"
            + mg.sql
            + "\n;INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES ("
            + f"{mg.version}, '{mg.name}', '{mg.checksum}', {now});\n"
            + f"PRAGMA user_version={mg.version};\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            details: dict[str, object] = {"reason": "apply_failed", "version": mg.version}
            if backup_path is not None:
                details["backup_path"] = str(backup_path)
            raise InternalError(
                "E_DB_MIGRATION", "마이그레이션에 실패했습니다. 백업에서 복원하세요.", details
            ) from None
    return start


def quick_check(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None and row[0] == "ok"
