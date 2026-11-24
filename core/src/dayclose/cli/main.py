"""`dayclose` CLI transport: argv -> api.execute -> envelope or human text (10 §1)."""

from __future__ import annotations

import argparse
import sys
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any, NoReturn

from dayclose import __version__, api
from dayclose.api.root_cmds import ICLOUD_MODES, ROOT_KINDS
from dayclose.api.runtime import CHANNELS, LOG_LEVELS, Options
from dayclose.common import envelope
from dayclose.common.errors import UsageError


class _Parser(argparse.ArgumentParser):
    """argparse errors become E_USAGE envelopes instead of exit(2) (10 §1.3)."""

    def error(self, message: str) -> NoReturn:
        raise UsageError("명령 인자가 올바르지 않습니다.", {"argparse": message})


def _globals() -> _Parser:
    # SUPPRESS defaults: a flag given before the noun is not reset by the subparser.
    g = _Parser(add_help=False)
    s = argparse.SUPPRESS
    g.add_argument("--json", action="store_true", default=s)
    g.add_argument("--home", default=s)
    g.add_argument("--progress", choices=["ndjson"], default=s)
    g.add_argument("--wait-lock", type=float, default=s)
    g.add_argument("--channel", choices=list(CHANNELS), default=s)
    g.add_argument("--log-level", choices=list(LOG_LEVELS), default=s)
    return g


def _list_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--limit", type=int)
    p.add_argument("--cursor")


def build_parser() -> argparse.ArgumentParser:
    g = _globals()
    parser = _Parser(prog="dayclose", parents=[g], description="DayClose core")
    top = parser.add_subparsers(dest="noun", parser_class=_Parser)

    def leaf(sub: Any, name: str, command_id: str) -> argparse.ArgumentParser:
        p: argparse.ArgumentParser = sub.add_parser(name, parents=[g])
        p.set_defaults(command_id=command_id)
        return p

    leaf(top, "version", "core.version")
    p = leaf(top, "init", "core.init")
    p.add_argument("--device-name")
    p.add_argument("--no-default-roots", action="store_true")
    leaf(top, "doctor", "core.doctor")

    cfg = top.add_parser("config", parents=[g]).add_subparsers(dest="verb", parser_class=_Parser)
    leaf(cfg, "get", "config.get").add_argument("key")
    p = leaf(cfg, "set", "config.set")
    p.add_argument("key")
    p.add_argument("value")
    leaf(cfg, "list", "config.list")

    root = top.add_parser("root", parents=[g]).add_subparsers(dest="verb", parser_class=_Parser)
    p = leaf(root, "list", "root.list")
    p.add_argument("--all", action="store_true")
    _list_flags(p)
    p = leaf(root, "add", "root.add")
    p.add_argument("path")
    p.add_argument("--kind", required=True, choices=list(ROOT_KINDS))
    p.add_argument("--max-depth", type=int)
    p.add_argument("--icloud-synced", choices=list(ICLOUD_MODES))
    leaf(root, "remove", "root.remove").add_argument("root_id")

    return parser


_GLOBAL_KEYS = (
    "json",
    "home",
    "progress",
    "wait_lock",
    "channel",
    "log_level",
    "noun",
    "verb",
    "command_id",
)


def parse(argv: Sequence[str]) -> tuple[str, dict[str, Any], Options, bool]:
    ns = build_parser().parse_args(list(argv))
    command_id = getattr(ns, "command_id", None)
    if command_id is None:
        raise UsageError("명령을 지정하세요.", {"usage": "dayclose <noun> <verb> [flags] --json"})
    raw = vars(ns)
    args = {
        k: v for k, v in raw.items() if k not in _GLOBAL_KEYS and v is not None and v is not False
    }
    for key in ("collectors", "event"):
        if isinstance(args.get(key), str):
            args[key] = [x for x in args[key].split(",") if x]
    opts = Options(
        home=raw.get("home"),
        channel=raw.get("channel", "cli"),
        wait_lock=raw.get("wait_lock", 10.0),
        progress=raw.get("progress"),
        log_level=raw.get("log_level", "info"),
    )
    return command_id, args, opts, bool(raw.get("json", False))


