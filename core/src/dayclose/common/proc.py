"""The only subprocess entry point (02 §6 `run_tool`).

Allow-listed tools by absolute path, no shell, fixed minimal environment, mandatory timeout.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass

from dayclose.common import paths
from dayclose.common.errors import EnvironmentError_, SafetyError

# Tools whose output is an approval decision: must be root-owned and not group/other writable.
_APPROVAL_PATH_TOOLS = frozenset({"osascript"})


@dataclass(frozen=True)
class ToolResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


def _check_trusted(path: str) -> None:
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SafetyError(
            "E_APPROVAL_DENIED",
            "신뢰할 수 없는 승인 도구입니다.",
            {"reason": "untrusted_tool"},
        )


def run_tool(
    tool: str,
    args: list[str],
    timeout: float,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
) -> ToolResult:
    if tool not in paths.TOOLS:
        raise ValueError(f"tool not allow-listed: {tool}")
    if timeout <= 0:
        raise ValueError("timeout is mandatory")
    exe = paths.system_path(tool)
    if exe is None:
        raise EnvironmentError_(
            "E_TOOL_MISSING", "필요한 외부 도구를 찾을 수 없습니다.", {"tool": tool}
        )
    if tool in _APPROVAL_PATH_TOOLS and not paths.sandbox_status().valid:
        _check_trusted(exe)
    fixed_env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "HOME": str(paths.user_home()),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    if env:
        fixed_env.update(env)
    try:
        proc = subprocess.run(
            [exe, *args],
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            env=fixed_env,
            shell=False,
            check=False,
            close_fds=True,
            cwd="/",
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, bytes) else b""
        err = exc.stderr if isinstance(exc.stderr, bytes) else b""
        return ToolResult(-1, out, err, timed_out=True)
    return ToolResult(proc.returncode, proc.stdout, proc.stderr)
