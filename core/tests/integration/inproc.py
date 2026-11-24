"""In-process api helpers for tests that need injection (EPERM, hung volume, SF_DATALESS).

The CLI calls the same `api.execute`.
"""

from __future__ import annotations

from typing import Any

from dayclose import api
from dayclose.api.runtime import Options


def run(command: str, **args: Any) -> tuple[dict[str, Any], int]:
    return api.execute(command, args, Options())


def ok(command: str, **args: Any) -> dict[str, Any]:
    env, code = run(command, **args)
    assert code == 0, env
    data: dict[str, Any] = env["data"]
    return data


def init(**cfg: Any) -> None:
    ok("core.init", no_default_roots=True)
    for k, v in cfg.items():
        ok("config.set", key=k.replace("__", "."), value=str(v))
