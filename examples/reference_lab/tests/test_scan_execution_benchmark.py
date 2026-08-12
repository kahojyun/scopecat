from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast


def test_scan_execution_benchmark_runs_both_paths(tmp_path: Path) -> None:
    output = tmp_path / "results.jsonl"
    script = Path(__file__).parents[3] / "scripts" / "benchmark_scan_execution.py"

    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--points",
            "3",
            "--runners",
            "adhoc,scopecat",
            "--repetitions",
            "1",
            "--warmups",
            "0",
            "--host-label",
            "test",
            "--output",
            str(output),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    results = tuple(
        cast("dict[str, object]", json.loads(line))
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    by_runner = {result["runner"]: result for result in results}
    assert set(by_runner) == {"adhoc", "scopecat"}
    assert all(result["points_completed"] == 3 for result in results)
    assert by_runner["adhoc"]["trigger_count"] == 3
    assert by_runner["scopecat"]["trigger_count"] == 1
