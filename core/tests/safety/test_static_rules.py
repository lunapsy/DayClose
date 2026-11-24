"""Static safety checks (11 §2.4, §4.1, §4.5 S7).

- test_no_mutation_outside_executor: no file-mutating call outside the allow-list. M1 has no
  executor, so user-file mutation must exist nowhere; only DayClose's own state writes in
  store/config/common.logging/common.paths are allowed (02 §6).
- test_import_boundaries: module import direction (02 §6).
- test_tests_do_not_reference_real_paths / test_conftest_guard_present.
"""

from __future__ import annotations

import ast
from pathlib import Path

from conftest import CORE_DIR, REPO_DIR, TESTS_DIR

SRC = CORE_DIR / "src" / "dayclose"

MUTATING_ATTRS = frozenset(
    {
        "rename",
        "replace",
        "remove",
        "unlink",
        "rmdir",
        "removedirs",
        "chmod",
        "lchmod",
        "chflags",
        "lchflags",
        "utime",
        "truncate",
        "ftruncate",
        "link",
        "symlink",
        "mkdir",
        "makedirs",
        "move",
        "rmtree",
        "copy",
        "copy2",
        "copyfile",
        "copytree",
        "copymode",
        "copystat",
        "write_text",
        "write_bytes",
        "touch",
        "setxattr",
        "removexattr",
        "write",
        "hardlink_to",
        "symlink_to",
    }
)
WRITE_FLAGS = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"})

# (file relative to src/dayclose, call attribute) -> reason. Each entry writes only inside
# DAYCLOSE_HOME (DayClose's own state), never a user file.
ALLOWED: dict[tuple[str, str], str] = {
    ("store/db.py", "mkdir"): "DAYCLOSE_HOME and backups/ directories",
    ("store/db.py", "os.chmod"): "0700 home, 0600 DB/WAL/SHM",
    ("store/db.py", "os.open"): "create the DB file / backup file with mode 0600",
    ("store/db.py", "unlink"): "prune DB backups beyond the newest 3 (06 §7)",
    ("config/__init__.py", "os.open"): "temporary config.toml for the atomic replace",
    ("config/__init__.py", "os.replace"): "atomic replace of config.toml",
    ("config/__init__.py", "os.unlink"): "remove our own temporary config file on failure",
    ("config/__init__.py", "os.chmod"): "config.toml 0600",
    ("common/logging.py", "mkdir"): "log directory",
    ("common/paths.py", "os.open"): "open_state_lock(): DAYCLOSE_HOME/state.lock",
    ("common/paths.py", "os.ftruncate"): "rewrite the holder pid in state.lock",
    ("common/paths.py", "os.write"): "write the holder pid into state.lock",
    ("api/core_cmds.py", "os.chmod"): "0600 on our own WAL/SHM after init",
}


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _open_writes(call: ast.Call) -> bool:
    mode = (
        call.args[1]
        if len(call.args) > 1
        else next((k.value for k in call.keywords if k.arg == "mode"), None)
    )
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(c in mode.value for c in "wax+")
    return True  # non-literal mode: treat as a write


def _os_open_writes(call: ast.Call) -> bool:
    names = {n.attr for n in ast.walk(call) if isinstance(n, ast.Attribute)}
    return bool(names & WRITE_FLAGS)


