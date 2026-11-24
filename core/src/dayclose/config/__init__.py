"""`config.toml` defaults, load/validate/save (02 §9, 10 §2.2). No DB access here."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dayclose.common.envelope import Warning_
from dayclose.common.errors import EnvironmentError_, UsageError

CONFIG_NAME = "config.toml"
SCHEMA_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "device_id": "",
    "device_name": "",
    "review.daily_time": "21:00",
    "review.day_boundary": "04:00",
    "review.carryover": True,
    "scan.exclude_globs": [
        "**/.DS_Store",
        "**/node_modules/**",
        "**/.git/**",
        "**/*.photoslibrary/**",
        "**/Library/**",
    ],
    "scan.package_dirs_as_files": True,
    "scan.hash_max_bytes": 67108864,
    "scan.hash_budget_bytes": 2147483648,
    "scan.settle_seconds": 60,
    "scan.max_entries_per_root": 300000,
    "scan.devcache_min_bytes": 104857600,
    "scan.read_dataless": False,
    "scan.volume_probe_timeout_s": 5,
    "projects.roots": ["~/dev"],
    "projects.active_days": 30,
    "protection.patient_filename_patterns": ["*처방*", "*조제*", "*환자*"],
    "protection.detect_rrn_in_text": True,
    "vault.gitleaks": "auto",
    "vault.extra_paths": [
        "~/.ssh",
        "~/.aws",
        "~/.azure",
        "~/.docker",
        "~/.config/gh",
        "~/.config/gcloud",
        "~/.kube",
        "~/.gnupg",
        "~/Library/Preferences/NPKI",
    ],
    "vault.content_scan_max_bytes": 1048576,
    "vault.expiry_warn_days": 30,
    "ai.enabled": False,
    "ai.provider": "none",
    "ai.model": "",
    "ai.allow_external": False,
    "ai.ollama_url": "http://127.0.0.1:11434",
    "ai.timeout_s": 60,
    "ai.max_items_per_request": 100,
    "policy.learn_window_days": 60,
    "policy.learn_min_evidence": 5,
    "policy.learn_min_days": 3,
    "policy.learn_consistency": 0.9,
    "policy.reject_cooldown_days": 30,
    "policy.auto_apply": True,
    "policy.auto_apply_daily_cap": 200,
    "icloud.allow_trash": True,
    "archive.root": "",
    "core.log_level": "info",
}

# Not settable through `config set` (10 §2.2). `scan.read_dataless` is a fixed value (02 §9).
READ_ONLY = frozenset({"schema_version", "device_id", "scan.read_dataless"})
CHOICES: dict[str, tuple[str, ...]] = {
    "core.log_level": ("debug", "info", "warn", "error"),
    "ai.provider": ("none", "ollama", "anthropic", "openai"),
    "vault.gitleaks": ("auto", "off"),
}


@dataclass
class Config:
    file_values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        if key in self.file_values:
            return self.file_values[key]
        return DEFAULTS[key]

    def source(self, key: str) -> str:
        return "file" if key in self.file_values else "default"

    @property
    def device_id(self) -> str:
        return str(self.get("device_id"))


def config_path(home: Path) -> Path:
    return home / CONFIG_NAME


def _flatten(table: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in table.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _type_ok(key: str, value: Any) -> bool:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(default, float):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif isinstance(default, str):
        ok = isinstance(value, str)
    elif isinstance(default, list):
        ok = isinstance(value, list) and all(isinstance(x, str) for x in value)
    else:  # pragma: no cover - DEFAULTS only holds the types above
        ok = False
    if ok and key in CHOICES:
        ok = value in CHOICES[key]
    return ok


def validate(key: str, value: Any) -> None:
    if not _type_ok(key, value):
        details: dict[str, Any] = {"key": key, "expected": type(DEFAULTS[key]).__name__}
        if key in CHOICES:
            details["allowed"] = list(CHOICES[key])
        raise EnvironmentError_("E_CONFIG_INVALID", "설정 값의 형식이 올바르지 않습니다.", details)


def known_key(key: str) -> None:
    if key not in DEFAULTS:
        head = key.split(".", 1)[0]
        similar = sorted(k for k in DEFAULTS if k.split(".", 1)[0] == head)
        raise UsageError("알 수 없는 설정 키입니다.", {"key": key, "known_prefix": similar[:20]})


def load(home: Path) -> tuple[Config, list[Warning_]]:
    path = config_path(home)
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        return Config(), []
    except tomllib.TOMLDecodeError as exc:
        raise EnvironmentError_(
            "E_CONFIG_INVALID",
            "설정 파일을 읽을 수 없습니다.",
            {"reason": "toml_parse", "line": getattr(exc, "lineno", None)},
        ) from None
    warnings: list[Warning_] = []
    values: dict[str, Any] = {}
    for key, value in _flatten(raw).items():
        if key not in DEFAULTS:
            warnings.append(
                Warning_("W_CONFIG_UNKNOWN_KEY", "알 수 없는 설정 키를 무시했습니다.", {"key": key})
            )
            continue
        validate(key, value)
        values[key] = value
    return Config(values), warnings


def parse_value(text: str) -> Any:
    """TOML literal, falling back to a plain string (10 §2.2)."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


def _nest(flat: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(flat, key=lambda k: (k.count("."), k)):
        parts = key.split(".")
        node = out
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = flat[key]
    return out


def save(home: Path, file_values: dict[str, Any]) -> None:
    """Atomic replace of config.toml, mode 0600 (10 §2.2). Comments are not preserved."""
    import tomli_w  # lazy: only `init` and `config set` write the file

    path = config_path(home)
    tmp = path.with_name(f".{CONFIG_NAME}.{os.getpid()}.tmp")
    data = tomli_w.dumps(_nest(file_values)).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    os.chmod(path, 0o600)
