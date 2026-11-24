"""iCloud trash unlock gate (02 §10.1 exception 2, 08 §9.1).

Only a reviewed change after the 08 §9.1 device verification (recorded in 09 §12) may set
this to True (M5 exit criterion).
"""

from __future__ import annotations

TRASH_UNLOCK_VERIFIED = False


def trash_gate_open(allow_trash_setting: bool) -> bool:
    return TRASH_UNLOCK_VERIFIED and allow_trash_setting
