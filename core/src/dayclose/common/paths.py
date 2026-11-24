"""Paths, sandbox guard, volume probe, iCloud/dataless signals (02 §6, §8, §10.4-10.6; 11 §2).

Everything here is read-only with respect to user files.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat as stat_mod
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from dayclose.common.errors import LockError, SafetyError, sandbox_violation

SF_DATALESS = 0x40000000

APP_SUPPORT_REL = "Library/Application Support/DayClose"
LOGS_REL = "Library/Logs/DayClose"
CACHES_REL = "Library/Caches/DayClose"
ICLOUD_DRIVE_REL = "Library/Mobile Documents/com~apple~CloudDocs"
MOBILE_DOCUMENTS_REL = "Library/Mobile Documents"
CLOUD_STORAGE_REL = "Library/CloudStorage"


# --------------------------------------------------------------------------- sandbox / home


def sandbox_root() -> Path | None:
    value = os.environ.get("DAYCLOSE_SANDBOX")
    if not value:
        return None
    return Path(os.path.realpath(value))


def user_home() -> Path:
    """The home that default roots and `~` resolve against.

    Sandbox mode remaps it to `$DAYCLOSE_SANDBOX/user` (11 §2.3, third layer) so that
    nothing in sandbox mode can resolve to the real home.
    """
    raw = os.environ.get("DAYCLOSE_SANDBOX")
    if raw:
        # As given (not realpath'd), so paths typed by the user keep matching it.
        return Path(os.path.abspath(raw)) / "user"
    return Path.home()


def resolve_home(cli_home: str | None) -> Path:
    """DAYCLOSE_HOME resolution: --home > env > default (02 §8)."""
    value = cli_home or os.environ.get("DAYCLOSE_HOME")
    if value:
        return Path(os.path.abspath(os.path.expanduser(value)))
    return user_home() / APP_SUPPORT_REL


def home_was_overridden(cli_home: str | None) -> bool:
    return bool(cli_home or os.environ.get("DAYCLOSE_HOME"))


def is_under(path: str | os.PathLike[str], base: str | os.PathLike[str]) -> bool:
    p = os.fspath(path)
    b = os.fspath(base).rstrip("/") or "/"
    return p == b or p.startswith(b + "/") or b == "/"


SANDBOX_MARKER = ".dayclose-sandbox"
_CS_DARWIN_USER_TEMP_DIR = 65537  # <unistd.h>; not in os.confstr_names


def _user_temp_dirs() -> list[str]:
    out = ["/private/tmp"]
    try:
        value = os.confstr(_CS_DARWIN_USER_TEMP_DIR)
    except (ValueError, OSError):
        value = None
    if value:
        out.append(os.path.realpath(value))
    return out


def real_home() -> str:
    """The account's home from the password database (not $HOME, which tests repoint)."""
    import pwd

    return os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)


def _sandbox_refusal(reason: str) -> SafetyError:
    return SafetyError(
        "E_SANDBOX_VIOLATION",
        "샌드박스 설정이 올바르지 않아 시작하지 않습니다.",
        {"reason": reason},
    )


def validate_sandbox(home: Path) -> None:
    """Sandbox validity (02 §10.4). Raises E_SANDBOX_VIOLATION before anything is touched.

    No-op when DAYCLOSE_SANDBOX is unset.
    """
    sb = sandbox_root()
    if sb is None:
        return
    sb_s = str(sb)
    if not any(is_under(sb_s, t) and sb_s != t for t in _user_temp_dirs()):
        raise _sandbox_refusal("not_under_temp_dir")
    rh = real_home()
    protected = [rh, "/Volumes", os.path.join(rh, APP_SUPPORT_REL)]
    for p in protected:
        if is_under(p, sb_s):  # equal to, or an ancestor of, a protected location
            raise _sandbox_refusal("contains_protected_location")
    if not os.path.isfile(os.path.join(sb_s, SANDBOX_MARKER)):
        raise _sandbox_refusal("marker_missing")
    if not is_under(os.path.realpath(home), sb_s):
        raise _sandbox_refusal("home_outside_sandbox")


