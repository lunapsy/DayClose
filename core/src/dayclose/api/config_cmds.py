"""config.get / config.set / config.list (10 §2.2)."""

from __future__ import annotations

from typing import Any

from dayclose import config as config_mod
from dayclose.api.runtime import Context, command
from dayclose.common.errors import UsageError
from dayclose.policy import icloud


def _entry(cfg: config_mod.Config, key: str) -> dict[str, Any]:
    return {
        "key": key,
        "value": cfg.get(key),
        "default": config_mod.DEFAULTS[key],
        "source": cfg.source(key),
    }


def _key(args: dict[str, Any]) -> str:
    key = args.get("key")
    if not isinstance(key, str) or not key:
        raise UsageError("KEY 가 필요합니다.")
    config_mod.known_key(key)
    return key


@command("config.get")
def config_get(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    return _entry(ctx.config, _key(args))


@command("config.list")
def config_list(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(config_mod.DEFAULTS)
    return {"items": [_entry(ctx.config, k) for k in keys], "next_cursor": None, "total": len(keys)}


@command("config.set", writes=True)
def config_set(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    key = _key(args)
    raw = args.get("value")
    if key in config_mod.READ_ONLY:
        raise UsageError("읽기 전용 설정 키입니다.", {"key": key, "reason": "read_only"})
    if isinstance(raw, str):
        value = config_mod.parse_value(raw)
    elif raw is None:
        raise UsageError("VALUE 가 필요합니다.")
    else:
        value = raw
    config_mod.validate(key, value)
    cfg = ctx.config
    old = cfg.get(key)
    values = dict(cfg.file_values)
    values[key] = value
    config_mod.save(ctx.home, values)
    ctx.cfg = config_mod.Config(values)
    ctx.audit.target_type = "config"
    ctx.audit.summary = f"config.set {key}"
    out: dict[str, Any] = {"key": key, "old_value": old, "value": value}
    if key == "icloud.allow_trash":
        out["effective"] = icloud.trash_gate_open(bool(value))
    return out
