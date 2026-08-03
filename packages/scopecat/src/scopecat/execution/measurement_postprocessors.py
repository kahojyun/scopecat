"""Execute point-local measurement postprocessors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.bound_facts import BoundMeasurementPostprocessor
from scopecat.kernel.errors import MeasurementPostprocessorExecutionError
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem, ProblemPhase, model_location, problem
from scopecat.measurements.contracts import measurement_value_contract_issues
from scopecat.measurements.points import RunPoint
from scopecat.measurements.postprocessor_contract import (
    MeasurementPostprocessorKernel,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    MeasurementValueCatalog,
)
from scopecat.records.measurement import MeasurementUnavailable


def execute_measurement_postprocessors(
    postprocessors: Sequence[BoundMeasurementPostprocessor],
    candidates: Sequence[MeasurementValueCandidate],
    *,
    points: Sequence[RunPoint],
    catalog: MeasurementValueCatalog,
) -> tuple[MeasurementValueCandidate, ...]:
    """Run each live postprocessor in dependency order per logical point."""

    supplied = tuple(candidates)
    product_by_id = {product.id: product for product in catalog.product_defs}
    candidates_by_key: dict[tuple[object, object], list[MeasurementValueCandidate]] = {}
    for candidate in supplied:
        candidates_by_key.setdefault(
            (candidate.logical_point_id, candidate.product_use_id),
            [],
        ).append(candidate)

    derived: list[MeasurementValueCandidate] = []
    for postprocessor in postprocessors:
        for point in points:
            source = candidates_by_key.get(
                (point.logical_id, postprocessor.input_product_use_id),
                [],
            )
            if len(source) != 1:
                code = (
                    "measurement_postprocessor_input_missing"
                    if not source
                    else "measurement_postprocessor_input_duplicate"
                )
                raise MeasurementPostprocessorExecutionError(
                    (
                        _execution_problem(
                            code,
                            "measurement postprocessor requires exactly one input "
                            "value for each logical point",
                            postprocessor=postprocessor,
                            point_index=point.logical_ordinal,
                        ),
                    )
                )
            source_value = source[0].value
            if isinstance(source_value, MeasurementUnavailable):
                # The compiled graph owns lineage; value metadata carries source
                # diagnostics through transformations that could not run.
                outputs = {
                    output.id: MeasurementUnavailable.create(
                        reason=source_value.reason,
                        dtype=product_by_id[output.product_id].dtype,
                        unit=product_by_id[output.product_id].unit,
                        shape=tuple(
                            axis.size for axis in product_by_id[output.product_id].axes
                        ),
                        metadata=source_value.metadata,
                    )
                    for output in postprocessor.outputs
                }
            else:
                try:
                    outputs = postprocessor.kernel(source_value)
                except Exception as error:
                    raise MeasurementPostprocessorExecutionError(
                        (
                            _execution_problem(
                                "measurement_postprocessor_kernel_failed",
                                f"measurement postprocessor "
                                f"{postprocessor.id.qualified_name!r} raised",
                                postprocessor=postprocessor,
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

            for output in postprocessor.outputs:
                try:
                    value = outputs[output.id]
                except (KeyError, TypeError) as error:
                    raise MeasurementPostprocessorExecutionError(
                        (
                            _execution_problem(
                                "measurement_postprocessor_output_missing",
                                f"measurement postprocessor output {output.id!r} "
                                "is missing",
                                postprocessor=postprocessor,
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
                    raise MeasurementPostprocessorExecutionError(
                        tuple(
                            _execution_problem(
                                f"measurement_postprocessor_output_{issue.code.value}",
                                f"measurement postprocessor output {output.id!r} "
                                "does not satisfy its product contract",
                                postprocessor=postprocessor,
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
                        evidence=source[0].evidence,
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
    postprocessor: BoundMeasurementPostprocessor,
    point_index: int,
    path: tuple[str | int, ...] = (),
    details: Mapping[str, JsonValue] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location(
            "measurement_postprocessors",
            postprocessor.id.qualified_name,
            *path,
        ),
        details={
            "postprocessor_id": postprocessor.id.qualified_name,
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
    "MeasurementPostprocessorKernel",
    "execute_measurement_postprocessors",
]
