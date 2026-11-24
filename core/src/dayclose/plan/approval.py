"""Approval-method constants (02 §10.3-2, 10 §8.5).

The single list of agent environment markers. `api` uses it for channel promotion; the
approval-method selection (M5) will use the same list.
"""

from __future__ import annotations

AGENT_ENV_MARKERS: tuple[str, ...] = (
    "CLAUDECODE",
    "AI_AGENT",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
)