def _mutations(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "open" and _open_writes(node):
            out.append(("open", node.lineno))
        elif isinstance(f, ast.Attribute):
            if f.attr == "open" and isinstance(f.value, ast.Name) and f.value.id == "os":
                if _os_open_writes(node):
                    out.append(("os.open", node.lineno))
            elif f.attr == "open" and _open_writes(node):
                out.append(("open", node.lineno))
            elif f.attr in MUTATING_ATTRS:
                recv = f.value.id if isinstance(f.value, ast.Name) else None
                if recv in ("os", "shutil"):
                    out.append((f"{recv}.{f.attr}", node.lineno))
                elif f.attr == "write":
                    continue  # file objects come from open(), which is checked itself
                elif f.attr == "replace" and len(node.args) != 1:
                    continue  # str.replace(old, new); Path.replace(target) has one argument
                else:
                    out.append((f.attr, node.lineno))
    return out


def test_no_mutation_outside_executor() -> None:
    assert not (SRC / "executor").exists() or not _py_files(SRC / "executor")  # M1: none
    offenders = []
    for path in _py_files(SRC):
        rel = path.relative_to(SRC).as_posix()
        for name, line in _mutations(path):
            if (rel, name) not in ALLOWED:
                offenders.append(f"{rel}:{line} {name}")
    assert offenders == []


def test_allowlist_entries_are_used() -> None:
    used = {(p.relative_to(SRC).as_posix(), n) for p in _py_files(SRC) for n, _ in _mutations(p)}
    assert set(ALLOWED) <= used, sorted(set(ALLOWED) - used)


# --------------------------------------------------------------------------- imports

LAYER = {
    "common": 0,
    "": 0,
    "store": 1,
    "config": 1,
    "collect": 2,
    "intel": 2,
    "vault": 2,
    "policy": 2,
    "review": 2,
    "plan": 2,
    "ai": 2,
    "executor": 2,
    "api": 3,
    "cli": 4,
    "serve": 4,
    "mcp": 4,
    "__main__": 5,  # `python -m dayclose` entry point
}


def _module_of(path: Path) -> str:
    rel = path.relative_to(SRC).parts
    if rel == ("__main__.py",):
        return "__main__"
    return rel[0] if len(rel) > 1 else ""


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for n in names:
            parts = n.split(".")
            if parts[0] == "dayclose":
                top = parts[1] if len(parts) > 1 else ""
                if top in LAYER or top == "":
                    out.append((top if top in LAYER else "", node.lineno))
    return out


def test_import_boundaries() -> None:
    bad = []
    for path in _py_files(SRC):
        src_mod = _module_of(path)
        for dst, line in _imports(path):
            if dst == src_mod or dst == "":
                continue
            src_l, dst_l = LAYER[src_mod], LAYER[dst]
            same_layer_ok = src_l == 2 and dst_l == 2 and src_mod != "ai"
            if dst_l > src_l or (dst_l == src_l and not same_layer_ok):
                bad.append(f"{path.relative_to(SRC)}:{line} {src_mod} -> {dst}")
            if src_mod == "ai" and dst in ("executor",):
                bad.append(f"{path.relative_to(SRC)}:{line} ai -> executor")
    assert bad == []


def test_network_modules_only_in_ai_providers() -> None:
    banned = {"urllib.request", "http.client", "socket", "ssl"}
    bad = []
    for path in _py_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            if any(m in banned or m.startswith("urllib.request") for m in mods):
                bad.append(str(path.relative_to(SRC)))
    assert bad == []


def test_no_shell_true_and_subprocess_only_in_proc() -> None:
    bad = []
    for path in _py_files(SRC):
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                if "subprocess" in mods and rel != "common/proc.py":
                    bad.append(f"{rel}: imports subprocess")
            if isinstance(node, ast.keyword) and node.arg == "shell":
                if not (isinstance(node.value, ast.Constant) and node.value.value is False):
                    bad.append(f"{rel}: shell=")
    assert bad == []


# --------------------------------------------------------------------------- tests themselves

# (file under core/tests or scripts, literal) -> reason
PATH_LITERAL_ALLOWED: dict[tuple[str, str], str] = {
    ("tests/conftest.py", "~/"): "os.path.expanduser patch that maps ~ to the sandbox user",
    ("tests/contract/test_envelope_contract.py", "/Volumes/"): "asserts fixtures lack it",
    ("tests/unit/test_common.py", "~/Downloads"): "expected display_path",
    ("tests/integration/test_config_cli.py", "~/dev"): "config value sample (a string)",
    ("tests/integration/test_config_cli.py", "~/src"): "config value sample (a string)",
    ("tests/integration/test_config_cli.py", '["~/dev", "~/src"]'): "TOML literal sample",
    ("tests/integration/test_init.py", "~/Pictures/Screenshots\n"): "fake defaults output",
    ("tests/integration/test_init.py", "~/Downloads"): "expected display_path",
    ("tests/integration/test_init.py", "/Volumes/External/Shots"): "refused fake location",
    ("tests/integration/test_scan.py", "~/Downloads"): "expected display_path",
    ("tests/integration/test_doctor.py", "~/Downloads"): "expected display_path",
    ("tests/integration/test_doctor.py", "~/Desktop"): "expected display_path",
    ("tests/integration/test_doctor.py", "~/Gone"): "expected display_path",
    (
        "tests/unit/test_common.py",
        "~/Downloads/스크린샷 2026-11-24 오후 2.02.11.png 스캔 완료 /private/var/folders/x",
    ): "redaction sample text",
    ("tests/unit/test_common.py", "~/x/../y"): "normalize remapped to the sandbox user",
    ("tests/unit/test_config_and_store.py", '["~/dev", "~/src"]'): "TOML literal sample",
    ("tests/unit/test_config_and_store.py", "~/dev"): "TOML literal sample",
    ("tests/unit/test_config_and_store.py", "~/src"): "TOML literal sample",
    ("tests/safety/test_sandbox_validity.py", "/Volumes/h"): "refused sandbox location",
}


def _literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_tests_do_not_reference_real_paths() -> None:
    files = _py_files(TESTS_DIR) + sorted((REPO_DIR / "scripts").glob("*"))
    bad = []
    for path in files:
        if path.suffix not in (".py", ".sh", "") or path.is_dir():
            continue
        rel = (
            path.relative_to(CORE_DIR)
            if path.is_relative_to(CORE_DIR)
            else path.relative_to(REPO_DIR)
        ).as_posix()
        if rel == "tests/safety/test_static_rules.py":
            continue  # this file lists the allowed literals themselves
        literals = _literals(path) if path.suffix == ".py" else [path.read_text()]
        for lit in literals:
            if ("/Users/" in lit or lit.startswith("~/") or "/Volumes/" in lit) and (
                rel,
                lit,
            ) not in PATH_LITERAL_ALLOWED:
                bad.append(f"{rel}: {lit[:60]!r}")
        if rel != "tests/conftest.py" and "Path.home()" in path.read_text():
            bad.append(f"{rel}: Path.home()")
    assert bad == []


def test_conftest_guard_present() -> None:
    tree = ast.parse((TESTS_DIR / "conftest.py").read_text(encoding="utf-8"))
    autouse = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and any(
                    k.arg == "autouse"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value is True
                    for k in d.keywords
                ):
                    autouse.add(node.name)
    assert {
        "sandbox",
        "_audit_guard",
        "_no_network",
        "_guard_env",
        "_real_home_snapshot",
    } <= autouse
