from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import cast


def test_scan_execution_benchmark_runs_all_execution_boundaries(tmp_path: Path) -> None:
    output = tmp_path / "results.jsonl"
    script = Path(__file__).parents[3] / "scripts" / "benchmark_scan_execution.py"

    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--points",
            "3",
            "--runners",
            "adhoc,scopecat-core,scopecat",
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
    assert set(by_runner) == {"adhoc", "scopecat-core", "scopecat"}
    assert all(result["points_completed"] == 3 for result in results)
    assert by_runner["adhoc"]["trigger_count"] == 3
    assert by_runner["scopecat-core"]["trigger_count"] == 2
    assert by_runner["scopecat"]["trigger_count"] == 2


def test_scopecat_benchmark_batches_measurement_appends(tmp_path: Path) -> None:
    script = Path(__file__).parents[3] / "scripts" / "benchmark_scan_execution.py"
    work_dir = tmp_path / "scopecat-worker"

    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--worker",
            "scopecat",
            "--point-count",
            "257",
            "--profile",
            "waveform",
            "--waveform-samples",
            "128",
            "--qubits",
            "2",
            "--host-label",
            "test",
            "--work-dir",
            str(work_dir),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    database = next(work_dir.rglob("control.sqlite3"))
    with sqlite3.connect(database) as connection:
        append_ranges = connection.execute(
            """
            SELECT start_index, record_count
            FROM execution_measurement_appends
            ORDER BY start_index
            """
        ).fetchall()
    assert append_ranges == [(0, 256), (256, 1)]
    object_root = work_dir / ".scopecat" / "objects"
    object_bytes = sum(
        path.stat().st_size for path in object_root.rglob("*") if path.is_file()
    )
    total_waveform_bytes = 257 * 6 * 128 * 8
    assert object_bytes < total_waveform_bytes // 2
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("SCAN_BENCHMARK_RESULT=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("SCAN_BENCHMARK_RESULT=")),
    )
    assert result["payload_spool_bytes_at_finish"] == 0
    peak_spool_bytes = cast("int", result["peak_payload_spool_bytes"])
    max_batch_bytes = cast("int", result["max_waveform_batch_bytes"])
    assert peak_spool_bytes > 0
    assert peak_spool_bytes <= 2 * max_batch_bytes


def test_waveform_profile_matches_multichannel_working_set(tmp_path: Path) -> None:
    output = tmp_path / "waveform-results.jsonl"
    script = Path(__file__).parents[3] / "scripts" / "benchmark_scan_execution.py"

    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--profile",
            "waveform",
            "--points",
            "3",
            "--waveform-samples",
            "128",
            "--qubits",
            "2",
            "--live-waveform",
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
    expected_total_bytes = 3 * 6 * 128 * 8
    expected_retained_bytes = 6 * 128 * 8
    assert all(
        result["schema"] == "scopecat.scan_execution_benchmark.v4" for result in results
    )
    assert all(
        result["waveform_bytes_uploaded"] == expected_total_bytes for result in results
    )
    assert all(
        result["live_waveform_bytes_retained"] == expected_retained_bytes
        for result in results
    )
    by_runner = {result["runner"]: result for result in results}
    assert by_runner["adhoc"]["max_waveform_batch_bytes"] == expected_retained_bytes
    assert (
        by_runner["scopecat"]["max_waveform_batch_bytes"] == 2 * expected_retained_bytes
    )
