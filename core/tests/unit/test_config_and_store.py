"""config load/validate/save (02 §9) and the migration runner (06 §7)."""

from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from conftest import TESTS_DIR, Sandbox

from dayclose import config
from dayclose.common import errors
from dayclose.store import db

# --------------------------------------------------------------------------- config


def test_parse_value_toml_literals() -> None:
    assert config.parse_value("true") is True
    assert config.parse_value("30") == 30
    assert config.parse_value('"21:00"') == "21:00"
    assert config.parse_value('["~/dev", "~/src"]') == ["~/dev", "~/src"]
    assert config.parse_value("21:00") == "21:00"  # not a TOML literal -> string


def test_validate_types_and_choices() -> None:
    config.validate("scan.settle_seconds", 10)
    config.validate("policy.learn_consistency", 1)
    for key, value in (
        ("scan.settle_seconds", "10"),
        ("scan.settle_seconds", True),
        ("review.carryover", 1),
        ("scan.exclude_globs", [1]),
        ("core.log_level", "verbose"),
    ):
        with pytest.raises(errors.EnvironmentError_) as exc:
            config.validate(key, value)
        assert exc.value.code == "E_CONFIG_INVALID" and exc.value.details["key"] == key
    with pytest.raises(errors.UsageError) as uexc:
        config.known_key("scan.nope")
    assert "scan.settle_seconds" in uexc.value.details["known_prefix"]


def test_load_save_roundtrip_and_unknown_key(sandbox: Sandbox) -> None:
    sandbox.home.mkdir(exist_ok=True)
    config.save(sandbox.home, {"device_id": "dev_1", "scan.settle_seconds": 5})
    path = sandbox.home / "config.toml"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    cfg, warns = config.load(sandbox.home)
    assert cfg.get("scan.settle_seconds") == 5 and cfg.source("scan.settle_seconds") == "file"
    assert cfg.get("review.day_boundary") == "04:00" and warns == []
    path.write_text(path.read_text() + "\n[mystery]\nx = 1\n")
    cfg, warns = config.load(sandbox.home)
    assert [(w.code, w.details) for w in warns] == [("W_CONFIG_UNKNOWN_KEY", {"key": "mystery.x"})]
    path.write_text('[scan]\nsettle_seconds = "soon"\n')
    with pytest.raises(errors.EnvironmentError_):
        config.load(sandbox.home)
    path.write_text("not = = toml")
    with pytest.raises(errors.EnvironmentError_) as exc:
        config.load(sandbox.home)
    assert exc.value.details["reason"] == "toml_parse"


# --------------------------------------------------------------------------- migrations


def _fresh(sandbox: Sandbox) -> sqlite3.Connection:
    db.ensure_home(sandbox.home)
    conn = db.connect(db.db_path(sandbox.home), create=True)
    db.migrate(conn, sandbox.home)
    return conn


def test_fresh_migration(sandbox: Sandbox) -> None:
    conn = _fresh(sandbox)
    assert db.user_version(conn) == db.latest_version() == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "app_meta",
        "schema_migrations",
        "scan_roots",
        "scan_runs",
        "file_entries",
        "file_events",
        "audit_log",
    } <= tables
    (version, name, checksum) = conn.execute(
        "SELECT version, name, checksum FROM schema_migrations"
    ).fetchone()
    assert (version, name) == (1, "core") and checksum == db.migrations()[0].checksum
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL
    with pytest.raises(sqlite3.IntegrityError):  # STRICT + CHECK enums
        conn.execute("INSERT INTO scan_roots(path, kind, created_at) VALUES ('/x', 'nas', 1)")
    assert db.migrate(conn, sandbox.home) is None  # idempotent


def _sql_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        code = re.sub(r"\s*--.*$", "", line).rstrip()
        if code.strip():
            out.append(code)
    return out


def test_migration_file_matches_spec_ddl() -> None:
    """0001_core.sql has the SQL of 06 §5.1 (comments may differ; the SQL may not)."""
    spec = (TESTS_DIR.parent.parent / "docs" / "06-DATA-MODEL.md").read_text()
    start = spec.index("```sql", spec.index("### 5.1 `0001_core.sql`")) + len("```sql\n")
    block = spec[start : spec.index("```", start)]
    assert _sql_lines(db.migrations()[0].sql) == _sql_lines(block)


def test_checksum_mismatch_is_rejected(sandbox: Sandbox) -> None:
    conn = _fresh(sandbox)
    conn.execute("UPDATE schema_migrations SET checksum='0' WHERE version=1")
    with pytest.raises(errors.InternalError) as exc:
        db.pending(conn)
    assert exc.value.code == "E_DB_MIGRATION"
    assert exc.value.details["reason"] == "checksum_mismatch"


def test_db_newer_than_core_is_rejected(sandbox: Sandbox) -> None:
    conn = _fresh(sandbox)
    conn.execute("PRAGMA user_version=99")
    with pytest.raises(errors.InternalError) as exc:
        db.pending(conn)
    assert exc.value.details["reason"] == "db_newer_than_core"


def test_backup_before_migrating_existing_db(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fresh(sandbox)
    real = db.migrations()

    def with_extra() -> list[db.Migration]:
        return [*real, db.Migration(2, "extra", "CREATE TABLE extra(x INTEGER) STRICT;")]

    monkeypatch.setattr(db, "migrations", with_extra)
    assert db.migrate(conn, sandbox.home) == 1
    assert db.user_version(conn) == 2
    backups = sorted((sandbox.home / "backups").glob("dayclose-*-pre-v2.db"))
    assert len(backups) == 1 and oct(backups[0].stat().st_mode & 0o777) == "0o600"
    old = sqlite3.connect(backups[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 1
    old.close()


def test_failed_migration_rolls_back(sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _fresh(sandbox)
    real = db.migrations()
    broken = db.Migration(2, "broken", "CREATE TABLE ok_one(x INTEGER) STRICT;\nSELEC nope;")
    monkeypatch.setattr(db, "migrations", lambda: [*real, broken])
    with pytest.raises(errors.InternalError) as exc:
        db.migrate(conn, sandbox.home)
    assert exc.value.code == "E_DB_MIGRATION" and "backup_path" in exc.value.details
    assert db.user_version(conn) == 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='ok_one'").fetchone() is None


@pytest.mark.parametrize("fixture", sorted((TESTS_DIR / "fixtures" / "db").glob("v*.db")))
def test_fixture_db_upgrades_to_latest(sandbox: Sandbox, fixture: Path) -> None:
    """Every committed fixture DB (core/tests/fixtures/db/v<N>.db) migrates to latest."""
    sandbox.home.mkdir(exist_ok=True)
    target = sandbox.home / "dayclose.db"
    shutil.copyfile(fixture, target)
    conn = db.connect(target)
    db.migrate(conn, sandbox.home)
    assert db.user_version(conn) == db.latest_version()
    assert db.quick_check(conn)
    assert conn.execute("SELECT count(*) FROM scan_roots").fetchone()[0] >= 1


def test_fixture_dbs_exist() -> None:
    assert (TESTS_DIR / "fixtures" / "db" / "v1.db").is_file()
