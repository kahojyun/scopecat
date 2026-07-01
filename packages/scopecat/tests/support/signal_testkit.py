"""Test-local signal workflow fixtures.

These helpers intentionally live outside the production package so core
workflow code can be tested without depending on a bundled demo domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

import scopecat as sc
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, PlanSnapshot
from scopecat.instruments import NativeRunSnapshot
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.models.run import RunManifest
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
BEST_SIGNAL_ANALYSIS_STEP = "best-signal-analysis"
BEST_SIGNAL_INPUT_REF = "artifacts/raw-measurements.jsonl"
BEST_SIGNAL_CONFIG_REF = "config-profile.snapshot.json"
BEST_SIGNAL_PLAN_REF = "plan.snapshot.json"
BEST_SIGNAL_ANALYSIS_RESULT_REF = "artifacts/best-signal-analysis.json"
BEST_SIGNAL_ANALYSIS_SUMMARY_REF = "artifacts/best-signal-analysis.md"
BEST_SIGNAL_ANALYSIS_RESULT_ARTIFACT_ID = "best-signal-analysis-result"
BEST_SIGNAL_ANALYSIS_SUMMARY_ARTIFACT_ID = "best-signal-analysis-summary"
RAW_MEASUREMENTS_ARTIFACT_ID = "raw-measurements"
MEASUREMENT_DATASET_ARTIFACT_KIND = "measurement_dataset"
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


class BestSignalAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.test_best_signal_analysis_result.v0"
    run_id: str
    step: str = BEST_SIGNAL_ANALYSIS_STEP
    input_ref: str = BEST_SIGNAL_INPUT_REF
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


@dataclass
class SummaryStatsAnalysisStep:
    selector: str | None = None
    id: str = SUMMARY_STATS_STEP

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements(self.selector or RAW_MEASUREMENTS_ARTIFACT_ID)
        result = _build_summary_result(
            run_id=context.run.id,
            step=SUMMARY_STATS_STEP,
            input_ref=raw.artifact.path,
            diagnostic_path=raw.artifact.path,
            measurements=raw.dataset.records,
        )
        return (
            context.result("summary stats")
            .input(
                raw.artifact.id,
                title="raw measurements",
                expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            )
            .artifact(
                title="summary stats result",
                kind="test_summary_stats_result",
                artifact_id="summary-stats-result",
                filename="summary-stats.json",
                model=result,
                media_type="application/json",
                metadata=TEST_STEP_METADATA,
            )
            .artifact(
                title="summary stats markdown",
                kind="summary",
                artifact_id="summary-stats-summary",
                filename="summary-stats.md",
                text=render_summary_stats_summary(result),
                media_type="text/markdown",
                metadata=TEST_STEP_METADATA,
            )
        )


@dataclass
class BestSignalAnalysisStep:
    id: str = BEST_SIGNAL_ANALYSIS_STEP

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements(RAW_MEASUREMENTS_ARTIFACT_ID)
        parameter_id = _sweep_parameter_id(context.data.plan_preview())
        old_value = _old_parameter_value(context.config, parameter_id)
        best_measurement = _best_signal_measurement(raw.dataset.records)
        proposed_value = _proposed_value(best_measurement, parameter_id)
        best_signal = best_measurement.observables["signal"]
        reason = f"Best signal observed at point {best_measurement.point_index}."
        result = BestSignalAnalysisResult(
            run_id=context.run.id,
            parameter_id=parameter_id,
            best_point_index=best_measurement.point_index,
            best_signal=best_signal,
            old_value=old_value,
            proposed_value=proposed_value,
        )
        return (
            context.result("best signal analysis")
            .input(
                raw.artifact.id,
                title="raw measurements",
                expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            )
            .artifact(
                title="best signal analysis result",
                kind="test_best_signal_analysis_result",
                artifact_id=BEST_SIGNAL_ANALYSIS_RESULT_ARTIFACT_ID,
                filename="best-signal-analysis.json",
                model=result,
                media_type="application/json",
                metadata=TEST_STEP_METADATA,
            )
            .artifact(
                title="best signal analysis markdown",
                kind="summary",
                artifact_id=BEST_SIGNAL_ANALYSIS_SUMMARY_ARTIFACT_ID,
                filename="best-signal-analysis.md",
                text=render_best_signal_summary(result=result, reason=reason),
                media_type="text/markdown",
                metadata=TEST_STEP_METADATA,
            )
            .propose(
                parameter_id,
                sc.set_param(parameter_id, proposed_value),
                reason=reason,
                confidence=best_signal.value,
            )
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
            .input(
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
            .propose(
                parameter_id,
                sc.set_param(parameter_id, proposed_value),
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
                        "test_best_signal_analysis_result",
                        "summary",
                    ),
                    parameter_change_kinds=("drive_frequency",),
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


def _analysis_run(*, run_id: str, workspace: str | Path) -> sc.Run:
    lab = sc.open(workspace)
    return lab.get_run(run_id)


def execute_summary_stats_analysis(
    *, run_id: str, workspace: str | Path, selector: str | None = None
) -> sc.SavedAnalysis:
    run = _analysis_run(run_id=run_id, workspace=workspace)
    return run.analyze(SummaryStatsAnalysisStep(selector=selector)).save()


def execute_best_signal_analysis(*, run_id: str, workspace: str | Path) -> sc.Analysis:
    run = _analysis_run(run_id=run_id, workspace=workspace)
    return run.analyze(BestSignalAnalysisStep())


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


def render_best_signal_summary(*, result: BestSignalAnalysisResult, reason: str) -> str:
    return "\n".join(
        [
            "# Scopecat Best Signal Analysis",
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
            f"- Reason: {reason}",
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
                            "invalid_analysis_input",
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
                    "analysis input contains no observables",
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


def _sweep_parameter_id(plan: PlanSnapshot) -> str:
    coordinate_ids = _primary_coordinates(plan)
    if len(coordinate_ids) != 1 or not coordinate_ids[0]:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_sweep_coordinate",
                    "analysis requires exactly one sweep coordinate",
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
                    "analysis input contains no signal observable",
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


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