def check_home_in_sandbox(home: Path) -> None:
    validate_sandbox(home)


def check_path_in_sandbox(path: str) -> None:
    sb = sandbox_root()
    if sb is not None and not is_under(os.path.realpath(path), sb):
        raise sandbox_violation(path, "path_argument")


def normalize_user_path(value: str) -> str:
    """CLI path argument: `~` expansion then abspath, symlinks untouched (10 §1.1)."""
    if value == "~" or value.startswith("~/"):
        value = str(user_home()) + value[1:]
    return os.path.abspath(value)


def display_path(path: str | None) -> str | None:
    """Home-abbreviated path for display fields only (02 §5.1)."""
    if path is None:
        return None
    raw = str(user_home())
    for home in dict.fromkeys((raw, os.path.realpath(raw))):
        if path == home:
            return "~"
        if path.startswith(home + "/"):
            return "~" + path[len(home) :]
    return path


# --------------------------------------------------------------------------- state lock (02 §7)


def open_state_lock(home: Path) -> int:
    """Create/open `DAYCLOSE_HOME/state.lock` (mode 0600). The only opener of that file."""
    return os.open(home / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)


LOCK_NAME = "state.lock"


class StateLock:
    def __init__(self, home: Path, wait_seconds: float) -> None:
        self.path = home / LOCK_NAME
        self.wait_seconds = max(0.0, wait_seconds)
        self._fd: int | None = None

    def acquire(self) -> None:
        fd = open_state_lock(self.path.parent)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    holder = _read_pid(fd)
                    os.close(fd)
                    details: dict[str, object] = {"wait_seconds": self.wait_seconds}
                    if holder is not None:
                        details["holder_pid"] = holder
                    raise LockError("다른 DayClose 작업이 진행 중입니다.", details) from None
                time.sleep(0.05)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> StateLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def _read_pid(fd: int) -> int | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 32).decode(errors="ignore").strip()
        return int(raw) if raw.isdigit() else None
    except OSError:
        return None


# --------------------------------------------------------------------------- system paths


_TOOL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "osascript": ("/usr/bin/osascript",),
    "git": ("/usr/bin/git",),
    "mdls": ("/usr/bin/mdls",),
    "defaults": ("/usr/bin/defaults",),
    "brew": ("/opt/homebrew/bin/brew",),
    "gitleaks": ("/opt/homebrew/bin/gitleaks", "/usr/local/bin/gitleaks"),
}
TOOLS: frozenset[str] = frozenset({*_TOOL_CANDIDATES, "dayclose-native"})
_HOMEBREW_PREFIXES = ("/opt/homebrew/", "/usr/local/")


def _location(name: str) -> str | None:
    sb = sandbox_root()
    home = user_home()
    real = {
        "applications": "/Applications",
        "user_applications": str(home / "Applications"),
        "launch_agents_user": str(home / "Library/LaunchAgents"),
        "launch_agents_global": "/Library/LaunchAgents",
        "launch_daemons": "/Library/LaunchDaemons",
        "user_trash": str(home / ".Trash"),
        "volumes_root": "/Volumes",
    }
    if name not in real:
        return None
    if sb is None:
        return real[name]
    remap = {
        "applications": sb / "sys/Applications",
        "user_applications": home / "Applications",
        "launch_agents_user": home / "Library/LaunchAgents",
        "launch_agents_global": sb / "sys/Library/LaunchAgents",
        "launch_daemons": sb / "sys/Library/LaunchDaemons",
        "user_trash": home / ".Trash",
        "volumes_root": sb / "vol",
    }
    return str(remap[name])


