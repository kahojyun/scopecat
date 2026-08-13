"""Execute point-local measurement computes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.bound_facts import BoundMeasurementCompute
from scopecat.kernel.errors import ComputeExecutionError
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem, ProblemPhase, model_location, problem
from scopecat.measurements.contracts import measurement_value_contract_issues
from scopecat.measurements.points import AcceptedRunPoint
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    MeasurementValueCatalog,
)
from scopecat.program.measurement_contracts import (
    MeasurementComputeKernel,
)
from scopecat.records.measurement import MeasurementUnavailable


def execute_measurement_computes(
    computes: Sequence[BoundMeasurementCompute],
    candidates: Sequence[MeasurementValueCandidate],
    *,
    points: Sequence[AcceptedRunPoint],
    catalog: MeasurementValueCatalog,
    value_candidates: Sequence[ValueRecordCandidate] = (),
) -> tuple[MeasurementValueCandidate, ...]:
    """Run each live measurement compute in dependency order per logical point."""

    supplied = tuple(candidates)
    product_by_id = {product.id: product for product in catalog.product_defs}
    candidates_by_key: dict[tuple[object, object], list[MeasurementValueCandidate]] = {}
    for candidate in supplied:
        candidates_by_key.setdefault(
            (candidate.logical_point_id, candidate.product_use_id),
            [],
        ).append(candidate)
    values_by_key = {
        (candidate.logical_point_id, candidate.value_id): candidate.value
        for candidate in value_candidates
    }

    derived: list[MeasurementValueCandidate] = []
    for compute in computes:
        for point in points:
            sources: dict[str, MeasurementValueCandidate] = {}
            for input_binding in compute.inputs:
                source = candidates_by_key.get(
                    (point.logical_id, input_binding.product_use_id),
                    [],
                )
                if len(source) != 1:
                    code = (
                        "compute_input_missing"
                        if not source
                        else "compute_input_duplicate"
                    )
                    raise ComputeExecutionError(
                        (
                            _execution_problem(
                                code,
                                "point-local compute requires exactly one "
                                "value for each named input and logical point",
                                compute=compute,
                                point_index=point.logical_ordinal,
                                path=("inputs", input_binding.id),
                            ),
                        )
                    )
                sources[input_binding.id] = source[0]
            unavailable = next(
                (
                    source.value
                    for source in sources.values()
                    if isinstance(source.value, MeasurementUnavailable)
                ),
                None,
            )
            if isinstance(unavailable, MeasurementUnavailable):
                # The compiled graph owns lineage; value metadata carries source
                # diagnostics through transformations that could not run.
                outputs = {
                    output.id: MeasurementUnavailable.create(
                        reason=unavailable.reason,
                        dtype=product_by_id[output.product_id].dtype,
                        unit=product_by_id[output.product_id].unit,
                        shape=tuple(
                            axis.size for axis in product_by_id[output.product_id].axes
                        ),
                        metadata=unavailable.metadata,
                    )
                    for output in compute.outputs
                }
            else:
                try:
                    early_values = {
                        binding.id: values_by_key[(point.logical_id, binding.value_id)]
                        for binding in compute.value_inputs
                    }
                except KeyError as error:
                    missing = next(
                        binding
                        for binding in compute.value_inputs
                        if (point.logical_id, binding.value_id) not in values_by_key
                    )
                    raise ComputeExecutionError(
                        (
                            _execution_problem(
                                "compute_value_input_missing",
                                "point-local compute requires one value for "
                                "each early input and logical point",
                                compute=compute,
                                point_index=point.logical_ordinal,
                                path=("value_inputs", missing.id),
                            ),
                        )
                    ) from error
                try:
                    outputs = compute.kernel(
                        {
                            **{name: source.value for name, source in sources.items()},
                            **early_values,
                        }
                    )
                except Exception as error:
                    raise ComputeExecutionError(
                        (
                            _execution_problem(
                                "compute_kernel_failed",
                                f"point-local compute "
                                f"{compute.id.qualified_name!r} raised",
                                compute=compute,
                                point_index=point.logical_ordinal,
                                details={
                                    "exception_type": (
                                        f"{type(error).__module__}."
                                        f"{type(error).__qualname__}"
                                    )
                                },
                            ),
                        )
                    ) from error

            for output in compute.outputs:
                try:
                    value = outputs[output.id]
                except (KeyError, TypeError) as error:
                    raise ComputeExecutionError(
                        (
                            _execution_problem(
                                "compute_output_missing",
                                f"point-local compute output {output.id!r} is missing",
                                compute=compute,
                                point_index=point.logical_ordinal,
                            ),
                        )
                    ) from error
                product = product_by_id[output.product_id]
                issues = measurement_value_contract_issues(
                    value,
                    expected_dtype=product.dtype,
                    expected_unit=product.unit,
                    expected_shape=tuple(axis.size for axis in product.axes),
                )
                if issues:
                    raise ComputeExecutionError(
                        tuple(
                            _execution_problem(
                                f"compute_output_{issue.code.value}",
                                f"point-local compute output {output.id!r} "
                                "does not satisfy its product contract",
                                compute=compute,
                                point_index=point.logical_ordinal,
                                path=("outputs", output.id, *issue.path),
                                details={
                                    "expected": _problem_detail(issue.expected),
                                    "actual": _problem_detail(issue.actual),
                                },
                            )
                            for issue in issues
                        )
                    )
                produced = tuple(
                    MeasurementValueCandidate(
                        logical_point_id=point.logical_id,
                        product_use_id=use_id,
                        value=value,
                        evidence=next(
                            (
                                source.evidence
                                for source in sources.values()
                                if source.evidence is not None
                            ),
                            None,
                        ),
                    )
                    for use_id in output.product_use_ids
                )
                derived.extend(produced)
                for candidate in produced:
                    candidates_by_key.setdefault(
                        (candidate.logical_point_id, candidate.product_use_id),
                        [],
                    ).append(candidate)
    return (*supplied, *derived)


def _execution_problem(
    code: str,
    message: str,
    *,
    compute: BoundMeasurementCompute,
    point_index: int,
    path: tuple[str | int, ...] = (),
    details: Mapping[str, JsonValue] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location(
            "measurement_computes",
            compute.id.qualified_name,
            *path,
        ),
        details={
            "compute_id": compute.id.qualified_name,
            "point_index": point_index,
            **({} if details is None else details),
        },
    )


def _problem_detail(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, tuple):
        return [_problem_detail(item) for item in cast("tuple[object, ...]", value)]
    return repr(value)


__all__ = [
    "MeasurementComputeKernel",
    "execute_measurement_computes",
]
