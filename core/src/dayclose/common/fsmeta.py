"""Read-only ctypes metadata helpers (02 §6). M1 binds only `gethostuuid` (08 §7.11).

No write APIs may ever be bound here.
"""

from __future__ import annotations

import ctypes
import hashlib

_HOST_PREFIX = b"dayclose.host.v1"


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


def _gethostuuid() -> bytes | None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)  # process namespace includes libSystem
        fn = libc.gethostuuid
    except (OSError, AttributeError):
        return None
    fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(_Timespec)]
    fn.restype = ctypes.c_int
    buf = ctypes.create_string_buffer(16)
    wait = _Timespec(1, 0)
    if fn(buf, ctypes.byref(wait)) != 0:
        return None
    return buf.raw


def host_uuid_sha256() -> str | None:
    """SHA-256(b"dayclose.host.v1" + gethostuuid()). The raw UUID never leaves this function."""
    raw = _gethostuuid()
    if raw is None:
        return None
    return hashlib.sha256(_HOST_PREFIX + raw).hexdigest()
