from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.processing.sdk import execute_processing_step
from tests.support.processing import (
    InvalidFilenameProcessingStep,
    UnexpectedProcessingFailureStep,
    assert_failed_processing_job,
    make_simulated_run,
)
from tests.support.records import read_measurement_records
from tests.support.signal_testkit import execute_summary_stats_processing


def test_processing_sdk_rejects_invalid_artifact_filename(tmp_path: Path) -> None:
    run_id = make_simulated_run(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_processing_step(
            run_id=run_id,
            workspace=tmp_path,
            step=InvalidFilenameProcessingStep(),
        )

    assert error.value.diagnostics[0].code == "processing_invalid_artifact_filename"
    job, _manifest = assert_failed_processing_job(
        tmp_path,
        run_id,
        step_id="invalid-filename-processing",
        diagnostic_code="processing_invalid_artifact_filename",
    )
    assert job.output_artifact_ids == []


def test_summary_stats_missing_input_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = make_simulated_run(tmp_path)
    (tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl").unlink()

    with pytest.raises(ValidationFailed) as error:
        execute_summary_stats_processing(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_processing_input"
    job, _manifest = assert_failed_processing_job(
        tmp_path,
        run_id,
        step_id="summary-stats",
        diagnostic_code="missing_processing_input",
    )
    assert job.input_artifact_ids == ["raw-measurements"]
    assert job.input_record_refs == []
    assert job.output_artifact_ids == []


def test_summary_stats_missing_observables_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = make_simulated_run(tmp_path)
    data_path = tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl"
    measurement = read_measurement_records(data_path)[0].model_dump(mode="json")
    measurement["observables"] = {}
    data_path.write_text(json.dumps(measurement) + "\n")

    with pytest.raises(ValidationFailed) as error:
        execute_summary_stats_processing(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_processing_input_schema"
    assert_failed_processing_job(
        tmp_path,
        run_id,
        step_id="summary-stats",
        diagnostic_code="invalid_processing_input_schema",
    )


def test_processing_sdk_persists_unexpected_exception_as_failed_job(
    tmp_path: Path,
) -> None:
    run_id = make_simulated_run(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_processing_step(
            run_id=run_id,
            workspace=tmp_path,
            step=UnexpectedProcessingFailureStep(),
        )

    assert error.value.diagnostics[0].code == "processing_step_failed"
    job, manifest = assert_failed_processing_job(
        tmp_path,
        run_id,
        step_id="unexpected-processing",
        diagnostic_code="processing_step_failed",
    )
    assert job.output_artifact_ids == ["unexpected-partial"]
    assert {artifact.id for artifact in manifest.artifact_refs} >= {
        "unexpected-partial",
        "unexpected-processing-job",
    }
