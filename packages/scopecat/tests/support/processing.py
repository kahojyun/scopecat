from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from scopecat.experiments import ExperimentSpec
from scopecat.models.artifact import ProcessingJob
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.run import RunManifest
from scopecat.processing.sdk import (
    ArtifactInputDiagnostics,
    ProcessingContext,
    ProcessingJobArtifact,
    ProcessingStepResult,
)
from scopecat.results import MeasurementDatasetInputDiagnostics
from scopecat.runs import open_run_store
from tests.support.records import assert_artifact_ref, read_model
from tests.support.signal_testkit import execute_signal_native_run

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


class FakeProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    measurement_count: int


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def make_simulated_run(tmp_path: Path) -> str:
    manifest, _simulated_run = execute_signal_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    return manifest.run_id


@dataclass(frozen=True)
class FakeProcessingStep:
    step_id: str = "fake-processing"

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[FakeProcessingResult]:
        source = context.inputs.resolve_artifact(
            selector="raw-measurements",
            expected_kind="measurement_dataset",
            diagnostics=ArtifactInputDiagnostics(
                not_found_code="fake_input_not_found",
                invalid_kind_code="fake_input_invalid_kind",
                path_escape_code="fake_input_path_escape",
                not_found_message="fake processing input artifact not found",
                invalid_kind_message=(
                    "fake processing input must be measurement_dataset"
                ),
                path_escape_message=(
                    "fake processing input selector escapes run directory"
                ),
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            source,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="fake_input_missing",
                empty_code="fake_input_empty",
                invalid_code="fake_input_invalid",
                missing_schema_code="fake_input_missing_schema",
                invalid_schema_code="fake_input_invalid_schema",
                noun="fake processing input",
            ),
        )
        measurements = dataset.records
        result = FakeProcessingResult(
            run_id=context.run_id,
            measurement_count=len(measurements),
        )
        context.artifacts.write_model(
            id="fake-processing-result",
            kind="fake_result",
            filename="fake-result.json",
            model=result,
        )
        context.artifacts.write_text(
            id="fake-processing-summary",
            kind="summary",
            filename="fake-summary.md",
            content="# Fake\n",
            media_type="text/markdown",
        )
        sample_measurements = measurements[:1]
        context.artifacts.write_measurement_dataset(
            id="fake-processing-sample",
            filename="fake-sample.jsonl",
            dataset_role="derived",
            records=sample_measurements,
            source_step=self.step_id,
            source_artifact_ids=[source.artifact_id],
        )
        context.artifacts.write_bytes(
            id="fake-processing-figure",
            kind="plot",
            filename="fake-figure.png",
            content=b"\x89PNG\r\n",
            media_type="image/png",
        )
        reserved = context.artifacts.reserve_file(
            id="fake-processing-reserved",
            kind="log",
            filename="fake-reserved.txt",
            media_type="text/plain",
        )
        reserved.path.write_text("reserved\n")
        return ProcessingStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="processing/fake-processing.job.json",
            job_artifact=ProcessingJobArtifact(id="fake-processing-job"),
        )


@dataclass(frozen=True)
class InvalidFilenameProcessingStep:
    step_id: str = "invalid-filename-processing"

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[FakeProcessingResult]:
        result = FakeProcessingResult(run_id=context.run_id, measurement_count=0)
        context.artifacts.write_text(
            id="invalid-filename-result",
            kind="summary",
            filename="../bad.md",
            content="bad",
        )
        return ProcessingStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="processing/invalid-filename-processing.job.json",
        )


@dataclass(frozen=True)
class DuplicateIdProcessingStep:
    step_id: str = "duplicate-id-processing"

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[FakeProcessingResult]:
        result = FakeProcessingResult(run_id=context.run_id, measurement_count=0)
        context.artifacts.write_text(
            id="duplicate-result",
            kind="summary",
            filename="duplicate-a.md",
            content="a",
        )
        context.artifacts.write_text(
            id="duplicate-result",
            kind="summary",
            filename="duplicate-b.md",
            content="b",
        )
        return ProcessingStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="processing/duplicate-id-processing.job.json",
        )


@dataclass(frozen=True)
class DuplicateFilenameProcessingStep:
    step_id: str = "duplicate-filename-processing"

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[FakeProcessingResult]:
        result = FakeProcessingResult(run_id=context.run_id, measurement_count=0)
        context.artifacts.write_text(
            id="duplicate-filename-a",
            kind="summary",
            filename="duplicate.md",
            content="a",
        )
        context.artifacts.write_text(
            id="duplicate-filename-b",
            kind="summary",
            filename="duplicate.md",
            content="b",
        )
        return ProcessingStepResult(
            result=result,
            job_id=self.step_id,
            job_ref="processing/duplicate-filename-processing.job.json",
        )


@dataclass(frozen=True)
class UnexpectedProcessingFailureStep:
    step_id: str = "unexpected-processing"

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[FakeProcessingResult]:
        context.artifacts.write_text(
            id="unexpected-partial",
            kind="summary",
            filename="unexpected-partial.md",
            content="partial",
        )
        raise RuntimeError("boom")


def assert_failed_processing_job(
    tmp_path: Path,
    run_id: str,
    *,
    step_id: str,
    diagnostic_code: str,
) -> tuple[ProcessingJob, RunManifest]:
    job_ref = f"processing/{step_id}.job.json"
    job_path = tmp_path / "runs" / run_id / job_ref
    assert job_path.is_file()
    job = read_model(job_path, ProcessingJob)
    assert job.id == step_id
    assert job.step == step_id
    assert job.status == "failed"
    assert [diagnostic.code for diagnostic in job.diagnostics] == [diagnostic_code]
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        f"{step_id}-job",
        kind="processing_job",
        path=job_ref,
    )
    return job, manifest
