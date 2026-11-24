"""M1 performance measurements (11 §7). Run with `uv run pytest -m perf`; prints one JSON line."""

from __future__ import annotations

import statistics
import time
from datetime import datetime
from typing import Any

import pytest
from conftest import RunCli, Sandbox
from fixtures.sandbox import build_sandbox


@pytest.mark.perf
def test_m1_warm_scan_10k(
    initialized: RunCli, sandbox: Sandbox, now: datetime, record_perf: Any
) -> None:
    cli = initialized
    build_sandbox(sandbox.root, "perf_10k", now=now)
    assert (
        cli("root", "add", str(sandbox.user / "Downloads"), "--kind", "downloads").returncode == 0
    )
    base = cli("scan", "run")
    assert base.data["stats"]["baseline_entries"] == 10_100
    timings = []
    for _ in range(3):
        start = time.monotonic()
        res = cli("scan", "run")
        timings.append(time.monotonic() - start)
        s = res.data["stats"]
        assert (s["created"], s["modified"], s["deleted"], s["moved"]) == (0, 0, 0, 0)
    best = min(timings)
    record_perf(
        {
            "test": "m1_warm_scan_10k",
            "entries": 10_100,
            "wall_s": [round(t, 3) for t in timings],
            "best_s": round(best, 3),
        }
    )
    assert best <= 2.0


@pytest.mark.perf
def test_nfr_perf_003_version_startup(cli: RunCli, record_perf: Any) -> None:
    timings = []
    for _ in range(20):
        start = time.monotonic()
        assert cli("version").returncode == 0
        timings.append(time.monotonic() - start)
    rest = sorted(timings[1:])
    p95 = rest[int(len(rest) * 0.95) - 1]
    record_perf(
        {
            "test": "version_startup",
            "median_s": round(statistics.median(rest), 3),
            "p95_s": round(p95, 3),
        }
    )
    assert p95 <= 0.25
