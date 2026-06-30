"""Python-level SDK for persisted Scopecat processing steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from scopecat._steps import (
    ArtifactInputDiagnostics,
    MeasurementInputDiagnostics,
    StepArtifactDiagnostics,
    StepArtifactHandle,
    StepArtifactStore,
    StepArtifactWriter,
    StepInputArtifact,
    StepInputResolver,
    StepJobArtifact,
    persist_completed_step,
    persist_failed_step,
)
from scopecat._storage import ARTIFACTS_DIR
from scopecat._storage.local import LocalRunStore
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.experiments import PlanSnapshot
from scopecat.models.artifact import ProcessingJob
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementRecord,
)
from scopecat.runs import open_run_store

__all__ = [
    "ArtifactInputDiagnostics",
    "MeasurementInputDiagnostics",
    "ProcessingArtifactHandle",
    "ProcessingArtifactWriter",
    "ProcessingContext",
    "ProcessingInputArtifact",
    "ProcessingInputResolver",
    "ProcessingJobArtifact",
    "ProcessingStep",
    "ProcessingStepResult",
    "execute_processing_step",
]

ProcessingArtifactHandle = StepArtifactHandle
ProcessingArtifactWriter = StepArtifactWriter
ProcessingInputArtifact = StepInputArtifact


class ProcessingArtifactStore(StepArtifactStore):
    """Allocates processing-owned artifacts without exposing storage layout."""

    def __init__(self, *, artifacts_dir: Path) -> None:
        super().__init__(
            root_dir=artifacts_dir,
            ref_dir=ARTIFACTS_DIR,
            diagnostics=StepArtifactDiagnostics(
                missing_id_code="processing_artifact_missing_id",
                duplicate_id_code="processing_duplicate_artifact",
                missing_kind_code="processing_artifact_missing_kind",
                invalid_filename_code="processing_invalid_artifact_filename",
                duplicate_filename_code="processing_duplicate_artifact_filename",
                noun="processing artifact",
                path_prefix="artifacts",
            ),
        )


class ProcessingInputResolver:
    """Resolves processing inputs and records job input provenance."""

    def __init__(
        self, *, storage: LocalRunStore, run_id: str, manifest: RunManifest
    ) -> None:
        self._resolver = StepInputResolver(
            storage=storage,
            run_id=run_id,
            manifest=manifest,
        )

    @property
    def input_artifact_ids(self) -> tuple[str, ...]:
        return self._resolver.input_artifact_ids

    @property
    def input_record_refs(self) -> tuple[str, ...]:
        return self._resolver.input_record_refs

    def artifact_ref(self, *, artifact_id: str, ref: str) -> ProcessingInputArtifact:
        return self._resolver.artifact_ref(
            artifact_id=artifact_id,
            ref=ref,
            path_escape_code="processing_input_path_escape",
            path_escape_message="processing input selector escapes run directory",
            diagnostic_path="input",
        )

    def resolve_artifact(
        self,
        *,
        selector: str,
        expected_kind: str,
        diagnostics: ArtifactInputDiagnostics,
    ) -> ProcessingInputArtifact:
        return self._resolver.resolve_artifact(
            selector=selector,
            expected_kind=expected_kind,
            diagnostics=diagnostics,
        )

    def read_measurement_records(
        self,
        input_artifact: ProcessingInputArtifact,
        *,
        diagnostics: MeasurementInputDiagnostics,
    ) -> list[MeasurementRecord]:
        return self._resolver.read_measurement_records(
            input_artifact,
            diagnostics=diagnostics,
        )

    def read_measurement_dataset(
        self,
        input_artifact: ProcessingInputArtifact,
        *,
        diagnostics: MeasurementDatasetInputDiagnostics,
    ) -> MeasurementDataset:
        return self._resolver.read_measurement_dataset(
            input_artifact,
            diagnostics=diagnostics,
        )


@dataclass(frozen=True)
class ProcessingContext:
    """Typed execution context provided to processing steps."""

    run_id: str
    config: ConfigProfileSnapshot
    manifest: RunManifest
    plan: PlanSnapshot
    inputs: ProcessingInputResolver
    artifacts: ProcessingArtifactWriter


@dataclass(frozen=True)
class ProcessingJobArtifact(StepJobArtifact):
    """Optional manifest artifact for the processing job record."""

    kind: str = "processing_job"
    media_type: str | None = "application/json"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessingStepResult[TResult]:
    """Processing step result and persistence metadata."""

    result: TResult
    job_id: str
    job_ref: str
    diagnostics: tuple[Diagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    job_artifact: ProcessingJobArtifact | None = None


class ProcessingStep[TResult](Protocol):
    """Protocol implemented by processing steps."""

    @property
    def step_id(self) -> str: ...

    def run(
        self,
        context: ProcessingContext,
    ) -> ProcessingStepResult[TResult]: ...


def execute_processing_step[TResult](
    *,
    run_id: str,
    workspace: str | Path,
    step: ProcessingStep[TResult],
) -> tuple[ProcessingJob, TResult]:
    """Execute a processing step and persist job/artifact metadata."""

    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    context = ProcessingContext(
        run_id=run_id,
        config=storage.read_config_profile_snapshot(run_id),
        manifest=manifest,
        plan=storage.read_plan_snapshot(run_id),
        inputs=ProcessingInputResolver(
            storage=storage,
            run_id=run_id,
            manifest=manifest,
        ),
        artifacts=ProcessingArtifactStore(
            artifacts_dir=storage.ref_path(run_id, ARTIFACTS_DIR),
        ),
    )
    try:
        step_result = step.run(context)
    except ValidationFailed as error:
        _persist_failed_processing_step(
            storage=storage,
            manifest=manifest,
            run_id=run_id,
            step=step,
            context=context,
            diagnostics=error.diagnostics,
        )
        raise
    except Exception as error:
        diagnostics = [
            _diagnostic(
                "processing_step_failed",
                f"processing step failed: {type(error).__name__}: {error}",
                "step",
            )
        ]
        _persist_failed_processing_step(
            storage=storage,
            manifest=manifest,
            run_id=run_id,
            step=step,
            context=context,
            diagnostics=diagnostics,
        )
        raise ValidationFailed(diagnostics) from error
    job = ProcessingJob(
        id=step_result.job_id,
        run_id=run_id,
        step=step.step_id,
        input_artifact_ids=list(context.inputs.input_artifact_ids),
        input_record_refs=list(context.inputs.input_record_refs),
        output_artifact_ids=list(context.artifacts.output_artifact_ids),
        output_artifacts=list(context.artifacts.artifacts),
        status="completed",
        diagnostics=list(step_result.diagnostics),
        metadata=step_result.metadata,
    )
    persist_completed_step(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref=step_result.job_ref,
        job=job,
        artifacts=context.artifacts.artifacts,
        job_artifact=step_result.job_artifact
        or ProcessingJobArtifact(id=f"{step.step_id}-job"),
    )
    return job, step_result.result


def _persist_failed_processing_step(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    run_id: str,
    step: ProcessingStep[Any],
    context: ProcessingContext,
    diagnostics: list[Diagnostic],
) -> None:
    job_ref = f"processing/{step.step_id}.job.json"
    job = ProcessingJob(
        id=step.step_id,
        run_id=run_id,
        step=step.step_id,
        input_artifact_ids=list(context.inputs.input_artifact_ids),
        input_record_refs=list(context.inputs.input_record_refs),
        output_artifact_ids=list(context.artifacts.output_artifact_ids),
        output_artifacts=list(context.artifacts.artifacts),
        status="failed",
        diagnostics=diagnostics,
    )
    persist_failed_step(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref=job_ref,
        job=job,
        artifacts=context.artifacts.artifacts,
        job_artifact=ProcessingJobArtifact(id=f"{step.step_id}-job"),
    )


def _diagnostic(code: str, message: str, path: str | None) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)
