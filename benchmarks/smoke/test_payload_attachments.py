from __future__ import annotations

import json
import subprocess
import sys
from typing import cast


def test_payload_attachment_benchmark_preserves_separate_immutable_arrays() -> None:
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "benchmarks",
            "run",
            "payload-attachments",
            "--arrays",
            "32",
            "--samples",
            "128",
            "--iterations",
            "2",
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
    assert result["case_id"] == "payload-attachments"
    assert result["case_version"] == 1
    assert result["kind"] == "micro"
    assert result["array_count"] == 32
    assert result["attachment_count"] == 32
    assert result["attachment_bytes"] == 32 * 128 * 8
    assert result["decoded_immutable_count"] == 32
    assert result["decoded_shared_attachment_count"] == 32
