"""Error hierarchy and codes (02 §11). Exit codes follow 02 §5.5."""

from __future__ import annotations

from typing import Any


class DayCloseError(Exception):
    """Base error. `code` is the contract error code; `message` is Korean user text."""

    exit_code = 10
    codes: frozenset[str] = frozenset()

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        if self.codes and code not in self.codes:
            raise ValueError(f"{type(self).__name__} cannot carry {code}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})
        self.retryable = retryable


class UsageError(DayCloseError):
    exit_code = 2
    codes = frozenset({"E_USAGE"})

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("E_USAGE", message, details)


class NotFoundError(DayCloseError):
    exit_code = 3
    codes = frozenset({"E_NOT_FOUND", "E_NOT_INITIALIZED"})


class StateError(DayCloseError):
    exit_code = 4
    codes = frozenset(
        {"E_INVALID_STATE", "E_STALE", "E_DEST_EXISTS", "E_APPROVAL_MISMATCH", "E_UNDO_IMPOSSIBLE"}
    )


class SafetyError(DayCloseError):
    exit_code = 5
    codes = frozenset(
        {
            "E_PROTECTED",
            "E_APPROVAL_REQUIRED",
            "E_APPROVAL_DENIED",
            "E_SANDBOX_VIOLATION",
            "E_PATH_OUTSIDE_ROOTS",
            "E_AI_BLOCKED_SENSITIVE",
            "E_DEVICE_MISMATCH",
        }
    )


class EnvironmentError_(DayCloseError):  # noqa: N801 - name fixed by 02 §11
    exit_code = 6
    codes = frozenset(
        {
            "E_PERMISSION",
            "E_TCC_DENIED",
            "E_VOLUME_UNAVAILABLE",
            "E_VOLUME_TIMEOUT",
            "E_TOOL_MISSING",
            "E_CONFIG_INVALID",
            "E_AI_DISABLED",
            "E_ARCHIVE_TARGET_MISSING",
        }
    )


class LockError(DayCloseError):
    exit_code = 7
    codes = frozenset({"E_LOCKED"})

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("E_LOCKED", message, details, retryable=True)


class PartialError(DayCloseError):
    exit_code = 8
    codes = frozenset({"E_PARTIAL"})

    def __init__(
        self, message: str, data: dict[str, Any], details: dict[str, Any] | None = None
    ) -> None:
        super().__init__("E_PARTIAL", message, details)
        self.data = data


class CancelledError(DayCloseError):
    exit_code = 130
    codes = frozenset({"E_CANCELLED"})

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("E_CANCELLED", message, details)


class InternalError(DayCloseError):
    exit_code = 10
    codes = frozenset({"E_INTERNAL", "E_DB_CORRUPT", "E_DB_MIGRATION"})


def sandbox_violation(path: str, operation: str) -> SafetyError:
    """The path itself is not echoed into details (it may be a real user path)."""
    return SafetyError(
        "E_SANDBOX_VIOLATION",
        "샌드박스 밖의 경로에는 접근할 수 없습니다.",
        {"operation": operation},
    )
