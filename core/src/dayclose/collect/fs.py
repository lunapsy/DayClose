"""File-system collector: traversal + snapshot diff (04 §1-§2, §14). Read-only on user files.

Pipeline: `traverse()` per root (lstat/scandir only) -> `diff()` once over all roots (so
cross-root moves are seen) -> the store applies the resulting `Changes`.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat as stat_mod
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from dayclose.common import paths
from dayclose.store.entries import Changes, Obs, Prev

PACKAGE_EXTS = frozenset(
    {
        "app",
        "bundle",
        "framework",
        "plugin",
        "kext",
        "photoslibrary",
        "musiclibrary",
        "tvlibrary",
        "fcpbundle",
        "logicx",
        "band",
        "pages",
        "numbers",
        "key",
        "rtfd",
        "xcarchive",
        "playground",
        "scriptd",
        "sparsebundle",
        "pkg",
    }
)
BUILTIN_EXCLUDED_NAMES = frozenset(
    {
        ".Trash",
        ".Trashes",
        ".DocumentRevisions-V100",
        ".Spotlight-V100",
        ".fseventsd",
        ".TemporaryItems",
        ".DS_Store",
        "Icon\r",
    }
)
PACKAGE_SIZE_MAX_ENTRIES = 20_000
PACKAGE_SIZE_MAX_SECONDS = 2.0
DIR_FANOUT_LIMIT = 50_000
CROSS_DEVICE_MIN_SIZE = 1024 * 1024
HASH_BUFFER = 1024 * 1024

# st_flags injection point for tests (11 §3.9): (path, st_flags) -> st_flags.
FlagsHook = Callable[[str, int], int]
flags_hook: FlagsHook | None = None


# --------------------------------------------------------------------------- globs


def _glob_to_regex(pattern: str) -> str:
    """`**` = zero or more directories, `*`/`?` never cross `/` (02 §9, 04 §2.2)."""
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


@dataclass(frozen=True)
class ExcludeRules:
    full: tuple[re.Pattern[str], ...]
    interior: tuple[re.Pattern[str], ...]

    @classmethod
    def compile(cls, globs: Iterable[str]) -> ExcludeRules:
        full: list[re.Pattern[str]] = []
        interior: list[re.Pattern[str]] = []
        for g in globs:
            g = g.strip()
            if not g:
                continue
            full.append(re.compile(_glob_to_regex(g) + r"\Z", re.DOTALL))
            if g.endswith("/**") and len(g) > 3:
                interior.append(re.compile(_glob_to_regex(g[:-3]) + r"\Z", re.DOTALL))
        return cls(tuple(full), tuple(interior))

    def classify(self, rel: str, is_dir: bool) -> str:
        """`keep` | `exclude` (no entry, no descent) | `no_descend` (entry, interior skipped)."""
        if is_dir and any(p.match(rel) for p in self.interior):
            return "no_descend"
        if any(p.match(rel) for p in self.full):
            return "exclude"
        return "keep"


# --------------------------------------------------------------------------- data


@dataclass
class RootSpec:
    id: int
    path: str
    kind: str
    max_depth: int | None


@dataclass
class Traversal:
    root_id: int
    status: str = "ok"  # ok | partial | unavailable | tcc_denied
    access: str = "ok"
    obs: list[Obs] = field(default_factory=list)
    safe_prefixes: list[str] = field(default_factory=list)
    truncated: bool = False
    entries_seen: int = 0
    permission_skipped: int = 0
    tcc_skipped: int = 0
    dataless_files: int = 0
    dataless_dirs: int = 0
    truncated_sizes: int = 0
    partial_dirs: int = 0

    @property
    def traversed(self) -> bool:
        return self.status in ("ok", "partial")


@dataclass
class ScanSettings:
    excludes: ExcludeRules
    package_dirs_as_files: bool
    max_entries_per_root: int
    hash_max_bytes: int
    builtin_excluded_paths: frozenset[str]
    # (st_dev, st_ino) of DAYCLOSE_HOME / caches / logs: matched by identity, so a different
    # spelling of the same directory (/var vs /private/var, a symlinked root) is still skipped.
    builtin_excluded_ids: frozenset[tuple[int, int]] = frozenset()


Progress = Callable[[int, int], None]  # (root_id, done)


# --------------------------------------------------------------------------- traversal


def _ext(name: str) -> str | None:
    if name.startswith(".") and name.count(".") == 1:
        return None
    _, dot, ext = name.rpartition(".")
    if not dot or not ext or not _:
        return None
    return ext.lower()


def _birthtime_ns(st: os.stat_result) -> int | None:
    bt = getattr(st, "st_birthtime", None)
    if bt is None:
        return None
    return int(round(bt * 1_000_000_000))


def _obs(
    root_id: int, path: str, name: str, kind: str, st: os.stat_result, flags: int, size: int
) -> Obs:
    return Obs(
        root_id=root_id,
        path=path,
        name=name,
        ext=_ext(name),
        kind=kind,
        size=size,
        mtime_ns=st.st_mtime_ns,
        ctime_ns=st.st_ctime_ns,
        birthtime_ns=_birthtime_ns(st),
        dev=st.st_dev,
        inode=st.st_ino,
        mode=st.st_mode,
        flags=flags,
        nlink=st.st_nlink,
    )


def _package_size(path: str, tr: Traversal) -> int:
    total = 0
    count = 0
    deadline = time.monotonic() + PACKAGE_SIZE_MAX_SECONDS
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    count += 1
                    if count > PACKAGE_SIZE_MAX_ENTRIES or time.monotonic() > deadline:
                        tr.truncated_sizes += 1
                        return total
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat_mod.S_ISDIR(st.st_mode):
                        if not st.st_flags & paths.SF_DATALESS:
                            stack.append(e.path)
                    else:
                        total += st.st_size
        except OSError:
            continue
    return total


def _record_skip(tr: Traversal, exc: OSError, path: str) -> None:
    tr.safe_prefixes.append(path)
    tr.status = "partial"
    if exc.errno == errno.EPERM:
        tr.tcc_skipped += 1
    else:
        tr.permission_skipped += 1


def traverse(
    root: RootSpec,
    settings: ScanSettings,
    other_root_ids: Iterable[tuple[int, int]],
    progress: Progress | None = None,
    other_root_paths: Iterable[str] = (),
) -> Traversal:
    """Walk one root with an explicit stack (04 §2.1). Never follows symlinks.

    `other_root_ids` are the (st_dev, st_ino) of the other active root directories: a
    sub-directory with one of those identities belongs to that root and is pruned here
    (identity, not path, comparison - 04 §1.1). `other_root_paths` are roots whose identity
    is unknown this run (they did not answer the probe): pruned by path, so the outer
    traversal never walks into a hung or denied inner root.
    """
    tr = Traversal(root_id=root.id)
    try:
        root_st = os.stat(root.path)
    except OSError as exc:
        tr.access = paths.classify_oserror(exc)
        tr.status = "tcc_denied" if tr.access == "tcc_denied" else "unavailable"
        return tr
    root_dev = root_st.st_dev
    inner = frozenset(other_root_ids) - {(root_st.st_dev, root_st.st_ino)}
    inner_paths = frozenset(other_root_paths) - {root.path}
    excluded_ids = settings.builtin_excluded_ids
    excludes = settings.excludes
    hook = flags_hook
    stack: list[tuple[str, str, int]] = [(root.path, "", 0)]
    dir_obs: dict[str, Obs] = {}
    last_progress = time.monotonic()
    first = True
    while stack:
        dpath, drel, depth = stack.pop()
        try:
            with os.scandir(dpath) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            if first:
                tr.access = paths.classify_oserror(exc)
                tr.status = "tcc_denied" if tr.access == "tcc_denied" else "unavailable"
                return tr
            _record_skip(tr, exc, dpath)
            continue
        first = False
        too_wide = len(entries) > DIR_FANOUT_LIMIT
        if too_wide:
            tr.partial_dirs += 1
            tr.status = "partial"
        child_dirs: list[tuple[str, str, int]] = []
        for e in entries:
            name = e.name
            if name in BUILTIN_EXCLUDED_NAMES or name.startswith("._"):
                continue
            path = e.path
            if path in settings.builtin_excluded_paths:
                continue
            if path in inner_paths:
                tr.safe_prefixes.append(path)  # an unreachable inner root keeps its entries
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                _record_skip(tr, exc, path)
                continue
            flags = st.st_flags
            if hook is not None:
                flags = hook(path, flags)
            mode = st.st_mode
            is_dir = stat_mod.S_ISDIR(mode)
            rel = f"{drel}/{name}" if drel else name
            if is_dir and (st.st_dev, st.st_ino) in excluded_ids:
                continue
            if is_dir and (st.st_dev, st.st_ino) in inner:
                tr.safe_prefixes.append(path)  # owned by the inner (more specific) root
                continue
            verdict = excludes.classify(rel, is_dir)
            if verdict == "exclude":
                continue
            # Files being written (settle, 04 §2.2-4) are recorded like any other: settle only
            # delays review-item creation (M2).
            ext = _ext(name)
            if tr.entries_seen >= settings.max_entries_per_root:
                tr.truncated = True
                tr.status = "partial"
                break
            tr.entries_seen += 1
            if progress is not None and (
                tr.entries_seen % 1000 == 0 or time.monotonic() - last_progress >= 1.0
            ):
                last_progress = time.monotonic()
                progress(root.id, tr.entries_seen)
            dataless = paths.is_dataless(name, flags)
            if stat_mod.S_ISLNK(mode):
                if dataless:
                    tr.dataless_files += 1
                tr.obs.append(_obs(root.id, path, name, "symlink", st, flags, st.st_size))
                continue
            if not is_dir:
                if dataless:
                    tr.dataless_files += 1
                tr.obs.append(_obs(root.id, path, name, "file", st, flags, st.st_size))
                continue
            if settings.package_dirs_as_files and ext in PACKAGE_EXTS:
                size = st.st_size if dataless else _package_size(path, tr)
                if dataless:
                    tr.dataless_files += 1
                tr.obs.append(_obs(root.id, path, name, "package", st, flags, size))
                continue
            o = _obs(root.id, path, name, "dir", st, flags, 0)
            tr.obs.append(o)
            dir_obs[path] = o
            child_depth = depth + 1
            if verdict == "no_descend":
                continue
            if dataless:
                tr.dataless_dirs += 1
                tr.safe_prefixes.append(path)
                continue
            if st.st_dev != root_dev:
                tr.safe_prefixes.append(path)
                continue
            if root.kind != "projects" and _is_git_worktree(path):
                continue
            if root.max_depth is not None and child_depth > root.max_depth:
                tr.safe_prefixes.append(path)
                continue
            if too_wide:
                tr.safe_prefixes.append(path)
                continue
            child_dirs.append((path, rel, child_depth))
        if tr.truncated:
            break
        # Reverse so that the stack pops children in name order (determinism, 04 §2.1).
        stack.extend(reversed(child_dirs))
    _accumulate_dir_sizes(tr.obs, dir_obs)
    return tr


def _is_git_worktree(path: str) -> bool:
    try:
        os.lstat(os.path.join(path, ".git"))
        return True
    except OSError:
        return False


def _accumulate_dir_sizes(obs: list[Obs], dir_obs: dict[str, Obs]) -> None:
    for o in sorted(obs, key=lambda x: x.path.count("/"), reverse=True):
        parent = dir_obs.get(os.path.dirname(o.path))
        if parent is not None:
            parent.size += o.size


# --------------------------------------------------------------------------- diff


def _identity_rules_ok(prev: Prev, o: Obs) -> bool:
    if prev.kind != o.kind:
        return False
    if prev.birthtime_ns is not None and o.birthtime_ns is not None:
        if prev.birthtime_ns != o.birthtime_ns:
            return False
    # Hard links: path matching only. Directories (and packages) always have nlink >= 2
    # and cannot be hard-linked on APFS, so the rule applies to files and symlinks.
    return o.kind in ("dir", "package") or o.nlink == 1


def _content_changed(prev: Prev, o: Obs) -> bool:
    if prev.kind in ("file", "symlink"):
        return prev.size != o.size or prev.mtime_ns != o.mtime_ns
    if prev.kind == "package":
        # Decision: a package's own mtime only - internal size drift (app auto-update) is
        # not a modification (04 §2.3 intent). Size is refreshed silently.
        return prev.mtime_ns != o.mtime_ns
    return False


Hasher = Callable[[Obs], str | None]


def diff(
    prev_rows: Iterable[Prev],
    observations: list[Obs],
    vanish_root_ids: set[int],
    is_safe: Callable[[Prev], bool],
    hasher: Hasher | None = None,
) -> Changes:
    """Snapshot diff (04 §2.4). `vanish_root_ids`: roots whose unseen rows may vanish."""
    ch = Changes()
    by_path: dict[str, Prev] = {}
    by_ident: dict[tuple[int, int], list[Prev]] = {}
    for row in prev_rows:
        by_path[row.path] = row
        by_ident.setdefault((row.dev, row.inode), []).append(row)
    observed_paths = {o.path for o in observations}
    seen: set[int] = set()
    appeared: list[Obs] = []
    replaced: list[tuple[Prev, Obs]] = []

    def take_candidate(o: Obs) -> Prev | None:
        cands = [
            q
            for q in by_ident.get((o.dev, o.inode), ())
            if q.id not in seen and q.path not in observed_paths
        ]
        if len(cands) == 1 and _identity_rules_ok(cands[0], o):
            return cands[0]
        return None

    for o in sorted(observations, key=lambda x: x.path):
        p = by_path.get(o.path)
        if p is not None and (p.dev, p.inode) == (o.dev, o.inode):
            seen.add(p.id)
            if _content_changed(p, o):
                ch.modified.append((p, o))
            else:
                ch.unchanged.append((p, o))
            continue
        if p is not None:
            # Same path, different inode (safe save, or rename-over).
            q = take_candidate(o)
            if q is not None:
                seen.add(q.id)
                ch.moved.append((q, o, True))
                # p is now unseen -> vanished/deleted below.
            elif p.kind != o.kind:
                appeared.append(o)  # p vanishes; o is new
            else:
                seen.add(p.id)
                if p.kind == "dir":
                    ch.unchanged.append((p, o))  # directories never get `modified`
                else:
                    replaced.append((p, o))
            continue
        q = take_candidate(o)
        if q is not None:
            seen.add(q.id)
            ch.moved.append((q, o, True))
        else:
            appeared.append(o)
    ch.modified.extend(replaced)

    vanished = [
        p
        for p in by_path.values()
        if p.id not in seen and p.root_id in vanish_root_ids and not is_safe(p)
    ]
    appeared, vanished = _match_placeholders(appeared, vanished, ch)
    appeared, vanished = _match_cross_device(appeared, vanished, ch, hasher)
    ch.created.extend(appeared)
    ch.deleted.extend(vanished)
    _suppress_child_moves(ch)
    return ch


def _match_placeholders(
    appeared: list[Obs], vanished: list[Prev], ch: Changes
) -> tuple[list[Obs], list[Prev]]:
    """`.X.icloud` <-> `X` in the same directory = same entry, no event (04 §2.6)."""

    def key(path: str) -> tuple[str, str]:
        d, n = os.path.split(path)
        return d, paths.legacy_placeholder_name(n) or n

    by_key: dict[tuple[str, str], list[Prev]] = {}
    for v in vanished:
        by_key.setdefault(key(v.path), []).append(v)
    used: set[int] = set()
    rest: list[Obs] = []
    for o in appeared:
        cands = [v for v in by_key.get(key(o.path), []) if v.id not in used and v.kind == o.kind]
        is_pair = len(cands) == 1 and (
            paths.legacy_placeholder_name(os.path.basename(cands[0].path)) is not None
        ) != (paths.legacy_placeholder_name(o.name) is not None)
        if is_pair:
            used.add(cands[0].id)
            ch.moved.append((cands[0], o, False))
        else:
            rest.append(o)
    return rest, [v for v in vanished if v.id not in used]


def _match_cross_device(
    appeared: list[Obs], vanished: list[Prev], ch: Changes, hasher: Hasher | None
) -> tuple[list[Obs], list[Prev]]:
    """Second-pass cross-volume move match (04 §2.4). Hashes stay in memory only."""
    if hasher is None:
        return appeared, vanished
    a_groups: dict[tuple[str, int], list[Obs]] = {}
    v_groups: dict[tuple[str, int], list[Prev]] = {}
    for o in appeared:
        if o.kind == "file" and o.size >= CROSS_DEVICE_MIN_SIZE:
            a_groups.setdefault((o.name, o.size), []).append(o)
    for v in vanished:
        if v.kind == "file" and v.size >= CROSS_DEVICE_MIN_SIZE and v.sha256:
            v_groups.setdefault((os.path.basename(v.path), v.size), []).append(v)
    matched_o: set[int] = set()
    matched_v: set[int] = set()
    for k, vs in v_groups.items():
        os_ = a_groups.get(k, [])
        if len(vs) != 1 or len(os_) != 1:
            continue
        digest = hasher(os_[0])
        if digest is not None and digest == vs[0].sha256:
            ch.moved.append((vs[0], os_[0], True))
            matched_o.add(id(os_[0]))
            matched_v.add(vs[0].id)
    return (
        [o for o in appeared if id(o) not in matched_o],
        [v for v in vanished if v.id not in matched_v],
    )


def _suppress_child_moves(ch: Changes) -> None:
    """A moved directory is one event; its descendants only get path updates (04 §2.4)."""
    dir_moves = [(p.path, o.path) for p, o, emit in ch.moved if emit and p.kind == "dir"]
    if not dir_moves:
        return
    out: list[tuple[Prev, Obs, bool]] = []
    for p, o, emit in ch.moved:
        if emit:
            for old_d, new_d in dir_moves:
                if p.path.startswith(old_d + "/") and o.path == new_d + p.path[len(old_d) :]:
                    emit = False
                    break
        out.append((p, o, emit))
    ch.moved = out


def make_hasher(hash_max_bytes: int) -> Hasher:
    """Read-only SHA-256 for cross-volume matching; never for dataless files (04 §2.5-2.6)."""

    def h(o: Obs) -> str | None:
        if o.size == 0 or o.size > hash_max_bytes:
            return None
        try:
            st = os.lstat(o.path)
        except OSError:
            return None
        flags = flags_hook(o.path, st.st_flags) if flags_hook is not None else st.st_flags
        if paths.is_dataless(o.name, flags) or not stat_mod.S_ISREG(st.st_mode):
            return None
        digest = hashlib.sha256()
        try:
            with open(o.path, "rb") as fh:
                while chunk := fh.read(HASH_BUFFER):
                    digest.update(chunk)
            if os.lstat(o.path).st_mtime_ns != st.st_mtime_ns:
                return None
        except OSError:
            return None
        return digest.hexdigest()

    return h
