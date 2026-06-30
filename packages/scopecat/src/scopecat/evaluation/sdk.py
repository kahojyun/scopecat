"""Python-level SDK for persisted Scopecat evaluation steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

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
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementRecord,
)
from scopecat.runs import open_run_store

PROPOSALS_DIR = "proposals"

__all__ = [
    "ArtifactInputDiagnostics",
    "EvaluationArtifactHandle",
    "EvaluationArtifactWriter",
    "EvaluationContext",
    "EvaluationInputArtifact",
    "EvaluationInputResolver",
    "EvaluationJob",
    "EvaluationJobArtifact",
    "EvaluationProposalHandle",
    "EvaluationProposalStore",
    "EvaluationStep",
    "EvaluationStepResult",
    "MeasurementInputDiagnostics",
    "execute_evaluation_step",
]


class EvaluationJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.evaluation_job.v1"
    id: str
    run_id: str
    step: str
    input_artifact_ids: list[str]
    input_record_refs: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    output_artifacts: list[Artifact] = Field(default_factory=list)
    status: str = "planned"
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


EvaluationArtifactHandle = StepArtifactHandle
EvaluationProposalHandle = StepArtifactHandle
EvaluationInputArtifact = StepInputArtifact
EvaluationArtifactWriter = StepArtifactWriter


class EvaluationArtifactStore(StepArtifactStore):
    """Allocates evaluation-owned artifacts without exposing storage layout."""

    def __init__(self, *, artifacts_dir: Path) -> None:
        super().__init__(
            root_dir=artifacts_dir,
            ref_dir=ARTIFACTS_DIR,
            diagnostics=StepArtifactDiagnostics(
                missing_id_code="evaluation_missing_id",
                duplicate_id_code="evaluation_duplicate_artifact",
                missing_kind_code="evaluation_missing_kind",
                invalid_filename_code="evaluation_invalid_artifact_filename",
                duplicate_filename_code="evaluation_duplicate_artifact_filename",
                noun="evaluation artifact",
                path_prefix="artifacts",
            ),
        )


class EvaluationProposalStore(StepArtifactStore):
    """Allocates evaluation-owned proposal files."""

    def __init__(self, *, proposals_dir: Path) -> None:
        super().__init__(
            root_dir=proposals_dir,
            ref_dir=PROPOSALS_DIR,
            diagnostics=StepArtifactDiagnostics(
                missing_id_code="evaluation_proposal_missing_id",
                duplicate_id_code="evaluation_proposal_duplicate_artifact",
                missing_kind_code="evaluation_proposal_missing_kind",
                invalid_filename_code="evaluation_proposal_invalid_artifact_filename",
                duplicate_filename_code=(
                    "evaluation_proposal_duplicate_artifact_filename"
                ),
                noun="evaluation proposal",
                path_prefix="proposals",
            ),
        )


class EvaluationInputResolver:
    """Resolves evaluation inputs and records job input provenance."""

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

    def record_ref(
        self,
        ref: str,
        *,
        path_escape_code: str = "evaluation_input_path_escape",
        path_escape_message: str = "evaluation input selector escapes run directory",
        diagnostic_path: str = "input",
    ) -> None:
        self._resolver.record_ref(
            ref,
            path_escape_code=path_escape_code,
            path_escape_message=path_escape_message,
            diagnostic_path=diagnostic_path,
        )

    def artifact_ref(self, *, artifact_id: str, ref: str) -> EvaluationInputArtifact:
        return self._resolver.artifact_ref(
            artifact_id=artifact_id,
            ref=ref,
            path_escape_code="evaluation_input_path_escape",
            path_escape_message="evaluation input selector escapes run directory",
            diagnostic_path="input",
        )

    def resolve_artifact(
        self,
        *,
        selector: str,
        expected_kind: str,
        diagnostics: ArtifactInputDiagnostics,
    ) -> EvaluationInputArtifact:
        return self._resolver.resolve_artifact(
            selector=selector,
            expected_kind=expected_kind,
            diagnostics=diagnostics,
        )

    def read_measurement_records(
        self,
        input_artifact: EvaluationInputArtifact,
        *,
        diagnostics: MeasurementInputDiagnostics,
    ) -> list[MeasurementRecord]:
        return self._resolver.read_measurement_records(
            input_artifact,
            diagnostics=diagnostics,
        )

    def read_measurement_dataset(
        self,
        input_artifact: EvaluationInputArtifact,
        *,
        diagnostics: MeasurementDatasetInputDiagnostics,
    ) -> MeasurementDataset:
        return self._resolver.read_measurement_dataset(
            input_artifact,
            diagnostics=diagnostics,
        )


@dataclass(frozen=True)
class EvaluationContext:
    """Typed execution context provided to evaluation steps."""

    run_id: str
    config: ConfigProfileSnapshot
    manifest: RunManifest
    plan: PlanSnapshot
    inputs: EvaluationInputResolver
    artifacts: EvaluationArtifactWriter
    proposals: EvaluationProposalStore


@dataclass(frozen=True)
class EvaluationJobArtifact(StepJobArtifact):
    """Optional manifest artifact for the evaluation job record."""

    kind: str = "evaluation_job"
    media_type: str | None = "application/json"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationStepResult[TResult, TProposal]:
    """Evaluation step result and persistence metadata."""

    result: TResult
    job_id: str
    job_ref: str
    proposals: tuple[TProposal, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    job_artifact: EvaluationJobArtifact | None = None


class EvaluationStep[TResult, TProposal](Protocol):
    """Protocol implemented by evaluation steps."""

    @property
    def step_id(self) -> str: ...

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[TResult, TProposal]: ...


def execute_evaluation_step[TResult, TProposal](
    *,
    run_id: str,
    workspace: str | Path,
    step: EvaluationStep[TResult, TProposal],
) -> tuple[EvaluationJob, TResult, tuple[TProposal, ...]]:
    """Execute an evaluation step and persist job/artifact/proposal metadata."""

    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    context = EvaluationContext(
        run_id=run_id,
        config=storage.read_config_profile_snapshot(run_id),
        manifest=manifest,
        plan=storage.read_plan_snapshot(run_id),
        inputs=EvaluationInputResolver(
            storage=storage,
            run_id=run_id,
            manifest=manifest,
        ),
        artifacts=EvaluationArtifactStore(
            artifacts_dir=storage.ref_path(run_id, ARTIFACTS_DIR),
        ),
        proposals=EvaluationProposalStore(
            proposals_dir=storage.ref_path(run_id, PROPOSALS_DIR),
        ),
    )
    try:
        step_result = step.run(context)
    except ValidationFailed as error:
        _persist_failed_evaluation_step(
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
                "evaluation_step_failed",
                f"evaluation step failed: {type(error).__name__}: {error}",
                "step",
            )
        ]
        _persist_failed_evaluation_step(
            storage=storage,
            manifest=manifest,
            run_id=run_id,
            step=step,
            context=context,
            diagnostics=diagnostics,
        )
        raise ValidationFailed(diagnostics) from error
    job = EvaluationJob(
        id=step_result.job_id,
        run_id=run_id,
        step=step.step_id,
        input_artifact_ids=list(context.inputs.input_artifact_ids),
        input_record_refs=list(context.inputs.input_record_refs),
        output_artifact_ids=[
            *context.artifacts.output_artifact_ids,
            *context.proposals.output_artifact_ids,
        ],
        output_artifacts=[*context.artifacts.artifacts, *context.proposals.artifacts],
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
        artifacts=[*context.artifacts.artifacts, *context.proposals.artifacts],
        job_artifact=step_result.job_artifact
        or EvaluationJobArtifact(id=f"{step.step_id}-job"),
    )
    return job, step_result.result, step_result.proposals


def _persist_failed_evaluation_step(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    run_id: str,
    step: EvaluationStep[Any, Any],
    context: EvaluationContext,
    diagnostics: list[Diagnostic],
) -> None:
    job_ref = f"evaluation/{step.step_id}.job.json"
    job = EvaluationJob(
        id=step.step_id,
        run_id=run_id,
        step=step.step_id,
        input_artifact_ids=list(context.inputs.input_artifact_ids),
        input_record_refs=list(context.inputs.input_record_refs),
        output_artifact_ids=[
            *context.artifacts.output_artifact_ids,
            *context.proposals.output_artifact_ids,
        ],
        output_artifacts=[*context.artifacts.artifacts, *context.proposals.artifacts],
        status="failed",
        diagnostics=diagnostics,
    )
    persist_failed_step(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref=job_ref,
        job=job,
        artifacts=[*context.artifacts.artifacts, *context.proposals.artifacts],
        job_artifact=EvaluationJobArtifact(id=f"{step.step_id}-job"),
    )


def _diagnostic(code: str, message: str, path: str | None) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)
