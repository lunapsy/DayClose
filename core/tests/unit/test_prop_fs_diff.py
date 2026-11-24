"""prop_fs_diff (11 §5.2, FR-CORE-003): each single FS change -> exactly one matching event.

Runs the real collector against a real sandbox directory through the in-process api.
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path
from typing import Any

from conftest import Sandbox
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dayclose import api
from dayclose.api.runtime import Options

NAMES = ["a.txt", "b.txt", "c.bin", "스크린샷.png", "d d.txt", "-rf.txt"]
OPS = st.lists(
    st.tuples(
        st.sampled_from(["create", "modify", "delete", "rename", "noop"]),
        st.sampled_from(NAMES),
        st.sampled_from(NAMES),
    ),
    min_size=1,
    max_size=8,
)


def _ok(command: str, home: Path, **args: Any) -> dict[str, Any]:
    env, code = api.execute(command, args, Options(home=str(home)))
    assert code == 0, env
    data: dict[str, Any] = env["data"]
    return data


def _stats(data: dict[str, Any]) -> tuple[int, int, int, int]:
    s = data["stats"]
    return s["created"], s["modified"], s["deleted"], s["moved"]


_counter = itertools.count()


# Every example gets a fresh home and root directory, so the shared fixture is fine.
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ops=OPS)
def test_prop_fs_diff(sandbox: Sandbox, ops: list[tuple[str, str, str]]) -> None:
    n = next(_counter)
    home = sandbox.root / f"home-{n}"
    root = sandbox.user / f"prop-{n}"
    root.mkdir(parents=True)
    _ok("core.init", home, no_default_roots=True)
    _ok("root.add", home, path=str(root), kind="custom")
    _ok("scan.run", home)
    tick = 1_000_000_000_000_000_000
    for op, name, other in ops:
        p, q = root / name, root / other
        tick += 10_000_000_000
        expected = (0, 0, 0, 0)
        if op == "create" and not p.exists():
            p.write_bytes(b"x")
            os.utime(p, ns=(tick, tick))
            expected = (1, 0, 0, 0)
        elif op == "modify" and p.exists():
            with open(p, "ab") as fh:
                fh.write(b"y")
            os.utime(p, ns=(tick, tick))
            expected = (0, 1, 0, 0)
        elif op == "delete" and p.exists():
            p.unlink()
            expected = (0, 0, 1, 0)
        elif op == "rename" and p.exists() and not q.exists():
            p.rename(q)
            expected = (0, 0, 0, 1)
        assert _stats(_ok("scan.run", home)) == expected, (op, name, other)
