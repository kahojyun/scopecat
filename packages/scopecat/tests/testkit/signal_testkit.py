"""Test-local signal workflow fixtures.

These helpers intentionally live outside the production package so core
workflow code can be tested without depending on a bundled demo domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict

import scopecat as sc
from scopecat.authoring import ExperimentInvocation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    StorageLocation,
    problem,
)
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.results import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementRecord,
    MeasurementValue,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import ScalarParameterValue
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.runs.access import dataset_storage_ref
from tests.testkit.execution import execute_invocation_run
from tests.testkit.instrument_host import compose_test_instruments
from tests.testkit.signal_instruments import TestSignalInstrumentProvider

SUMMARY_STATS_STEP = "summary-stats"
BEST_SIGNAL_ANALYSIS_STEP = "best-signal-analysis"
BEST_SIGNAL_INPUT_REF = "data/measurement_dataset/raw-measurements"
BEST_SIGNAL_SCHEMA_REF = "data/measurement_dataset/raw-measurements.schema"
RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
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

    run_id: str
    step: str = SUMMARY_STATS_STEP
    input_ref: str
    measurement_count: int
    observables: dict[str, SummaryStatsObservable]
    problems: tuple[Problem, ...] = ()


class BestSignalAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
            )
            .table(
                [result.model_dump(mode="json")],
                title="summary stats result",
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
            )
            .table(
                [result.model_dump(mode="json")],
                title="best signal analysis result",
                metadata=TEST_STEP_METADATA,
            )
            .propose(
                parameter_id,
                sc.replace_scalar_parameter(parameter_id, proposed_value),
                reason=reason,
                confidence=best_signal.value,
            )
        )


def execute_signal_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInvocation,
    project_root: str | Path,
    config_source: RunConfigSource | None = None,
) -> RunManifest:
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    return execute_invocation_run(
        config=config,
        experiment=experiment,
        system=composition.system,
        instrument_backend=composition.backend,
        project_root=project_root,
        config_source=config_source,
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
            flattened.extend(_flatten_numeric_array_values(cast("list[object]", value)))
        elif isinstance(value, int | float):
            flattened.append(float(value))
        else:
            msg = "measurement array contains a non-numeric value"
            raise ValueError(msg)
    return flattened


def _scan_parameter_id(schema: MeasurementDatasetSchema) -> str:
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
    return problem(
        code,
        message,
        phase=ProblemPhase.ANALYSIS,
        location=StorageLocation(ref=ref),
    )
