from __future__ import annotations

import json
import subprocess
import sys
from typing import cast


def test_inspection_index_materializes_only_indexed_filter_matches() -> None:
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "benchmarks",
            "run",
            "inspection-index",
            "--nodes",
            "10000",
            "--page-size",
            "32",
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("BENCHMARK_RESULT=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("BENCHMARK_RESULT=")),
    )
    assert result["schema"] == "scopecat.benchmark_result.v1"
    assert result["case_id"] == "inspection-index"
    assert result["case_version"] == 1
    assert result["kind"] == "micro"
    assert result["node_count"] == 10_000
    assert result["exact_matching_count"] == 1
    assert result["exact_returned_count"] == 1
    assert cast("int", result["exact_response_bytes"]) <= 4 * 1024
    assert result["filter_matching_count"] == 156
    assert result["filter_returned_count"] == 32
    assert result["filter_materialized_node_count"] == 156
    assert cast("int", result["filter_response_bytes"]) <= 32 * 1024
