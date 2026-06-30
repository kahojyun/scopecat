"""Evaluation for readout-frequency calibration S21 scans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.evaluation import (
    ArtifactInputDiagnostics,
    EvaluationContext,
    EvaluationJob,
    EvaluationJobArtifact,
    EvaluationStepResult,
    execute_evaluation_step,
)
from scopecat.models.parameter import (
    ParameterChangeSet,
    ParameterPatch,
    Quantity,
)
from scopecat.results import MeasurementDatasetInputDiagnostics, MeasurementRecord

from quantum_lab_demo.readout.frequency_processing import (
    MEASUREMENT_DATASET_ARTIFACT_KIND,
    PROCESSED_DATA_ARTIFACT_ID,
)

READOUT_EVALUATION_STEP = "readout-frr-min-s21"
READOUT_PARAMETER_ID = "readout_frequency"
CONFIG_SNAPSHOT_REF = "config.snapshot.json"
READOUT_EVALUATION_RESULT_REF = "artifacts/readout-frr-min-s21-evaluation.json"
READOUT_EVALUATION_SUMMARY_REF = "artifacts/readout-frr-min-s21-evaluation.md"
READOUT_EVALUATION_JOB_REF = "evaluation/readout-frr-min-s21.job.json"
READOUT_RESONATOR_PROPOSAL_REF = (
    "proposals/readout-frr-resonator-frequency-proposal.json"
)
READOUT_EVALUATION_RESULT_ARTIFACT_ID = "readout-frr-min-s21-evaluation-result"
READOUT_EVALUATION_SUMMARY_ARTIFACT_ID = "readout-frr-min-s21-evaluation-summary"
READOUT_EVALUATION_JOB_ARTIFACT_ID = "readout-frr-min-s21-evaluation-job"
READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID = "readout-frr-resonator-frequency-proposal"


class ReadoutFrequencyEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "quantum_lab_demo.readout_frequency_evaluation_result.v0"
    run_id: str
    step: str = READOUT_EVALUATION_STEP
    input_ref: str
    proposal_artifact_id: str = READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID
    parameter_id: str
    best_point_index: int
    minimum_s21: Quantity
    old_value: Quantity
    proposed_value: Quantity
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def execute_readout_frequency_evaluation(
    *, run_id: str, workspace: str | Path
) -> tuple[EvaluationJob, ReadoutFrequencyEvaluationResult, ParameterChangeSet]:
    job, result, proposals = execute_evaluation_step(
        run_id=run_id,
        workspace=workspace,
        step=ReadoutFrequencyEvaluationStep(),
    )
    return job, result, proposals[0]


@dataclass(frozen=True)
class ReadoutFrequencyEvaluationStep:
    step_id: str = READOUT_EVALUATION_STEP

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[
        ReadoutFrequencyEvaluationResult,
        ParameterChangeSet,
    ]:
        input_artifact = context.inputs.resolve_artifact(
            selector=PROCESSED_DATA_ARTIFACT_ID,
            expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            diagnostics=ArtifactInputDiagnostics(
                not_found_code="readout_evaluation_input_not_found",
                invalid_kind_code="readout_evaluation_input_kind_unsupported",
                path_escape_code="readout_evaluation_input_path_escape",
                not_found_message="readout evaluation input artifact not found",
                invalid_kind_message=(
                    "readout evaluation supports measurement_dataset only"
                ),
                path_escape_message=(
                    "readout evaluation input selector escapes run directory"
                ),
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            input_artifact,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="missing_readout_evaluation_input",
                empty_code="empty_readout_evaluation_input",
                invalid_code="invalid_readout_evaluation_input",
                missing_schema_code="missing_readout_evaluation_input_schema",
                invalid_schema_code="invalid_readout_evaluation_input_schema",
                noun="readout evaluation input",
                diagnostic_path=input_artifact.ref,
            ),
        )
        measurements = dataset.records
        context.inputs.record_ref(CONFIG_SNAPSHOT_REF)
        if context.config.parameter_build is None:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "missing_readout_frequency_parameter_build",
                        "config snapshot is missing parameter build",
                        CONFIG_SNAPSHOT_REF,
                    )
                ]
            )
        parameter = context.config.parameter_build.get(READOUT_PARAMETER_ID)
        if parameter is None:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "missing_readout_frequency_config_parameter",
                        "config snapshot is missing readout_frequency",
                        CONFIG_SNAPSHOT_REF,
                    )
                ]
            )

        best_measurement = _minimum_s21_measurement(
            measurements=measurements,
            input_ref=input_artifact.ref,
        )
        minimum_s21 = best_measurement.observables["s21_db"]
        proposed_value = _readout_frequency_parameter(
            measurement=best_measurement,
            input_ref=input_artifact.ref,
        )
        reason = f"Minimum S21 observed at point {best_measurement.point_index}."
        proposal = ParameterChangeSet(
            id=READOUT_EVALUATION_STEP,
            source_run_id=context.run_id,
            reason=reason,
            patches=[
                ParameterPatch(
                    kind="set_scalar",
                    parameter_id=READOUT_PARAMETER_ID,
                    expected_value=parameter.quantity,
                    value=proposed_value,
                )
            ],
            confidence=1.0,
        )
        result = ReadoutFrequencyEvaluationResult(
            run_id=context.run_id,
            input_ref=input_artifact.ref,
            parameter_id=READOUT_PARAMETER_ID,
            best_point_index=best_measurement.point_index,
            minimum_s21=minimum_s21,
            old_value=parameter.quantity,
            proposed_value=proposed_value,
            diagnostics=[],
        )
        context.artifacts.write_model(
            id=READOUT_EVALUATION_RESULT_ARTIFACT_ID,
            kind="readout_frequency_evaluation_result",
            filename=_artifact_filename(READOUT_EVALUATION_RESULT_REF),
            model=result,
            media_type="application/json",
        )
        context.artifacts.write_text(
            id=READOUT_EVALUATION_SUMMARY_ARTIFACT_ID,
            kind="summary",
            filename=_artifact_filename(READOUT_EVALUATION_SUMMARY_REF),
            content=render_readout_frequency_evaluation_summary(
                result=result,
                proposal=proposal,
            ),
            media_type="text/markdown",
        )
        context.proposals.write_model(
            id=READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
            kind="parameter_change_set",
            filename=_artifact_filename(READOUT_RESONATOR_PROPOSAL_REF),
            model=proposal,
            media_type="application/json",
        )
        return EvaluationStepResult(
            result=result,
            proposals=(proposal,),
            job_id=READOUT_EVALUATION_STEP,
            job_ref=READOUT_EVALUATION_JOB_REF,
            job_artifact=EvaluationJobArtifact(id=READOUT_EVALUATION_JOB_ARTIFACT_ID),
        )


def render_readout_frequency_evaluation_summary(
    *,
    result: ReadoutFrequencyEvaluationResult,
    proposal: ParameterChangeSet,
) -> str:
    lines = [
        "# Readout Frequency Evaluation",
        "",
        f"- Run ID: {result.run_id}",
        f"- Step: {result.step}",
        f"- Input: {result.input_ref}",
        f"- Parameter: {result.parameter_id}",
        f"- Minimum point: {result.best_point_index}",
        f"- Minimum S21: {result.minimum_s21.value} {result.minimum_s21.unit}",
        f"- Old value: {result.old_value.value} {result.old_value.unit}",
        (
            f"- Proposed value: {result.proposed_value.value} "
            f"{result.proposed_value.unit}"
        ),
        f"- Proposal artifact: {result.proposal_artifact_id}",
        f"- Reason: {proposal.reason}",
        "",
    ]
    return "\n".join(lines)


def _minimum_s21_measurement(
    *,
    measurements: list[MeasurementRecord],
    input_ref: str,
) -> MeasurementRecord:
    candidates = [
        measurement
        for measurement in measurements
        if measurement.observables.get("s21_db") is not None
    ]
    if not candidates:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_s21_observable",
                    "readout evaluation input contains no s21_db observable",
                    input_ref,
                )
            ]
        )
    for measurement in candidates:
        observable = measurement.observables["s21_db"]
        if observable.unit != "dB":
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_readout_s21_observable",
                        "readout s21_db observable must use dB unit",
                        _measurement_path(input_ref, measurement),
                    )
                ]
            )
    return min(
        candidates,
        key=lambda measurement: (
            measurement.observables["s21_db"].value,
            measurement.point_index,
        ),
    )


def _readout_frequency_parameter(
    *, measurement: MeasurementRecord, input_ref: str
) -> Quantity:
    parameter = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if parameter is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_frequency_parameter",
                    "minimum S21 measurement is missing readout_frequency",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return parameter


def _measurement_path(input_ref: str, measurement: MeasurementRecord) -> str:
    return f"{input_ref}:point[{measurement.point_index}]"


def _artifact_filename(ref: str) -> str:
    return PurePosixPath(ref).name


def _diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
