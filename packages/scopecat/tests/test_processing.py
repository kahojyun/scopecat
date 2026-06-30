from __future__ import annotations

from pathlib import Path

from scopecat.models.artifact import ProcessingJob
from scopecat.processing.sdk import execute_processing_step
from scopecat.runs import open_run_store
from tests.support.processing import (
    FakeProcessingResult,
    FakeProcessingStep,
    make_simulated_run,
)
from tests.support.records import (
    assert_artifact_ref,
    read_measurement_records,
    read_model,
    require_artifact,
)
from tests.support.signal_testkit import (
    SUMMARY_STATS_JOB_REF,
    SUMMARY_STATS_RESULT_REF,
    SUMMARY_STATS_SUMMARY_REF,
    SummaryStatsResult,
    execute_summary_stats_processing,
)


def test_execute_summary_stats_processing_updates_manifest(
    tmp_path: Path,
) -> None:
    run_id = make_simulated_run(tmp_path)

    job, result = execute_summary_stats_processing(run_id=run_id, workspace=tmp_path)

    run_dir = tmp_path / "runs" / run_id
    assert (run_dir / "processing" / "summary-stats.job.json").is_file()
    assert (run_dir / "artifacts" / "summary-stats.json").is_file()
    assert (run_dir / "artifacts" / "summary-stats.md").is_file()
    assert job.status == "completed"
    assert result.measurement_count == 3
    assert result.observables["signal"].count == 3
    assert result.observables["signal"].min == 0.5
    assert result.observables["signal"].max == 1.0
    assert result.observables["signal"].mean == 0.666666666667
    assert result.observables["signal"].unit == "ratio"
    persisted_job = read_model(run_dir / SUMMARY_STATS_JOB_REF, ProcessingJob)
    persisted_result = read_model(
        run_dir / SUMMARY_STATS_RESULT_REF,
        SummaryStatsResult,
    )
    assert persisted_job == job
    assert persisted_result == result

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert manifest.status == "completed"
    assert_artifact_ref(
        manifest.artifact_refs,
        "summary-stats-result",
        kind="test_summary_stats_result",
        path=SUMMARY_STATS_RESULT_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "summary-stats-summary",
        kind="summary",
        path=SUMMARY_STATS_SUMMARY_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "summary-stats-job",
        kind="processing_job",
        path=SUMMARY_STATS_JOB_REF,
    )


def test_processing_sdk_persists_job_outputs_and_manifest_artifacts(
    tmp_path: Path,
) -> None:
    run_id = make_simulated_run(tmp_path)

    job, result = execute_processing_step(
        run_id=run_id,
        workspace=tmp_path,
        step=FakeProcessingStep(),
    )

    run_dir = tmp_path / "runs" / run_id
    assert result.measurement_count == 3
    assert job.input_artifact_ids == ["raw-measurements"]
    assert job.input_record_refs == []
    assert job.output_artifact_ids == [
        "fake-processing-result",
        "fake-processing-summary",
        "fake-processing-sample",
        "fake-processing-figure",
        "fake-processing-reserved",
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path) for artifact in job.output_artifacts
    ] == [
        (
            "fake-processing-result",
            "fake_result",
            "artifacts/fake-result.json",
        ),
        ("fake-processing-summary", "summary", "artifacts/fake-summary.md"),
        (
            "fake-processing-sample",
            "measurement_dataset",
            "artifacts/fake-sample.jsonl",
        ),
        ("fake-processing-figure", "plot", "artifacts/fake-figure.png"),
        ("fake-processing-reserved", "log", "artifacts/fake-reserved.txt"),
    ]
    assert (run_dir / "artifacts" / "fake-summary.md").is_file()
    assert (run_dir / "artifacts" / "fake-figure.png").read_bytes() == b"\x89PNG\r\n"
    assert (run_dir / "artifacts" / "fake-reserved.txt").read_text() == "reserved\n"
    persisted_job = read_model(
        run_dir / "processing" / "fake-processing.job.json",
        ProcessingJob,
    )
    persisted_result = read_model(
        run_dir / "artifacts" / "fake-result.json",
        FakeProcessingResult,
    )
    persisted_sample = read_measurement_records(
        run_dir / "artifacts" / "fake-sample.jsonl"
    )
    assert persisted_job == job
    assert persisted_result == result
    assert len(persisted_sample) == 1
    assert persisted_sample[0].observables["signal"].unit == "ratio"

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert {artifact.id for artifact in manifest.artifact_refs} >= {
        "fake-processing-result",
        "fake-processing-summary",
        "fake-processing-sample",
        "fake-processing-figure",
        "fake-processing-reserved",
        "fake-processing-job",
    }
    sample_artifact = require_artifact(manifest.artifact_refs, "fake-processing-sample")
    sample_metadata = sample_artifact.metadata
    assert sample_metadata["dataset_role"] == "derived"
    assert sample_metadata["record_schema"] == "scopecat.measurement_record.v0"
    assert sample_metadata["source_step"] == "fake-processing"
    assert sample_metadata["source_artifact_ids"] == ["raw-measurements"]
    assert sample_metadata["dataset_schema"]["dataset_id"] == "fake-processing-sample"
    assert sample_metadata["dataset_schema"]["primary_coordinates"] == [
        "drive_frequency"
    ]
    assert sample_metadata["dataset_schema"]["primary_observables"] == ["signal"]