_CORE_VERBS = {
    "version": "core.version",
    "init": "core.init",
    "doctor": "core.doctor",
    "schema": "core.schema",
    "serve": "core.serve",
}


def _guess_command(argv: Sequence[str]) -> str:
    """Best-effort command ID for an envelope whose argv could not be parsed."""
    words = [a for a in argv if not a.startswith("-")]
    if not words:
        return ""
    if words[0] in _CORE_VERBS:
        return _CORE_VERBS[words[0]]
    return f"{words[0]}.{words[1]}" if len(words) > 1 else words[0]


def _usage_failure(err: UsageError, as_json: bool, argv: Sequence[str]) -> int:
    meta = envelope.Meta(envelope.new_request_id(), __version__, None, None, 0)
    command_id = _guess_command(argv)
    env = envelope.failure(command_id, err, [], meta)
    _emit(env, as_json, command_id)
    if not as_json and "argparse" in err.details:
        sys.stderr.write(f"  {err.details['argparse']}\n")
    return err.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args_list
    try:
        command_id, args, opts, as_json = parse(args_list)
    except UsageError as err:
        return _usage_failure(err, as_json, args_list)
    env, code = api.execute(command_id, args, opts)
    _emit(env, as_json, command_id)
    return code


# --------------------------------------------------------------------------- human output


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _clean(value: Any) -> str:
    text = "-" if value is None else str(value)
    return text.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")


def _table(rows: list[list[str]], header: list[str]) -> list[str]:
    widths = [max(_width(r[i]) for r in [header, *rows]) for i in range(len(header))]
    return [
        "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)).rstrip() for r in [header, *rows]
    ]


def _render_list(data: dict[str, Any], columns: list[tuple[str, str]]) -> list[str]:
    rows = [[_clean(item.get(key)) for key, _ in columns] for item in data.get("items", [])]
    out = _table(rows, [label for _, label in columns]) if rows else []
    total = data.get("total")
    out.append(f"총 {total if total is not None else len(rows)}개")
    if data.get("next_cursor"):
        out.append(f"다음: --cursor {data['next_cursor']}")
    return out


def _kv(data: dict[str, Any]) -> list[str]:
    return [f"{k}: {_clean(v)}" for k, v in data.items() if not isinstance(v, (dict, list))]


_RENDER: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "core.version": lambda d: [
        f"DayClose core {d['core_version']} (계약 v{d['contract_version']}, "
        f"DB v{_clean(d['db_schema_version'])}/{d['db_schema_supported']}, Python {d['python']})"
    ],
    "core.init": lambda d: [
        (f"초기화 완료: {d['home']}" if d["created"] else f"이미 초기화됨: {d['home']}")
        + f" (DB v{d['db_schema_version']}, 루트 {len(d['roots_added'])}개 추가)"
    ],
    "core.doctor": lambda d: (
        [("[정상] " if d["healthy"] else "[문제] ") + "진단 결과"]
        + [f"[문제] {i['message']}" for i in d["issues"]]
        + [f"루트 {r['root_id']} {r['display_path']}: {r['access']}" for r in d["roots"]]
    ),
    "config.list": lambda d: _render_list(d, [("key", "키"), ("value", "값"), ("source", "출처")]),
    "root.list": lambda d: _render_list(
        d, [("id", "ID"), ("kind", "종류"), ("display_path", "경로"), ("icloud_synced", "iCloud")]
    ),
    "root.add": lambda d: [
        ("루트 등록: " if d["created"] else "이미 등록됨: ")
        + f"{d['root']['id']} {d['root']['display_path']}"
    ],
}


def _emit(env: dict[str, Any], as_json: bool, command_id: str) -> None:
    if as_json:
        sys.stdout.write(envelope.dumps(env) + "\n")
        sys.stdout.flush()
        return
    if not env["ok"]:
        err = env["error"]
        sys.stderr.write(f"오류({err['code']}): {err['message']}\n")
    else:
        data = env["data"]
        render = _RENDER.get(command_id)
        lines = render(data) if render else _kv(data)
        sys.stdout.write("\n".join(lines) + "\n")
    for w in env["warnings"]:
        sys.stderr.write(f"경고({w['code']}): {w['message']}\n")
