"""Test-local signal workflow fixtures.

These helpers intentionally live outside the production package so core
workflow code can be tested without depending on a bundled demo domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard, cast

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
    Dataset,
    MeasurementDatasetSchema,
    MeasurementScalar,
    Variable,
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
    best_signal: MeasurementScalar
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
        measurements = context.measurements(
            self.selector or RAW_MEASUREMENTS_DATASET_ID
        )
        input_ref = dataset_storage_ref(measurements.entry)
        result = _build_summary_result(
            run_id=context.run.id,
            step=SUMMARY_STATS_STEP,
            input_ref=input_ref,
            measurements=measurements,
        )
        return (
            context.result("summary stats")
            .input(
                measurements.entry.id,
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
        measurements = context.measurements(RAW_MEASUREMENTS_DATASET_ID)
        parameter_id = _scan_parameter_id(measurements.schema)
        old_value = _old_parameter_value(context.config, parameter_id)
        best_position = _best_signal_position(measurements)
        signal = measurements.data_vars["signal"]
        parameter = measurements.coords[parameter_id]
        proposed_value = _proposed_value(
            parameter,
            parameter.values[best_position],
            parameter_id,
            old_value=old_value,
        )
        best_signal = _signal_scalar(
            variable=signal,
            value=signal.values[best_position],
            problem_ref=BEST_SIGNAL_INPUT_REF,
        )
        best_point_index = measurements.point_indices[best_position]
        reason = f"Best signal observed at point {best_point_index}."
        result = BestSignalAnalysisResult(
            run_id=context.run.id,
            parameter_id=parameter_id,
            best_point_index=best_point_index,
            best_signal=best_signal,
            old_value=old_value,
            proposed_value=proposed_value,
        )
        return (
            context.result("best signal analysis")
            .input(
                measurements.entry.id,
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
                confidence=_numeric_scalar_value(best_signal),
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
    measurements: Dataset,
) -> SummaryStatsResult:
    accumulators: dict[str, _Accumulator] = {}
    for name, observable in measurements.data_vars.items():
        for value, unavailable_reason in zip(
            observable.values,
            observable.availability,
            strict=True,
        ):
            values, unit = _numeric_observable_values(
                name=name,
                variable=observable,
                value=value,
                unavailable_reason=unavailable_reason,
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
    variable: Variable,
    value: object,
    unavailable_reason: str | None,
    problem_ref: str,
) -> tuple[list[float], str]:
    if unavailable_reason is not None:
        raise CheckFailed(
            [
                _problem(
                    "invalid_analysis_input",
                    f"observable {name} is unavailable ({unavailable_reason})",
                    problem_ref,
                )
            ]
        )
    unit = variable.unit
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
    if variable.dtype not in {"float64", "int64"}:
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
        values = _flatten_numeric_values(value)
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


def _flatten_numeric_values(value: object) -> list[float]:
    if isinstance(value, tuple):
        nested = cast("tuple[object, ...]", value)
        return [
            selected for item in nested for selected in _flatten_numeric_values(item)
        ]
    if not isinstance(value, bool) and isinstance(value, int | float):
        return [float(value)]
    raise ValueError("measurement value is not numeric")


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


def _best_signal_position(measurements: Dataset) -> int:
    try:
        signal = measurements.data_vars["signal"]
    except KeyError as error:
        raise CheckFailed(
            [
                _problem(
                    "missing_signal_observable",
                    "analysis input contains no signal observable",
                    BEST_SIGNAL_INPUT_REF,
                )
            ]
        ) from error
    candidates = [
        (position, float(value))
        for position, (value, unavailable_reason) in enumerate(
            zip(signal.values, signal.availability, strict=True)
        )
        if unavailable_reason is None and _is_numeric_value(value)
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
        key=lambda candidate: (
            candidate[1],
            -measurements.point_indices[candidate[0]],
        ),
    )[0]


def _signal_scalar(
    *,
    variable: Variable,
    value: object,
    problem_ref: str,
) -> MeasurementScalar:
    if (
        variable.dims == ("point",)
        and variable.dtype in {"float64", "int64"}
        and _is_numeric_value(value)
    ):
        return MeasurementScalar.create(
            value=value,
            dtype=variable.dtype,
            unit=variable.unit,
        )
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
    variable: Variable,
    value: object,
    parameter_id: str,
    *,
    old_value: Quantity,
) -> Quantity:
    if (
        variable.dims != ("point",)
        or variable.unit is None
        or not _is_numeric_value(value)
    ):
        raise CheckFailed(
            [
                _problem(
                    "missing_parameter_value",
                    f"best point parameter {parameter_id} has no unit",
                    BEST_SIGNAL_INPUT_REF,
                )
            ]
        )
    quantity = Quantity(
        value=float(value),
        unit=variable.unit,
    )
    if quantity != old_value:
        return quantity
    # The symmetric fake signal peaks at the current center. Keep the analysis
    # fixture useful as a proposal workflow by producing a small next-fit update.
    return Quantity(value=old_value.value + 0.01, unit=old_value.unit)


def _numeric_scalar_value(value: MeasurementScalar) -> float:
    selected = value.value
    if (
        value.dtype not in {"float64", "int64"}
        or isinstance(selected, bool)
        or not isinstance(selected, int | float)
    ):
        raise ValueError("measurement scalar must be numeric")
    return float(selected)


def _is_numeric_value(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)


def _problem(code: str, message: str, ref: str) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.ANALYSIS,
        location=StorageLocation(ref=ref),
    )
