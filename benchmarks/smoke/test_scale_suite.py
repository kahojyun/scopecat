# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

from benchmarks.e2e.scale_suite import (
    SCALE_PROFILES,
    acceptance_checks,
    scale_profile,
    selected_profiles,
)
from benchmarks.e2e.scan_execution import ScanScenario, _benchmark_config


def test_named_scale_profiles_have_memorable_width_and_distinct_pressure() -> None:
    assert [profile.id for profile in SCALE_PROFILES] == [
        "smoke",
        "small",
        "medium",
        "full",
        "endurance",
    ]
    assert [profile.qubit_count for profile in SCALE_PROFILES] == [1, 4, 16, 64, 64]
    assert selected_profiles(profiles=None, through="medium") == SCALE_PROFILES[:3]
    assert selected_profiles(profiles="full,endurance", through=None) == (
        scale_profile("full"),
        scale_profile("endurance"),
    )
    assert scale_profile("full").total_waveform_bytes == (
        scale_profile("endurance").total_waveform_bytes
    )
    assert scale_profile("full").entry_waveform_bytes > (
        scale_profile("endurance").entry_waveform_bytes
    )


def test_acceptance_checks_require_complete_buffers_and_bounded_retention() -> None:
    profile = scale_profile("smoke")
    entry_bytes = profile.entry_waveform_bytes
    measurement: dict[str, object] = {
        "points_completed": 1,
        "waveform_bytes_rendered": entry_bytes,
        "waveform_bytes_uploaded": entry_bytes,
        "live_waveform_bytes_retained": entry_bytes,
        "max_waveform_batch_bytes": entry_bytes,
        "trigger_count": 1,
        "payload_spool_bytes_at_finish": 0,
        "peak_payload_spool_bytes": entry_bytes,
        "peak_rss_bytes": 400,
        "host": {"physical_memory_bytes": 1_000},
    }

    passing = acceptance_checks(
        profile,
        (measurement,),
        max_memory_fraction=0.75,
    )
    assert all(check.passed for check in passing)

    failing_measurement = {**measurement, "waveform_bytes_uploaded": entry_bytes - 8}
    failing = acceptance_checks(
        profile,
        (failing_measurement,),
        max_memory_fraction=0.75,
    )
    by_id = {check.id: check for check in failing}
    assert by_id["complete-waveforms-uploaded"].passed is False


def test_full_profile_uses_bounded_physical_awg_banks() -> None:
    profile = scale_profile("full")
    scenario = ScanScenario(
        point_count=profile.point_count,
        profile="multichannel_waveform_integrated_iq",
        waveform_sample_count=profile.waveform_sample_count,
        qubit_count=profile.qubit_count,
        physical_channel_count=profile.physical_channel_count,
    )

    config = _benchmark_config(scenario)
    drive_awgs = [
        instrument
        for instrument in config.system.instrument_registry.instruments
        if instrument.id == "drive-awg" or instrument.id.startswith("drive-awg-")
    ]
    target = config.domain_target
    assert target is not None
    assert [instrument.id for instrument in drive_awgs] == [
        "drive-awg",
        "drive-awg-1",
        "drive-awg-2",
        "drive-awg-3",
    ]
    assert all(
        cast("int", instrument.connection.options["output_count"]) <= 33
        for instrument in drive_awgs
    )
    assert all(instrument.id in target.instrument_ids for instrument in drive_awgs)


def test_scale_suite_smoke_profile_runs_the_production_boundary(tmp_path: Path) -> None:
    output = tmp_path / "scale-suite.jsonl"
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            "-m",
            "benchmarks",
            "run",
            "scale-suite",
            "--profiles",
            "smoke",
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
    [record] = [
        cast("dict[str, object]", json.loads(line))
        for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert record["case_id"] == "scale-suite"
    assert record["case_version"] == 2
    assert record["mode"] == "acceptance"
    assert record["runner"] == "scopecat-deployed"
    assert record["passed"] is True
    assert cast("dict[str, object]", record["profile"])["id"] == "smoke"
    [measurement] = cast("list[dict[str, object]]", record["measurements"])
    assert measurement["runner"] == "scopecat-deployed"
    deployment = cast("dict[str, object]", measurement["deployment"])
    assert cast("int", deployment["daemon_peak_rss_bytes"]) > 0
    assert cast("int", deployment["instrument_peak_rss_bytes"]) > 0
    assert measurement["peak_rss_bytes"] == deployment["combined_peak_rss_bytes"]
    assert measurement["payload_spool_bytes_at_finish"] == 0
    assert cast("int", measurement["peak_payload_spool_bytes"]) > 0
    assert all(
        cast("bool", check["passed"])
        for check in cast("list[dict[str, object]]", record["checks"])
    )


def test_64_qubit_synthetic_target_uploads_complete_waveforms(tmp_path: Path) -> None:
    work_dir = tmp_path / "q64-worker"
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            "-m",
            "benchmarks",
            "run",
            "scan-execution",
            "--worker",
            "scopecat",
            "--point-count",
            "1",
            "--qubit-count",
            "64",
            "--profile",
            "waveform",
            "--waveform-samples",
            "32",
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
        if line.startswith("BENCHMARK_RESULT=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("BENCHMARK_RESULT=")),
    )
    expected_bytes = (2 * 64 + 2) * 32 * 8
    assert result["points_completed"] == 1
    assert result["waveform_bytes_rendered"] == expected_bytes
    assert result["waveform_bytes_uploaded"] == expected_bytes
    assert result["payload_spool_bytes_at_finish"] == 0
