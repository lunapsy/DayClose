"""Command registry. Importing this package registers every implemented command."""

from dayclose.api import config_cmds, core_cmds, root_cmds, scan_cmds
from dayclose.api.runtime import REGISTRY, Options, execute

__all__ = ["REGISTRY", "Options", "config_cmds", "core_cmds", "execute", "root_cmds", "scan_cmds"]
