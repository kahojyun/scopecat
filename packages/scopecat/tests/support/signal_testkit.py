"""Test-local signal workflow fixtures.

These helpers intentionally live outside the production package so core
workflow code can be tested without depending on a bundled demo domain.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

import scopecat as sc
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.evaluation.sdk import (
    ArtifactInputDiagnostics as EvaluationArtifactInputDiagnostics,
)
from scopecat.evaluation.sdk import (
    EvaluationContext,
    EvaluationJob,
    EvaluationJobArtifact,
    EvaluationStepResult,
    execute_evaluation_step,
)
from scopecat.experiments import ExperimentSpec, PlanSnapshot
from scopecat.instruments import NativeRunSnapshot
from scopecat.models.artifact import ProcessingJob
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterChangeSet,
    ParameterPatch,
    Quantity,
)
from scopecat.models.provider import ProviderOptionDescription
from scopecat.models.run import RunManifest
from scopecat.processing.sdk import (
    ArtifactInputDiagnostics as ProcessingArtifactInputDiagnostics,
)
from scopecat.processing.sdk import (
    ProcessingContext,
    ProcessingInputArtifact,
    ProcessingJobArtifact,
    ProcessingStepResult,
    execute_processing_step,
)
from scopecat.results import (
    MeasurementDatasetInputDiagnostics as EvaluationDatasetInputDiagnostics,
)
from scopecat.results import (
    MeasurementDatasetInputDiagnostics as ProcessingDatasetInputDiagnostics,
)
from scopecat.results import MeasurementRecord
from scopecat.workflows import (
    AnalysisCatalogDescription,
    AnalysisStepCatalogContext,
    AnalysisStepCatalogResult,
    AnalysisStepDescription,
)
from scopecat.workflows.runs import start_native_run
from tests.support.native_signal import TestSignalInstrumentProvider

SUMMARY_STATS_STEP = "summary-stats"
SUMMARY_STATS_INPUT_REF = "artifacts/raw-measurements.jsonl"
SUMMARY_STATS_RESULT_REF = "artifacts/summary-stats.json"
SUMMARY_STATS_SUMMARY_REF = "artifacts/summary-stats.md"
SUMMARY_STATS_JOB_REF = "processing/summary-stats.job.json"
BEST_SIGNAL_EVALUATION_STEP = "best-signal-proposal"
BEST_SIGNAL_ANALYSIS_STEP = "best-signal-analysis"
BEST_SIGNAL_INPUT_REF = "artifacts/raw-measurements.jsonl"
BEST_SIGNAL_CONFIG_REF = "config-profile.snapshot.json"
BEST_SIGNAL_PLAN_REF = "plan.snapshot.json"
BEST_SIGNAL_EVALUATION_RESULT_REF = "artifacts/best-signal-evaluation.json"
BEST_SIGNAL_EVALUATION_SUMMARY_REF = "artifacts/best-signal-evaluation.md"
BEST_SIGNAL_EVALUATION_JOB_REF = "evaluation/best-signal-proposal.job.json"
BEST_SIGNAL_PROPOSAL_REF = "proposals/best-signal-proposal.json"
BEST_SIGNAL_EVALUATION_RESULT_ARTIFACT_ID = "best-signal-evaluation-result"
BEST_SIGNAL_EVALUATION_SUMMARY_ARTIFACT_ID = "best-signal-evaluation-summary"
BEST_SIGNAL_EVALUATION_JOB_ARTIFACT_ID = "best-signal-evaluation-job"
BEST_SIGNAL_PROPOSAL_ARTIFACT_ID = "best-signal-proposal"
RAW_MEASUREMENTS_ARTIFACT_ID = "raw-measurements"
MEASUREMENT_DATASET_ARTIFACT_KIND = "measurement_dataset"
SAFE_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TEST_STEP_METADATA = {"scope": "test"}


class _MeasurementWithObservables(Protocol):
    observables: dict[str, Quantity]


class SummaryStatsObservable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    min: float
    max: float
    mean: float
    unit: str


class SummaryStatsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.test_summary_stats_result.v0"
    run_id: str
    step: str = SUMMARY_STATS_STEP
    input_ref: str
    measurement_count: int
    observables: dict[str, SummaryStatsObservable]
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class BestSignalEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.test_best_signal_evaluation_result.v0"
    run_id: str
    step: str = BEST_SIGNAL_EVALUATION_STEP
    input_ref: str = BEST_SIGNAL_INPUT_REF
    proposal_artifact_id: str = BEST_SIGNAL_PROPOSAL_ARTIFACT_ID
    parameter_id: str
    best_point_index: int
    best_signal: Quantity
    old_value: Quantity
    proposed_value: Quantity
    diagnostics: list[Diagnostic] = Field(default_factory=list)


@dataclass
class _Accumulator:
    count: int
    total: float
    minimum: float
    maximum: float
    unit: str

    def add(self, value: float, unit: str) -> None:
        if unit != self.unit:
            raise ValueError("observable unit changed")
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    def to_result(self) -> SummaryStatsObservable:
        return SummaryStatsObservable(
            count=self.count,
            min=self.minimum,
            max=self.maximum,
            mean=round(self.total / self.count, 12),
            unit=self.unit,
        )


@dataclass(frozen=True)
class SummaryStatsProcessingStep:
    selector: str | None = None
    step_id: str = SUMMARY_STATS_STEP

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[SummaryStatsResult]:
        source = _resolve_summary_stats_input(context, self.selector)
        _validate_source_artifact_id(source.artifact_id)
        dataset = context.inputs.read_measurement_dataset(
            source,
            diagnostics=ProcessingDatasetInputDiagnostics(
                missing_code="missing_processing_input",
                empty_code="empty_processing_input",
                invalid_code="invalid_processing_input",
                missing_schema_code="missing_processing_input_schema",
                invalid_schema_code="invalid_processing_input_schema",
                noun="processing input",
                diagnostic_path=source.ref,
            ),
        )
        refs = _SummaryStatsRefs(source.artifact_id)
        result = _build_summary_result(
            run_id=context.run_id,
            step=SUMMARY_STATS_STEP,
            input_ref=source.ref,
            diagnostic_path=source.ref,
            measurements=dataset.records,
        )
        context.artifacts.write_model(
            id=refs.result_artifact_id,
            kind="test_summary_stats_result",
            filename=_artifact_filename(refs.result_ref),
            model=result,
            media_type="application/json",
            metadata=TEST_STEP_METADATA,
        )
        context.artifacts.write_text(
            id=refs.summary_artifact_id,
            kind="summary",
            filename=_artifact_filename(refs.summary_ref),
            content=render_summary_stats_summary(result),
            media_type="text/markdown",
            metadata=TEST_STEP_METADATA,
        )
        return ProcessingStepResult(
            result=result,
            job_id=refs.job_id,
            job_ref=refs.job_ref,
            metadata=TEST_STEP_METADATA,
            job_artifact=ProcessingJobArtifact(
                id=refs.job_artifact_id,
                metadata=TEST_STEP_METADATA,
            ),
        )


@dataclass(frozen=True)
class BestSignalEvaluationStep:
    step_id: str = BEST_SIGNAL_EVALUATION_STEP

    def run(
        self, context: EvaluationContext
    ) -> EvaluationStepResult[
        BestSignalEvaluationResult,
        ParameterChangeSet,
    ]:
        source = context.inputs.resolve_artifact(
            selector="raw-measurements",
            expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            diagnostics=EvaluationArtifactInputDiagnostics(
                not_found_code="evaluation_input_not_found",
                invalid_kind_code="unsupported_evaluation_input_artifact",
                path_escape_code="evaluation_input_path_escape",
                not_found_message="evaluation input artifact not found",
                invalid_kind_message=(
                    "best-signal evaluation supports measurement_dataset only"
                ),
                path_escape_message="evaluation input selector escapes run directory",
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            source,
            diagnostics=EvaluationDatasetInputDiagnostics(
                missing_code="missing_evaluation_input",
                empty_code="empty_evaluation_input",
                invalid_code="invalid_evaluation_input",
                missing_schema_code="missing_evaluation_input_schema",
                invalid_schema_code="invalid_evaluation_input_schema",
                noun="evaluation input",
                diagnostic_path=source.ref,
            ),
        )
        context.inputs.record_ref(BEST_SIGNAL_CONFIG_REF)
        context.inputs.record_ref(BEST_SIGNAL_PLAN_REF)
        parameter_id = _sweep_parameter_id(context.plan)
        old_value = _old_parameter_value(context.config, parameter_id)
        best_measurement = _best_signal_measurement(dataset.records)
        proposed_value = _proposed_value(best_measurement, parameter_id)
        best_signal = best_measurement.observables["signal"]
        proposal = ParameterChangeSet(
            id=BEST_SIGNAL_EVALUATION_STEP,
            source_run_id=context.run_id,
            reason=f"Best signal observed at point {best_measurement.point_index}.",
            patches=[
                ParameterPatch(
                    kind="set_scalar",
                    parameter_id=parameter_id,
                    expected_value=old_value,
                    value=proposed_value,
                )
            ],
            confidence=best_signal.value,
        )
        result = BestSignalEvaluationResult(
            run_id=context.run_id,
            parameter_id=parameter_id,
            best_point_index=best_measurement.point_index,
            best_signal=best_signal,
            old_value=old_value,
            proposed_value=proposed_value,
        )
        context.artifacts.write_model(
            id=BEST_SIGNAL_EVALUATION_RESULT_ARTIFACT_ID,
            kind="test_best_signal_evaluation_result",
            filename=_artifact_filename(BEST_SIGNAL_EVALUATION_RESULT_REF),
            model=result,
            media_type="application/json",
            metadata=TEST_STEP_METADATA,
        )
        context.artifacts.write_text(
            id=BEST_SIGNAL_EVALUATION_SUMMARY_ARTIFACT_ID,
            kind="summary",
            filename=_artifact_filename(BEST_SIGNAL_EVALUATION_SUMMARY_REF),
            content=render_best_signal_summary(result=result, proposal=proposal),
            media_type="text/markdown",
            metadata=TEST_STEP_METADATA,
        )
        context.proposals.write_model(
            id=BEST_SIGNAL_PROPOSAL_ARTIFACT_ID,
            kind="parameter_change_set",
            filename=_artifact_filename(BEST_SIGNAL_PROPOSAL_REF),
            model=proposal,
            media_type="application/json",
            metadata=TEST_STEP_METADATA,
        )
        return EvaluationStepResult(
            result=result,
            proposals=(proposal,),
            job_id=BEST_SIGNAL_EVALUATION_STEP,
            job_ref=BEST_SIGNAL_EVALUATION_JOB_REF,
            metadata=TEST_STEP_METADATA,
            job_artifact=EvaluationJobArtifact(
                id=BEST_SIGNAL_EVALUATION_JOB_ARTIFACT_ID,
                metadata=TEST_STEP_METADATA,
            ),
        )


@dataclass
class TestSignalAnalysisStep:
    __test__ = False

    selector: str | None = None
    id: str = BEST_SIGNAL_ANALYSIS_STEP

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements(self.selector or RAW_MEASUREMENTS_ARTIFACT_ID)
        summary = _build_summary_result(
            run_id=context.run.id,
            step=BEST_SIGNAL_ANALYSIS_STEP,
            input_ref=raw.artifact.path,
            diagnostic_path=raw.artifact.path,
            measurements=raw.dataset.records,
        )
        parameter_id = _sweep_parameter_id(context.data.plan_preview())
        best_measurement = _best_signal_measurement(raw.dataset.records)
        proposed_value = _proposed_value(best_measurement, parameter_id)
        return (
            context.result("best signal analysis")
            .artifact_ref(
                raw.artifact.id,
                title="raw measurements",
                expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            )
            .table(
                [
                    {
                        "measurement_count": summary.measurement_count,
                        "best_point_index": best_measurement.point_index,
                    }
                ],
                title="signal summary",
            )
            .guess(
                parameter_id,
                proposed_value,
                reason=f"Best signal observed at point {best_measurement.point_index}.",
            )
        )


@dataclass(frozen=True)
class TestSignalAnalysisCatalog:
    __test__ = False

    catalog_id: str = "tests.signal_analysis"

    def describe(self) -> AnalysisCatalogDescription:
        return AnalysisCatalogDescription(
            catalog_id=self.catalog_id,
            steps=(
                AnalysisStepDescription(
                    step_id=BEST_SIGNAL_ANALYSIS_STEP,
                    label="Best signal analysis",
                    options=(
                        ProviderOptionDescription(
                            id="input",
                            dtype="string | None",
                            default=None,
                            label="Input dataset",
                        ),
                    ),
                    input_artifact_kinds=("measurement_dataset",),
                    output_artifact_kinds=(
                        "test_summary_stats_result",
                        "test_best_signal_evaluation",
                        "summary",
                    ),
                    guess_kinds=("drive_frequency",),
                    metadata=TEST_STEP_METADATA,
                ),
            ),
            metadata=TEST_STEP_METADATA,
        )

    def analysis_step(
        self, context: AnalysisStepCatalogContext
    ) -> AnalysisStepCatalogResult:
        if context.step_id != BEST_SIGNAL_ANALYSIS_STEP:
            return AnalysisStepCatalogResult(
                diagnostics=(
                    _diagnostic(
                        "error",
                        "unsupported_analysis_step",
                        f"unsupported analysis step {context.step_id}",
                        "step",
                    ),
                ),
                metadata={"catalog_id": self.catalog_id},
            )
        input_option = context.options.get("input")
        if input_option is not None and not isinstance(input_option, str):
            return AnalysisStepCatalogResult(
                diagnostics=(
                    _diagnostic(
                        "error",
                        "invalid_analysis_catalog_option",
                        "best signal analysis option input must be a string",
                        "options.input",
                    ),
                ),
                metadata={"catalog_id": self.catalog_id},
            )
        return AnalysisStepCatalogResult(
            step=TestSignalAnalysisStep(selector=input_option),
            metadata={"catalog_id": self.catalog_id},
        )


def execute_signal_native_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    workspace: str | Path,
) -> tuple[RunManifest, NativeRunSnapshot]:
    result = start_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
        instrument_provider=TestSignalInstrumentProvider(),
    )
    return result.manifest, cast(NativeRunSnapshot, result.snapshot)


def execute_summary_stats_processing(
    *, run_id: str, workspace: str | Path, selector: str | None = None
) -> tuple[ProcessingJob, SummaryStatsResult]:
    return execute_processing_step(
        run_id=run_id,
        workspace=workspace,
        step=SummaryStatsProcessingStep(selector=selector),
    )


def execute_best_signal_evaluation(
    *, run_id: str, workspace: str | Path
) -> tuple[EvaluationJob, BestSignalEvaluationResult, ParameterChangeSet]:
    job, result, proposals = execute_evaluation_step(
        run_id=run_id,
        workspace=workspace,
        step=BestSignalEvaluationStep(),
    )
    return job, result, proposals[0]


def render_summary_stats_summary(result: SummaryStatsResult) -> str:
    lines = [
        "# Scopecat Summary Stats",
        "",
        f"- Run ID: {result.run_id}",
        f"- Step: {result.step}",
        f"- Input: {result.input_ref}",
        f"- Measurements: {result.measurement_count}",
        "",
        "## Observables",
        "",
    ]
    for name in sorted(result.observables):
        observable = result.observables[name]
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Count: {observable.count}",
                f"- Min: {observable.min} {observable.unit}",
                f"- Max: {observable.max} {observable.unit}",
                f"- Mean: {observable.mean} {observable.unit}",
                "",
            ]
        )
    return "\n".join(lines)


def render_best_signal_summary(
    *, result: BestSignalEvaluationResult, proposal: ParameterChangeSet
) -> str:
    return "\n".join(
        [
            "# Scopecat Best Signal Evaluation",
            "",
            f"- Run ID: {result.run_id}",
            f"- Step: {result.step}",
            f"- Input: {result.input_ref}",
            f"- Parameter: {result.parameter_id}",
            f"- Best point: {result.best_point_index}",
            f"- Best signal: {result.best_signal.value} {result.best_signal.unit}",
            f"- Old value: {result.old_value.value} {result.old_value.unit}",
            (
                f"- Proposed value: {result.proposed_value.value} "
                f"{result.proposed_value.unit}"
            ),
            f"- Proposal artifact: {result.proposal_artifact_id}",
            f"- Reason: {proposal.reason}",
            "",
        ]
    )


def _build_summary_result(
    *,
    run_id: str,
    step: str,
    input_ref: str,
    diagnostic_path: str,
    measurements: Sequence[_MeasurementWithObservables],
) -> SummaryStatsResult:
    accumulators: dict[str, _Accumulator] = {}
    for measurement in measurements:
        for name, quantity in measurement.observables.items():
            accumulator = accumulators.get(name)
            if accumulator is None:
                accumulators[name] = _Accumulator(
                    count=1,
                    total=quantity.value,
                    minimum=quantity.value,
                    maximum=quantity.value,
                    unit=quantity.unit,
                )
                continue
            try:
                accumulator.add(quantity.value, quantity.unit)
            except ValueError as error:
                raise ValidationFailed(
                    [
                        _diagnostic(
                            "error",
                            "invalid_processing_input",
                            f"observable {name} uses inconsistent units",
                            diagnostic_path,
                        )
                    ]
                ) from error

    if not accumulators:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_observables",
                    "processing input contains no observables",
                    diagnostic_path,
                )
            ]
        )

    return SummaryStatsResult(
        run_id=run_id,
        step=step,
        input_ref=input_ref,
        measurement_count=len(measurements),
        observables={
            name: accumulator.to_result()
            for name, accumulator in sorted(accumulators.items())
        },
    )


class _SummaryStatsRefs:
    def __init__(self, source_artifact_id: str) -> None:
        if source_artifact_id == RAW_MEASUREMENTS_ARTIFACT_ID:
            self.job_id = SUMMARY_STATS_STEP
            self.job_ref = SUMMARY_STATS_JOB_REF
            self.result_artifact_id = "summary-stats-result"
            self.summary_artifact_id = "summary-stats-summary"
            self.job_artifact_id = "summary-stats-job"
            self.result_ref = SUMMARY_STATS_RESULT_REF
            self.summary_ref = SUMMARY_STATS_SUMMARY_REF
            return
        self.job_id = f"{source_artifact_id}-summary-stats"
        self.job_ref = f"processing/{source_artifact_id}.summary-stats.job.json"
        self.result_artifact_id = f"{source_artifact_id}-summary-stats-result"
        self.summary_artifact_id = f"{source_artifact_id}-summary-stats-summary"
        self.job_artifact_id = f"{source_artifact_id}-summary-stats-job"
        self.result_ref = f"artifacts/{source_artifact_id}.summary-stats.json"
        self.summary_ref = f"artifacts/{source_artifact_id}.summary-stats.md"


def _resolve_summary_stats_input(
    context: ProcessingContext,
    selector: str | None,
) -> ProcessingInputArtifact:
    if selector is None:
        selector = RAW_MEASUREMENTS_ARTIFACT_ID
    return context.inputs.resolve_artifact(
        selector=selector,
        expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
        diagnostics=ProcessingArtifactInputDiagnostics(
            not_found_code="processing_input_not_found",
            invalid_kind_code="unsupported_processing_input_artifact",
            path_escape_code="processing_input_path_escape",
            not_found_message="processing input artifact not found",
            invalid_kind_message=(
                "summary-stats supports measurement_dataset artifacts only"
            ),
            path_escape_message="processing input selector escapes run directory",
            diagnostic_path="input",
        ),
    )


def _sweep_parameter_id(plan: PlanSnapshot) -> str:
    coordinate_ids = _primary_coordinates(plan)
    if len(coordinate_ids) != 1 or not coordinate_ids[0]:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_sweep_coordinate",
                    "evaluation requires exactly one sweep coordinate",
                    "plan.snapshot.json",
                )
            ]
        )
    return coordinate_ids[0]


def _primary_coordinates(plan: PlanSnapshot) -> list[str]:
    if plan.expected_dataset_schema is not None:
        return plan.expected_dataset_schema.primary_coordinates
    return plan.point_coordinate_ids


def _old_parameter_value(config: ConfigProfileSnapshot, parameter_id: str) -> Quantity:
    parameter = (
        config.parameter_build.get(parameter_id)
        if config.parameter_build is not None
        else None
    )
    if parameter is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_parameter_value",
                    f"config snapshot has no parameter for {parameter_id}",
                    "config-profile.snapshot.json",
                )
            ]
        )
    return parameter.quantity


def _best_signal_measurement(
    measurements: list[MeasurementRecord],
) -> MeasurementRecord:
    candidates = [
        measurement
        for measurement in measurements
        if measurement.observables.get("signal") is not None
    ]
    if not candidates:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_signal_observable",
                    "evaluation input contains no signal observable",
                    BEST_SIGNAL_INPUT_REF,
                )
            ]
        )
    return max(
        candidates,
        key=lambda measurement: (
            measurement.observables["signal"].value,
            -measurement.point_index,
        ),
    )


def _proposed_value(measurement: MeasurementRecord, parameter_id: str) -> Quantity:
    quantity = measurement.coordinates.get(parameter_id)
    if quantity is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_parameter_value",
                    f"best point has no parameter for {parameter_id}",
                    BEST_SIGNAL_INPUT_REF,
                )
            ]
        )
    return quantity


def _validate_source_artifact_id(source_artifact_id: str) -> None:
    if not SAFE_ARTIFACT_ID_RE.fullmatch(source_artifact_id):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_processing_input",
                    f"processing input artifact id is not safe: {source_artifact_id}",
                    "input",
                )
            ]
        )


def _artifact_filename(ref: str) -> str:
    return PurePosixPath(ref).name


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
