"""Sandbox tree generator (11 §3). Does not import dayclose (oracle kept separate from SUT)."""

from __future__ import annotations

import json
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ICLOUD_REL = "Library/Mobile Documents/com~apple~CloudDocs"


@dataclass
class FileSpec:
    path: Path
    kind: str = "file"  # file | dir | package
    dataless: bool = False


@dataclass
class Manifest:
    root: Path
    files: list[FileSpec] = field(default_factory=list)

    @property
    def user(self) -> Path:
        return self.root / "user"

    def dataless_paths(self) -> list[Path]:
        return [f.path for f in self.files if f.dataless]


def _write(m: Manifest, path: Path, data: bytes, when: datetime, *, dataless: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    ts = when.timestamp()
    os.utime(path, (ts, ts))
    m.files.append(FileSpec(path, "file", dataless))


def build_sandbox(root: Path, preset: str, *, seed: int = 0, now: datetime) -> Manifest:
    """Presets used by M1: `minimal`, `tree`, `icloud`, `perf_10k`.

    File times are set one hour (or more) in the past so that the 60 s settle window
    (04 §2.2) never hides them.
    """
    rnd = random.Random(seed)
    m = Manifest(root)
    past = now - timedelta(hours=1)
    user = m.user
    if preset == "minimal":
        for name in ("report.pdf", "photo.jpg", "notes.txt"):
            _write(m, user / "Downloads" / name, rnd.randbytes(64), past)
    elif preset == "tree":
        dl = user / "Downloads"
        for name in ("a.txt", "b.txt", "c.pdf"):
            _write(m, dl / name, rnd.randbytes(32), past)
        _write(m, dl / ".DS_Store", b"\x00" * 8, past)
        _write(m, dl / "proj" / "node_modules" / "left-pad" / "index.js", b"x", past)
        _write(m, dl / "proj" / "README.md", b"readme", past)
        _write(m, dl / "repo" / ".git" / "HEAD", b"ref: refs/heads/main\n", past)
        _write(m, dl / "repo" / "src" / "main.py", b"print(1)\n", past)
        _write(m, dl / "Thing.app" / "Contents" / "Info.plist", b"<plist/>", past)
        _write(m, dl / "Thing.app" / "Contents" / "MacOS" / "thing", b"\x7fELF", past)
        _write(m, dl / "deep" / "one" / "two" / "three.txt", b"3", past)
    elif preset == "icloud":
        drive = user / ICLOUD_REL
        for name in ("plan.txt", "budget.numbers.txt", "photo.jpg"):
            _write(m, drive / name, rnd.randbytes(48), past)
        _write(m, drive / ".계약서.pdf.icloud", b"bplist00placeholder", past)
        _write(m, drive / "lazy.pdf", b"decoy content", past, dataless=True)
        _write(m, drive / ".env", b"API_KEY=decoy-not-a-secret", past, dataless=True)
        _write(m, drive / "Library" / "inner.txt", b"inner", past)
        _write(m, drive / "Desktop" / "on-desktop.txt", b"desk", past)
        _write(m, user / "Downloads" / "dl.txt", b"dl", past)
    elif preset == "perf_10k":
        base = user / "Downloads"
        for d in range(100):
            sub = base / f"d{d:03d}"
            sub.mkdir(parents=True, exist_ok=True)
            for f in range(100):
                p = sub / f"f{f:03d}.bin"
                p.touch()
                ts = past.timestamp()
                os.utime(p, (ts, ts))
    else:
        raise ValueError(f"unknown preset {preset}")
    return m


def install_fake_tool(
    sandbox: Path, name: str, *, stdout: str | None = None, returncode: int = 0
) -> Path:
    """Fake external tool in `$SANDBOX/bin` that records argv to `.tooldata/calls.jsonl`."""
    bin_dir = sandbox / "bin"
    data = sandbox / ".tooldata"
    bin_dir.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    spec = {"stdout": stdout, "returncode": returncode}
    (data / f"{name}.json").write_text(json.dumps(spec))
    script = bin_dir / name
    script.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        f"data = {str(data)!r}\n"
        "with open(os.path.join(data, 'calls.jsonl'), 'a') as fh:\n"
        f"    fh.write(json.dumps({{'tool': {name!r}, 'argv': sys.argv[1:],"
        " 'env': sorted(os.environ)}) + '\\n')\n"
        f"spec = json.load(open(os.path.join(data, {name + '.json'!r})))\n"
        "if spec['stdout'] is not None:\n"
        "    sys.stdout.write(spec['stdout'])\n"
        "sys.exit(spec['returncode'])\n"
    )
    script.chmod(0o755)
    return script


def tool_calls(sandbox: Path) -> list[dict[str, object]]:
    path = sandbox / ".tooldata" / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]