def _resolve_tool(tool: str) -> str | None:
    sb = sandbox_root()
    if sb is not None:
        # Decision (M1): in sandbox mode only the sandbox's fake tools run. Falling back
        # to the real /usr/bin/defaults would read the real user's preferences.
        fake = sb / "bin" / tool
        return str(fake) if fake.is_file() and os.access(fake, os.X_OK) else None
    if tool == "dayclose-native":
        native = os.environ.get("DAYCLOSE_NATIVE")
        return native if native and os.path.isabs(native) and os.path.isfile(native) else None
    for cand in _TOOL_CANDIDATES.get(tool, ()):
        if not os.path.isfile(cand):
            continue
        if cand.startswith(_HOMEBREW_PREFIXES):
            real = os.path.realpath(cand)
            if not real.startswith(_HOMEBREW_PREFIXES):
                continue
        return cand
    return None


def system_path(name: str) -> str | None:
    """Absolute path of an allow-listed tool or a fixed system location (02 §6, 11 §2.3).

    Tool names and location names do not overlap. No PATH lookup ever happens.
    """
    if name in TOOLS:
        return _resolve_tool(name)
    return _location(name)


# --------------------------------------------------------------------------- probe


ProbeStat = Callable[[str], None]


def _default_probe_stat(path: str) -> None:
    os.stat(path)
    with os.scandir(path) as it:
        next(it, None)


# Replaceable in in-process tests (EPERM injection, never-returning volume, 11 §6.1).
probe_stat: ProbeStat = _default_probe_stat


def classify_oserror(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) == errno.ENOENT:
        return "missing"
    if isinstance(exc, NotADirectoryError):
        return "not_dir"
    if getattr(exc, "errno", None) == errno.EPERM:
        return "tcc_denied"
    if getattr(exc, "errno", None) == errno.EACCES:
        return "permission_denied"
    return "missing"


