from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast


def test_real_list_mode_compiler_reports_bounded_stage_caches() -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_list_mode_compiler.py"
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--entries",
            "4",
            "--repetitions",
            "16",
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("LIST_MODE_COMPILER_BENCHMARK=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("LIST_MODE_COMPILER_BENCHMARK=")),
    )
    assert result["schema"] == "scopecat.list_mode_compiler_benchmark.v1"
    assert result["entry_count"] == 4
    assert result["repetitions"] == 16
    assert result["artifact_reused"] is True
    assert cast("int", result["waveform_bytes"]) > 0
    assert cast("int", result["result_bytes"]) > 0

    cold = cast("dict[str, object]", result["cold_trace"])
    warm = cast("dict[str, object]", result["warm_trace"])
    assert [
        cold[stage] for stage in ("semantic", "placement", "layout", "artifact")
    ] == [
        "miss",
        "miss",
        "miss",
        "miss",
    ]
    assert warm["artifact"] == "hit"
    assert [warm[stage] for stage in ("semantic", "placement", "layout")] == [
        "not_checked",
        "not_checked",
        "not_checked",
    ]

    cold_cache = cast("dict[str, dict[str, int]]", cold["cache_info"])
    for stage in ("semantic", "placement", "layout", "artifact"):
        cache = cold_cache[stage]
        assert 0 < cache["retained_bytes"] <= cache["max_retained_bytes"]

    bounded = cast(
        "dict[str, int]",
        result["byte_bounded_artifact_cache"],
    )
    assert bounded["size"] == 1
    assert bounded["evictions"] == 1
    assert bounded["retained_bytes"] <= bounded["max_retained_bytes"]

    oversize = cast("dict[str, int]", result["oversize_artifact_cache"])
    assert oversize["size"] == 0
    assert oversize["retained_bytes"] == 0
    assert oversize["misses"] == 2
    assert oversize["oversize_skips"] == 2
