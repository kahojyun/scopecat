"""Test-local signal workflow fixtures.

These helpers intentionally live outside the production package so core
workflow code can be tested without depending on a bundled demo domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

import scopecat as sc
from scopecat.authoring import ExperimentInvocation
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.composition.local import local_workspace_services
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.measurements.results import (
    MeasurementArray,
    MeasurementRecord,
    MeasurementValue,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution import ExecutionSummary
from scopecat.records.parameter import Quantity, ScalarParameterValue
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.runs.access import (
    dataset_storage_ref,
    record_storage_ref,
)
from scopecat.runs.service import start_run
from tests.testkit.signal_instruments import TestSignalInstrumentProvider

SUMMARY_STATS_STEP = "summary-stats"
SUMMARY_STATS_INPUT_REF = "data/measurement_dataset/raw-measurements"
SUMMARY_STATS_RESULT_REF = "artifacts/test_summary_stats_result/summary-stats-result"
SUMMARY_STATS_SUMMARY_REF = "artifacts/summary/summary-stats-summary"
BEST_SIGNAL_ANALYSIS_STEP = "best-signal-analysis"
BEST_SIGNAL_INPUT_REF = "data/measurement_dataset/raw-measurements"
BEST_SIGNAL_CONFIG_REF = "config-profile.snapshot.json"
BEST_SIGNAL_SCHEMA_REF = "data/measurement_dataset/raw-measurements.schema"
BEST_SIGNAL_ANALYSIS_RESULT_ARTIFACT_ID = "best-signal-analysis-result"
BEST_SIGNAL_ANALYSIS_SUMMARY_ARTIFACT_ID = "best-signal-analysis-summary"
BEST_SIGNAL_ANALYSIS_RESULT_REF = (
    "artifacts/test_best_signal_analysis_result/"
    f"{BEST_SIGNAL_ANALYSIS_RESULT_ARTIFACT_ID}"
)
BEST_SIGNAL_ANALYSIS_SUMMARY_REF = (
    f"artifacts/summary/{BEST_SIGNAL_ANALYSIS_SUMMARY_ARTIFACT_ID}"
)
RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
MEASUREMENT_DATASET_KIND = "measurement_dataset"
TEST_STEP_METADATA = {"scope": "test"}


class _MeasurementWithObservables(Protocol):
    observables: dict[str, MeasurementValue]


class SummaryStatsObservable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    min: float
    max: float
    mean: float
    unit: str


class SummaryStatsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.test_summary_stats_result.v1"
    run_id: str
    step: str = SUMMARY_STATS_STEP
    input_ref: str
    measurement_count: int
    observables: dict[str, SummaryStatsObservable]
    problems: tuple[Problem, ...] = ()


class BestSignalAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.test_best_signal_analysis_result.v1"
    run_id: str
    step: str = BEST_SIGNAL_ANALYSIS_STEP
    input_ref: str = BEST_SIGNAL_INPUT_REF
    parameter_id: str
    best_point_index: int
    best_signal: Quantity
    old_value: Quantity
    proposed_value: Quantity
    problems: tuple[Problem, ...] = ()


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
        raw = context.data.measurements(self.selector or RAW_MEASUREMENTS_DATASET_ID)
        input_ref = dataset_storage_ref(raw.dataset_entry)
        result = _build_summary_result(
            run_id=context.run.id,
            step=SUMMARY_STATS_STEP,
            input_ref=input_ref,
            measurements=raw.dataset.records,
        )
        return (
            context.result("summary stats")
            .input(
                raw.dataset_entry.id,
                title="raw measurements",
                expected_kind=MEASUREMENT_DATASET_KIND,
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
        raw = context.data.measurements(RAW_MEASUREMENTS_DATASET_ID)
        parameter_id = _scan_parameter_id(context.data.schema())
        old_value = _old_parameter_value(context.config, parameter_id)
        best_measurement = _best_signal_measurement(raw.dataset.records)
        proposed_value = _proposed_value(
            best_measurement,
            parameter_id,
            old_value=old_value,
        )
        best_signal = _signal_quantity(
            measurement=best_measurement,
            problem_ref=BEST_SIGNAL_INPUT_REF,
        )
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
                raw.dataset_entry.id,
                title="raw measurements",
                expected_kind=MEASUREMENT_DATASET_KIND,
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
                sc.replace_scalar_parameter(parameter_id, proposed_value),
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
        raw = context.data.measurements(self.selector or RAW_MEASUREMENTS_DATASET_ID)
        input_ref = dataset_storage_ref(raw.dataset_entry)
        summary = _build_summary_result(
            run_id=context.run.id,
            step=BEST_SIGNAL_ANALYSIS_STEP,
            input_ref=input_ref,
            measurements=raw.dataset.records,
        )
        parameter_id = _scan_parameter_id(context.data.schema())
        best_measurement = _best_signal_measurement(raw.dataset.records)
        proposed_value = _proposed_value(
            best_measurement,
            parameter_id,
            old_value=_old_parameter_value(context.config, parameter_id),
        )
        return (
            context.result("best signal analysis")
            .input(
                raw.dataset_entry.id,
                title="raw measurements",
                expected_kind=MEASUREMENT_DATASET_KIND,
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
                sc.replace_scalar_parameter(parameter_id, proposed_value),
                reason=f"Best signal observed at point {best_measurement.point_index}.",
            )
        )


def execute_signal_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInvocation,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    services = local_workspace_services(workspace)
    manifest = start_run(
        config=config,
        experiment=prepare_invocation(experiment),
        services=services,
        execution_backend=sc.ExecutionBackend(provider=TestSignalInstrumentProvider()),
        config_source=config_source,
    )
    summary_record = next(
        record for record in manifest.records if record.kind == "execution_summary"
    )
    summary = services.runs.read_model(
        manifest.run_id,
        record_storage_ref(summary_record),
        ExecutionSummary,
    )
    return manifest, summary


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
    measurements: Sequence[_MeasurementWithObservables],
) -> SummaryStatsResult:
    accumulators: dict[str, _Accumulator] = {}
    for measurement in measurements:
        for name, observable in measurement.observables.items():
            values, unit = _numeric_observable_values(
                name=name,
                observable=observable,
                problem_ref=input_ref,
            )
            accumulator = accumulators.get(name)
            if accumulator is None:
                first_value = values[0]
                accumulators[name] = _Accumulator(
                    count=1,
                    total=first_value,
                    minimum=first_value,
                    maximum=first_value,
                    unit=unit,
                )
                accumulator = accumulators[name]
                values = values[1:]
            for value in values:
                try:
                    accumulator.add(value, unit)
                except ValueError as error:
                    raise CheckFailed(
                        [
                            _problem(
                                "invalid_analysis_input",
                                f"observable {name} uses inconsistent units",
                                input_ref,
                            )
                        ]
                    ) from error

    if not accumulators:
        raise CheckFailed(
            [
                _problem(
                    "missing_observables",
                    "analysis input contains no observables",
                    input_ref,
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


def _numeric_observable_values(
    *,
    name: str,
    observable: MeasurementValue,
    problem_ref: str,
) -> tuple[list[float], str]:
    unit = observable.unit
    if unit is None:
        raise CheckFailed(
            [
                _problem(
                    "invalid_analysis_input",
                    f"observable {name} is missing unit",
                    problem_ref,
                )
            ]
        )
    if isinstance(observable, Quantity):
        return [observable.value], unit
    if not isinstance(observable, MeasurementArray):
        raise CheckFailed(
            [
                _problem(
                    "invalid_analysis_input",
                    f"observable {name} must use numeric values",
                    problem_ref,
                )
            ]
        )
    if observable.dtype not in {"float64", "int64"}:
        raise CheckFailed(
            [
                _problem(
                    "invalid_analysis_input",
                    f"observable {name} must use numeric values",
                    problem_ref,
                )
            ]
        )
    try:
        values = _flatten_numeric_array_values(observable.values)
    except ValueError as error:
        raise CheckFailed(
            [
                _problem(
                    "invalid_analysis_input",
                    f"observable {name} must use numeric values",
                    problem_ref,
                )
            ]
        ) from error
    if not values:
        raise CheckFailed(
            [
                _problem(
                    "invalid_analysis_input",
                    f"observable {name} contains no values",
                    problem_ref,
                )
            ]
        )
    return values, unit


def _flatten_numeric_array_values(values: Sequence[object]) -> list[float]:
    flattened: list[float] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(_flatten_numeric_array_values(value))
        elif isinstance(value, int | float):
            flattened.append(float(value))
        else:
            msg = "measurement array contains a non-numeric value"
            raise ValueError(msg)
    return flattened


def _scan_parameter_id(schema: sc.MeasurementDatasetSchema) -> str:
    coordinate_ids = list(schema.primary_coordinates)
    if len(coordinate_ids) != 1 or not coordinate_ids[0]:
        raise CheckFailed(
            [
                _problem(
                    "missing_scan_coordinate",
                    "analysis requires exactly one scan coordinate",
                    BEST_SIGNAL_SCHEMA_REF,
                )
            ]
        )
    return coordinate_ids[0]


def _old_parameter_value(config: ConfigProfileSnapshot, parameter_id: str) -> Quantity:
    parameter = config.parameter_snapshot.get(parameter_id)
    if not isinstance(parameter, ScalarParameterValue):
        raise CheckFailed(
            [
                _problem(
                    "missing_parameter_value",
                    f"config snapshot has no scalar parameter for {parameter_id}",
                    "config-profile.snapshot.json",
                )
            ]
        )
    if not isinstance(parameter.value, Quantity):
        raise CheckFailed(
            [
                _problem(
                    "parameter_value_type_mismatch",
                    f"config parameter {parameter_id} is not a quantity",
                    "config-profile.snapshot.json",
                )
            ]
        )
    return parameter.value


def _best_signal_measurement(
    measurements: list[MeasurementRecord],
) -> MeasurementRecord:
    candidates = [
        measurement
        for measurement in measurements
        if isinstance(measurement.observables.get("signal"), Quantity)
    ]
    if not candidates:
        raise CheckFailed(
            [
                _problem(
                    "missing_signal_observable",
                    "analysis input contains no signal observable",
                    BEST_SIGNAL_INPUT_REF,
                )
            ]
        )
    return max(
        candidates,
        key=lambda measurement: (
            _signal_quantity(
                measurement=measurement,
                problem_ref=BEST_SIGNAL_INPUT_REF,
            ).value,
            -measurement.point_index,
        ),
    )


def _signal_quantity(
    *,
    measurement: MeasurementRecord,
    problem_ref: str,
) -> Quantity:
    signal = measurement.observables.get("signal")
    if isinstance(signal, Quantity):
        return signal
    raise CheckFailed(
        [
            _problem(
                "invalid_signal_observable",
                "signal observable must be scalar",
                problem_ref,
            )
        ]
    )


def _proposed_value(
    measurement: MeasurementRecord,
    parameter_id: str,
    *,
    old_value: Quantity,
) -> Quantity:
    quantity = measurement.coordinates.get(parameter_id)
    if not isinstance(quantity, Quantity):
        raise CheckFailed(
            [
                _problem(
                    "missing_parameter_value",
                    f"best point has no parameter for {parameter_id}",
                    BEST_SIGNAL_INPUT_REF,
                )
            ]
        )
    if quantity != old_value:
        return quantity
    # The symmetric fake signal peaks at the current center. Keep the analysis
    # fixture useful as a proposal workflow by producing a small next-fit update.
    return Quantity(value=old_value.value + 0.01, unit=old_value.unit)


def _problem(code: str, message: str, ref: str) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.ANALYSIS,
        location=StorageLocation(ref=ref),
    )