def probe(path: str, timeout: float) -> str:
    """One stat+scandir in a daemon thread (02 §10.5).

    Returns `ok | missing | not_dir | tcc_denied | permission_denied | timeout`. A hung
    thread is abandoned as a daemon thread.
    """
    result: dict[str, str] = {}
    fn = probe_stat

    def run() -> None:
        try:
            fn(path)
            result["access"] = "ok"
        except OSError as exc:
            result["access"] = classify_oserror(exc)

    t = threading.Thread(target=run, name="dayclose-probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return "timeout"
    return result.get("access", "missing")


# --------------------------------------------------------------------------- iCloud / dataless


def legacy_placeholder_name(name: str) -> str | None:
    """`.<name>.icloud` -> `<name>`, else None."""
    if name.startswith(".") and name.endswith(".icloud"):
        return name[1 : -len(".icloud")] or None
    return None


def is_dataless(name: str, st_flags: int) -> bool:
    return bool(st_flags & SF_DATALESS) or legacy_placeholder_name(name) is not None


def live_icloud_signal(path: str, root_kind: str | None = None) -> bool:
    """S1/S2 live signals (04 §1): realpath under Mobile Documents/CloudStorage, or a
    desktop/documents root whose CloudDocs counterpart exists. lstat/realpath only."""
    home = str(user_home())
    real = os.path.realpath(path)
    for rel in (MOBILE_DOCUMENTS_REL, CLOUD_STORAGE_REL):
        if is_under(real, os.path.realpath(os.path.join(home, rel))):
            return True
    if root_kind in ("desktop", "documents"):
        sub = "Desktop" if root_kind == "desktop" else "Documents"
        try:
            os.lstat(os.path.join(home, ICLOUD_DRIVE_REL, sub))
            return True
        except OSError:
            return False
    return False


def is_icloud_synced(path: str, kind: str) -> bool | None:
    """`detect(root)` of 04 §1. None = undetermined (V17 method not fixed yet)."""
    if kind == "icloud_drive":
        return True
    home = str(user_home())
    drive = os.path.realpath(os.path.join(home, ICLOUD_DRIVE_REL))
    if is_under(os.path.realpath(path), drive):
        return True
    if kind in ("desktop", "documents") and path in (
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
    ):
        # 09 §12 V17 has not fixed a detection method yet -> undetermined.
        return None
    return False


def effective_icloud(path: str, kind: str, mode: str) -> tuple[int, str]:
    """(icloud_synced, icloud_synced_source) per the 04 §1 pseudo-code."""
    live = live_icloud_signal(path, kind)
    if mode == "yes":
        return 1, "user"
    if mode == "no":
        return (1, "detected") if live else (0, "user")
    if live:
        return 1, "detected"
    sig = is_icloud_synced(path, kind)
    if sig is True:
        return 1, "detected"
    if sig is False:
        return 0, "detected"
    if kind in ("desktop", "documents"):
        return 1, "assumed"
    return 0, "detected"


# --------------------------------------------------------------------------- sandbox guard

# event -> ((path arg index, dir_fd arg index or None), ...) for paths that get written.
_WRITE_EVENTS_PATH_ARGS: dict[str, tuple[tuple[int, int | None], ...]] = {
    "os.rename": ((0, 2), (1, 3)),
    "os.remove": ((0, 1),),
    "os.rmdir": ((0, 1),),
    "os.mkdir": ((0, 2),),
    "os.chmod": ((0, 2),),
    "os.chflags": ((0, None),),
    "os.lchflags": ((0, None),),
    "os.utime": ((0, 3),),
    "os.truncate": ((0, None),),
    "os.link": ((0, 2), (1, 3)),
    "os.symlink": ((1, 2),),  # the link target (arg 0) is data, not a written path
    "os.setxattr": ((0, None),),
    "os.removexattr": ((0, None),),
    "shutil.rmtree": ((0, 1),),
    "shutil.copyfile": ((1, None),),
    "shutil.copytree": ((1, None),),
    "shutil.move": ((0, None), (1, None)),
    "shutil.copymode": ((1, None),),
    "shutil.copystat": ((1, None),),
    "sqlite3.connect": ((0, None),),
}
_READ_EVENTS_PATH_ARGS: dict[str, tuple[int, ...]] = {
    "os.listdir": (0,),
    "os.scandir": (0,),
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class _GuardState:
    installed = False
    extra_executables: set[str] = set()
    extra_read_roots: list[str] = []
    read_cache: list[str] | None = None


def _read_allowlist() -> list[str]:
    if _GuardState.read_cache is not None:
        return _GuardState.read_cache
    roots = {
        os.path.realpath(sys.prefix),
        os.path.realpath(sys.base_prefix),
        os.path.realpath(sys.exec_prefix),
        "/usr",
        "/System",
        "/Library/Frameworks",
        "/dev/null",
        "/dev/tty",
        "/dev/urandom",
        *_user_temp_dirs(),  # never tempfile.gettempdir(): it probes by writing a file
    }
    # The installed package itself (core/src in an editable install) and the repository's
    # contracts/ directory. core/tests is added by the test harness (failure tracebacks).
    pkg = Path(__file__).resolve().parents[2]
    roots.add(str(pkg))
    repo_contracts = pkg.parent.parent / "contracts"
    roots.add(str(repo_contracts))
    roots.update(_GuardState.extra_read_roots)
    _GuardState.read_cache = sorted(roots)
    return _GuardState.read_cache


def _exec_allowlist() -> set[str]:
    allowed = {c for cands in _TOOL_CANDIDATES.values() for c in cands}
    sb = sandbox_root()
    if sb is not None:
        bin_dir = sb / "bin"
        allowed.add(str(bin_dir))
    native = os.environ.get("DAYCLOSE_NATIVE")
    if native:
        allowed.add(native)
    return allowed | _GuardState.extra_executables


def _as_path(value: Any) -> str | None:
    if isinstance(value, (str, bytes, os.PathLike)):
        p = os.fsdecode(os.fspath(value))
        return p
    return None


def _guard_hook(event: str, args: tuple[Any, ...]) -> None:
    sb_env = os.environ.get("DAYCLOSE_SANDBOX")
    if not sb_env:
        return
    if event == "open":
        target = _as_path(args[0]) if args else None
        if target is None:
            return
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        )
        _check(target, sb_env, writing, event)
        return
    spec = _WRITE_EVENTS_PATH_ARGS.get(event)
    if spec is not None:
        for i, fd_i in spec:
            if i >= len(args):
                continue
            target = _as_path(args[i])
            if target is None or target == ":memory:" or target.startswith("file:"):
                continue
            dir_fd = args[fd_i] if fd_i is not None and fd_i < len(args) else None
            _check(_with_dir_fd(target, dir_fd), sb_env, True, event)
        return
    idx = _READ_EVENTS_PATH_ARGS.get(event)
    if idx is not None:
        arg = args[0] if args else None
        if isinstance(arg, int):
            return  # fd-based listing of a directory that was already opened (and checked)
        target = _as_path(arg)
        _check(target if target is not None else ".", sb_env, False, event)
        return
    if event == "subprocess.Popen":
        exe = _as_path(args[0]) if args else None
        argv = args[1] if len(args) > 1 else None
        if exe is None and isinstance(argv, (list, tuple)) and argv:
            exe = _as_path(argv[0])
        if exe is None:
            raise sandbox_violation("", event)
        real = os.path.realpath(exe) if os.path.isabs(exe) else exe
        allowed = _exec_allowlist()
        ok = (
            exe in allowed
            or real in allowed
            or any(os.path.isabs(exe) and is_under(exe, a) and os.path.isdir(a) for a in allowed)
        )
        if not ok:
            raise sandbox_violation(exe, event)


def _with_dir_fd(target: str, dir_fd: Any) -> str:
    """Resolve a path given relative to an open directory fd (shutil.rmtree uses these)."""
    if isinstance(dir_fd, int) and not os.path.isabs(target):
        try:
            base = fcntl.fcntl(dir_fd, fcntl.F_GETPATH, bytes(1024))
        except OSError:
            return target
        return os.path.join(os.fsdecode(base.rstrip(b"\0")), target)
    return target


def _check(target: str, sb_env: str, writing: bool, event: str) -> None:
    real = os.path.realpath(target)
    sb = os.path.realpath(sb_env)
    if is_under(real, sb):
        return
    if writing:
        if real == "/dev/null":
            return
        raise sandbox_violation(target, event)
    for allowed in _read_allowlist():
        if is_under(real, allowed):
            return
    raise sandbox_violation(target, event)


def install_sandbox_guard() -> bool:
    """Install the audit-hook guard (02 §10.4, 11 §2.2). Idempotent; returns True if active.

    The hook stays installed for the process lifetime (audit hooks cannot be removed) and
    re-reads DAYCLOSE_SANDBOX on every event, so it is inert when the variable is unset.
    """
    if not os.environ.get("DAYCLOSE_SANDBOX"):
        return False
    # Writing .pyc files next to the source would be a write outside the sandbox.
    sys.dont_write_bytecode = True
    if not _GuardState.installed:
        sys.addaudithook(_guard_hook)
        _GuardState.installed = True
    return True


def allow_extra_for_tests(
    *, executables: list[str] | None = None, read_roots: list[str] | None = None
) -> None:
    """Test-process-only additions (the test interpreter, the tests directory)."""
    _GuardState.extra_executables.update(executables or [])
    for r in read_roots or []:
        if r not in _GuardState.extra_read_roots:
            _GuardState.extra_read_roots.append(r)
    _GuardState.read_cache = None


def mode_string(path: str) -> str | None:
    try:
        return f"{stat_mod.S_IMODE(os.stat(path).st_mode):04o}"
    except OSError:
        return None
