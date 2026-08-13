from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import cast


def test_scan_execution_benchmark_runs_all_boundaries_with_waveforms(
    tmp_path: Path,
) -> None:
    output = tmp_path / "results.jsonl"
    script = Path(__file__).parents[1] / "scripts" / "benchmark_scan_execution.py"

    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--points",
            "3",
            "--profile",
            "waveform",
            "--waveform-samples",
            "128",
            "--qubits",
            "2",
            "--live-waveform",
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
    expected_total_bytes = 3 * 6 * 128 * 8
    expected_retained_bytes = 6 * 128 * 8
    assert all(
        result["schema"] == "scopecat.scan_execution_benchmark.v5" for result in results
    )
    assert all(
        result["waveform_bytes_uploaded"] == expected_total_bytes for result in results
    )
    assert all(
        result["live_waveform_bytes_retained"] == expected_retained_bytes
        for result in results
    )
    assert by_runner["adhoc"]["max_waveform_batch_bytes"] == expected_retained_bytes
    scopecat_batch_bytes = cast(
        "int", by_runner["scopecat"]["max_waveform_batch_bytes"]
    )
    assert expected_retained_bytes <= scopecat_batch_bytes
    assert scopecat_batch_bytes <= 2 * expected_retained_bytes


def test_scopecat_benchmark_batches_measurement_appends(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_scan_execution.py"
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
        append_ranges = cast(
            "list[tuple[int, int]]",
            connection.execute(
                """
                SELECT start_index, record_count
                FROM execution_measurement_appends
                ORDER BY start_index
                """
            ).fetchall(),
        )
    assert len(append_ranges) > 1
    next_start = 0
    for start_index, record_count in append_ranges:
        assert start_index == next_start
        assert 0 < record_count <= 256
        next_start += record_count
    assert next_start == 257
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


def test_result_retention_profile_separates_selected_data_from_control(
    tmp_path: Path,
) -> None:
    discarded = _result_worker(
        tmp_path,
        runner="adhoc",
        retention="discard",
        shots=8,
    )
    summary_small = _result_worker(
        tmp_path,
        runner="scopecat",
        retention="summary",
        shots=8,
    )
    summary_large = _result_worker(
        tmp_path,
        runner="scopecat",
        retention="summary",
        shots=64,
    )
    iq_and_bits = _result_worker(
        tmp_path,
        runner="scopecat",
        retention="iq-and-bits",
        shots=64,
    )

    assert discarded["selected_result_bytes"] == 0
    assert discarded["measurement_dataset_bytes"] == 0
    assert discarded["durable_bytes"] == 0
    assert summary_small["acquired_result_bytes"] == 512
    assert summary_large["acquired_result_bytes"] == 4096
    assert summary_small["selected_result_bytes"] == 32
    assert summary_large["selected_result_bytes"] == 32
    assert cast("int", summary_large["measurement_dataset_bytes"]) < (
        cast("int", summary_small["measurement_dataset_bytes"]) + 1024
    )

    assert iq_and_bits["selected_result_bytes"] == 4128
    assert cast("int", iq_and_bits["measurement_dataset_bytes"]) > cast(
        "int", summary_large["measurement_dataset_bytes"]
    )
    for result in (summary_small, summary_large, iq_and_bits):
        assert result["points_completed"] == 2
        assert result["durable_bytes"] == (
            cast("int", result["measurement_dataset_bytes"])
            + cast("int", result["control_and_provenance_bytes"])
        )


def _result_worker(
    tmp_path: Path,
    *,
    runner: str,
    retention: str,
    shots: int,
) -> dict[str, object]:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_scan_execution.py"
    work_dir = tmp_path / f"{runner}-{retention}-{shots}"
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--worker",
            runner,
            "--point-count",
            "2",
            "--profile",
            "results",
            "--retention",
            retention,
            "--shots",
            str(shots),
            "--waveform-samples",
            "72",
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
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("SCAN_BENCHMARK_RESULT=")
    )
    return cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("SCAN_BENCHMARK_RESULT=")),
    )
