"""Host selection, binding, and execution for measurement transforms.

The graph owns pure semantic meaning and typed logical input/output edges.
Host callables are selected separately, after linking and before any producer
effect. Runtime execution extends canonical logical value candidates directly;
only the RunProgram boundary closes the complete value inventory.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.execution.points import RunPoint
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import (
    CheckFailed,
    MeasurementTransformExecutionError,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.measurements.transform_model import (
    MeasurementTransformDef,
    MeasurementTransformInputPort,
    MeasurementTransformOutputPort,
    NativeMeasurementTransformId,
)
from scopecat.measurements.transform_verification import (
    VerifiedMeasurementTransformGraph,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
)
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.records.parameter import Quantity

type MeasurementTransformColumn = tuple[MeasurementValue, ...]
type MeasurementTransformPortValues = Mapping[str, MeasurementTransformColumn]
type HostMeasurementTransformKernel = Callable[
    ["HostMeasurementTransformCall"],
    Mapping[str, Sequence[MeasurementValue]],
]
type HostMeasurementTransformValidator = Callable[["MeasurementTransformDef"], None]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformImplementation:
    """Transient host callable sidecar for one semantic family and rate."""

    id: str
    semantic_id: str
    semantic_version: str
    implementation_fingerprint: str
    validate_transform: HostMeasurementTransformValidator = field(
        repr=False,
        compare=False,
    )
    kernel: HostMeasurementTransformKernel = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        fields = (
            self.id,
            self.semantic_id,
            self.semantic_version,
            self.implementation_fingerprint,
        )
        if not all(fields):
            msg = "host measurement transform implementation fields must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformCall:
    """One batch invocation over canonical logical point columns."""

    transform_id: NativeMeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    points: tuple[RunPoint, ...]
    input_ports: tuple[MeasurementTransformInputPort, ...]
    output_ports: tuple[MeasurementTransformOutputPort, ...]
    inputs: MeasurementTransformPortValues

    def __post_init__(self) -> None:
        if len({port.id for port in self.input_ports}) != len(self.input_ports):
            msg = "host transform call input port ids must be unique"
            raise ValueError(msg)
        if len({port.id for port in self.output_ports}) != len(self.output_ports):
            msg = "host transform call output port ids must be unique"
            raise ValueError(msg)
        input_candidates = dict(self.inputs)
        if set(input_candidates) != {port.id for port in self.input_ports}:
            msg = "host transform call inputs must exactly match its input ports"
            raise ValueError(msg)
        if any(len(values) != len(self.points) for values in input_candidates.values()):
            msg = "host transform input columns must match the point count"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(
                {
                    port_id: tuple(
                        validated_measurement_value_copy(value) for value in values
                    )
                    for port_id, values in input_candidates.items()
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class SelectedHostMeasurementTransforms:
    """Exact host implementation selection for a verified graph."""

    graph: VerifiedMeasurementTransformGraph = field(repr=False)
    implementations: tuple[HostMeasurementTransformImplementation, ...]
    contract_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        implementations = tuple(self.implementations)
        if len(implementations) != len(self.graph.transforms):
            msg = "every measurement transform must have one host implementation"
            raise ValueError(msg)
        for transform, implementation in zip(
            self.graph.transforms,
            implementations,
            strict=True,
        ):
            if (
                implementation.semantic_id != transform.semantic.id
                or implementation.semantic_version != transform.semantic.version
            ):
                msg = "host implementation does not match its measurement transform"
                raise ValueError(msg)
        object.__setattr__(self, "implementations", implementations)
        object.__setattr__(
            self,
            "contract_fingerprint",
            _host_selection_fingerprint(self.graph, implementations),
        )


@dataclass(frozen=True, slots=True)
class BoundHostMeasurementTransforms:
    """Selected pure transform graph with its direct logical source inventory."""

    selection: SelectedHostMeasurementTransforms = field(repr=False)
    source_product_use_ids: tuple[ProductUseId, ...]
    contract_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        source_ids = tuple(self.source_product_use_ids)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("host transform source product uses must be unique")
        produced = {
            use_id
            for transform in self.selection.graph.transforms
            for output in transform.outputs
            for use_id in output.product_use_ids
        }
        required_sources = {
            input_port.product_use_id
            for transform in self.selection.graph.transforms
            for input_port in transform.inputs
            if input_port.product_use_id not in produced
        }
        if not required_sources.issubset(source_ids):
            raise ValueError("host transform sources do not cover graph inputs")
        object.__setattr__(
            self,
            "contract_fingerprint",
            stable_content_hash(
                content_fingerprint(
                    {
                        "schema": "scopecat.bound_host_measurement_transforms.v2",
                        "selection_contract_fingerprint": (
                            self.selection.contract_fingerprint
                        ),
                        "source_product_use_ids": [item.value for item in source_ids],
                    }
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutedHostMeasurementTransforms:
    """Canonical direct and derived logical value candidates."""

    plan: BoundHostMeasurementTransforms = field(repr=False)
    values: tuple[MeasurementValueCandidate, ...]


def select_host_measurement_transforms(
    graph: VerifiedMeasurementTransformGraph,
    implementations: Sequence[HostMeasurementTransformImplementation],
) -> SelectedHostMeasurementTransforms:
    """Select one registered implementation for every transform semantic."""

    selected_graph = graph
    candidates = tuple(implementations)
    problems: list[Problem] = []
    implementation_counts = Counter(candidate.id for candidate in candidates)
    implementations_by_contract: dict[
        tuple[str, str], HostMeasurementTransformImplementation
    ] = {}
    for implementation_index, candidate in enumerate(candidates):
        if implementation_counts[candidate.id] > 1:
            problems.append(
                _check_problem(
                    "measurement_transform_host_implementation_id_duplicate",
                    f"host implementation id {candidate.id!r} is duplicated",
                    path=("implementations", implementation_index, "id"),
                    category=ProblemCategory.CONFLICT,
                )
            )
        contract = (candidate.semantic_id, candidate.semantic_version)
        if contract in implementations_by_contract:
            problems.append(
                _check_problem(
                    "measurement_transform_host_implementation_contract_duplicate",
                    (
                        f"semantic implementation {contract!r} is registered "
                        "more than once"
                    ),
                    path=("implementations", implementation_index),
                    category=ProblemCategory.CONFLICT,
                )
            )
        else:
            implementations_by_contract[contract] = candidate

    selected: list[HostMeasurementTransformImplementation] = []
    for transform_index, transform in enumerate(selected_graph.transforms):
        implementation = implementations_by_contract.get(
            (transform.semantic.id, transform.semantic.version)
        )
        if implementation is None:
            problems.append(
                _check_problem(
                    "measurement_transform_host_implementation_missing",
                    f"measurement transform {transform.id.value!r} has no registered "
                    "semantic implementation",
                    path=("transforms", transform_index, "implementation"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        try:
            validation_result = _invoke_transform_validator(
                implementation.validate_transform,
                transform,
            )
        except Exception as error:
            problems.append(
                _check_problem(
                    "measurement_transform_host_capability_rejected",
                    f"host implementation {implementation.id!r} rejected transform "
                    f"{transform.id.value!r}",
                    path=("transforms", transform_index, "implementation"),
                    category=ProblemCategory.UNAVAILABLE,
                    details={"error_type": _type_name(error)},
                )
            )
            continue
        if validation_result is not None:
            problems.append(
                _check_problem(
                    "measurement_transform_host_validator_result_invalid",
                    f"host implementation {implementation.id!r} validator must "
                    "return None",
                    path=("transforms", transform_index, "implementation"),
                    category=ProblemCategory.CONFLICT,
                )
            )
            continue
        selected.append(implementation)
    if problems:
        raise CheckFailed(problems)
    selected_tuple = tuple(selected)
    return SelectedHostMeasurementTransforms(
        selected_graph,
        selected_tuple,
    )


def bind_host_measurement_transforms(
    selection: SelectedHostMeasurementTransforms,
    source_product_use_ids: Sequence[ProductUseId],
) -> BoundHostMeasurementTransforms:
    """Bind a selected transform graph to its direct logical source uses."""

    return BoundHostMeasurementTransforms(selection, tuple(source_product_use_ids))


def execute_host_measurement_transforms(
    plan: BoundHostMeasurementTransforms,
    source_values: Sequence[MeasurementValueCandidate],
    *,
    points: Sequence[RunPoint],
) -> ExecutedHostMeasurementTransforms:
    """Execute each transform once over canonical logical point columns."""

    bound = plan
    supplied = tuple(source_values)
    points = tuple(points)
    expected_keys = {
        (point.logical_id, use_id)
        for point in points
        for use_id in bound.source_product_use_ids
    }
    value_by_output: dict[
        tuple[LogicalPointId, ProductUseId], MeasurementValueCandidate
    ] = {}
    problems: list[Problem] = []
    for candidate_index, candidate in enumerate(supplied):
        key = (candidate.logical_point_id, candidate.product_use_id)
        if key in value_by_output:
            problems.append(
                _execution_problem(
                    "measurement_transform_source_value_duplicate",
                    "host transform sources repeat one logical point/use value",
                    path=("source_values", candidate_index),
                    category=ProblemCategory.CONFLICT,
                )
            )
        elif key not in expected_keys:
            problems.append(
                _execution_problem(
                    "measurement_transform_source_value_unexpected",
                    "host transform source is outside its logical inventory",
                    path=("source_values", candidate_index),
                    category=ProblemCategory.INVALID_INPUT,
                )
            )
        else:
            value_by_output[key] = candidate
    for logical_point_id, product_use_id in expected_keys - set(value_by_output):
        problems.append(
            _execution_problem(
                "measurement_transform_source_value_missing",
                "host transform source is missing one logical point/use value",
                path=("source_values", logical_point_id.value, product_use_id.value),
                category=ProblemCategory.INVALID_INPUT,
            )
        )
    if problems:
        raise MeasurementTransformExecutionError(problems)
    if not points:
        return ExecutedHostMeasurementTransforms(bound, supplied)

    derived_values: list[MeasurementValueCandidate] = []
    for transform, implementation in zip(
        bound.selection.graph.transforms,
        bound.selection.implementations,
        strict=True,
    ):
        try:
            inputs = {
                port.id: tuple(
                    value_by_output[(point.logical_id, port.product_use_id)].value
                    for point in points
                )
                for port in transform.inputs
            }
        except KeyError as error:
            msg = "bound measurement transform plan lost one closed graph input"
            raise AssertionError(msg) from error
        call = HostMeasurementTransformCall(
            transform_id=transform.id,
            semantic=transform.semantic,
            points=points,
            input_ports=transform.inputs,
            output_ports=transform.outputs,
            inputs=inputs,
        )
        try:
            raw_candidate = _invoke_host_kernel(implementation.kernel, call)
        except Exception as error:
            logger.error(  # noqa: TRY400
                "host measurement transform kernel raised",
                extra={
                    "transform_id": transform.id.value,
                    "implementation_id": implementation.id,
                    "semantic_id": transform.semantic.id,
                    "point_count": len(points),
                    "exception_type": _type_name(error),
                    "problem_code": "measurement_transform_host_kernel_failed",
                },
            )
            raise MeasurementTransformExecutionError(
                (
                    _execution_problem(
                        "measurement_transform_host_kernel_failed",
                        f"host implementation for transform "
                        f"{transform.id.value!r} raised",
                        path=("transforms", transform.id.value, "kernel"),
                        details={
                            "exception_type": _type_name(error),
                            "transform_id": transform.id.value,
                            "implementation_id": implementation.id,
                            "semantic_id": transform.semantic.id,
                            "point_count": len(points),
                        },
                        category=ProblemCategory.EXTERNAL_FAILURE,
                    ),
                )
            ) from error
        try:
            raw_outputs = _materialize_kernel_outputs(raw_candidate)
        except Exception as error:
            raise MeasurementTransformExecutionError(
                (
                    _execution_problem(
                        "measurement_transform_host_output_container_invalid",
                        "host measurement transform returned unreadable outputs",
                        path=("transforms", transform.id.value, "outputs"),
                        details={"exception_type": _type_name(error)},
                        category=ProblemCategory.OPERATION,
                    ),
                )
            ) from error
        expected_port_ids = {port.id for port in transform.outputs}
        actual_port_ids = set(raw_outputs)
        if actual_port_ids != expected_port_ids:
            raise MeasurementTransformExecutionError(
                (
                    _execution_problem(
                        "measurement_transform_host_output_inventory_mismatch",
                        f"host transform {transform.id.value!r} returned a "
                        "non-exact output port inventory",
                        path=("transforms", transform.id.value, "outputs"),
                        details={
                            "expected": sorted(expected_port_ids),
                            "actual": sorted(repr(item) for item in actual_port_ids),
                        },
                        category=ProblemCategory.OPERATION,
                    ),
                )
            )
        candidates: list[MeasurementValueCandidate] = []
        for port in transform.outputs:
            column = raw_outputs[port.id]
            if not isinstance(column, Sequence) or isinstance(column, str | bytes):
                raise MeasurementTransformExecutionError(
                    (
                        _execution_problem(
                            "measurement_transform_host_output_column_invalid",
                            f"host transform output {port.id!r} is not a value column",
                            path=("transforms", transform.id.value, "outputs", port.id),
                            category=ProblemCategory.OPERATION,
                        ),
                    )
                )
            values = tuple(column)
            if len(values) != len(points):
                raise MeasurementTransformExecutionError(
                    (
                        _execution_problem(
                            "measurement_transform_host_output_column_length_mismatch",
                            f"host transform output {port.id!r} does not cover "
                            "every point",
                            path=("transforms", transform.id.value, "outputs", port.id),
                            details={"expected": len(points), "actual": len(values)},
                            category=ProblemCategory.OPERATION,
                        ),
                    )
                )
            for point, value in zip(points, values, strict=True):
                if not _is_measurement_value(value):
                    raise MeasurementTransformExecutionError(
                        (
                            _execution_problem(
                                "measurement_transform_host_output_carrier_invalid",
                                f"host transform output {port.id!r} is not a "
                                "MeasurementValue",
                                path=(
                                    "transforms",
                                    transform.id.value,
                                    "outputs",
                                    port.id,
                                    point.logical_ordinal,
                                ),
                                category=ProblemCategory.OPERATION,
                            ),
                        )
                    )
                issues = measurement_value_contract_issues(
                    cast("MeasurementValue", value),
                    expected_dtype=port.product.dtype,
                    expected_unit=port.product.unit,
                    expected_shape=tuple(axis.size for axis in port.product.axes),
                )
                if issues:
                    raise MeasurementTransformExecutionError(
                        tuple(
                            _execution_problem(
                                f"measurement_transform_host_output_{issue.code.value}",
                                f"host transform output {port.id!r} does not satisfy "
                                "its logical product contract",
                                path=(
                                    "transforms",
                                    transform.id.value,
                                    "outputs",
                                    port.id,
                                    point.logical_ordinal,
                                    *issue.path,
                                ),
                                details={
                                    "expected": _problem_detail(issue.expected),
                                    "actual": _problem_detail(issue.actual),
                                },
                                category=ProblemCategory.OPERATION,
                            )
                            for issue in issues
                        )
                    )
                candidates.extend(
                    MeasurementValueCandidate(
                        logical_point_id=point.logical_id,
                        product_use_id=use_id,
                        value=cast("MeasurementValue", value),
                    )
                    for use_id in port.product_use_ids
                )
        derived_values.extend(candidates)
        value_by_output.update(
            {
                (value.logical_point_id, value.product_use_id): value
                for value in candidates
            }
        )

    return ExecutedHostMeasurementTransforms(bound, (*supplied, *derived_values))


def _host_selection_fingerprint(
    graph: VerifiedMeasurementTransformGraph,
    implementations: Sequence[HostMeasurementTransformImplementation],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.host_measurement_transform_selection.v1",
                "graph_contract_fingerprint": graph.contract_fingerprint,
                "implementations": [
                    {
                        "transform_id": transform.id.value,
                        "implementation_id": implementation.id,
                        "implementation_fingerprint": (
                            implementation.implementation_fingerprint
                        ),
                        "semantic_id": implementation.semantic_id,
                        "semantic_version": implementation.semantic_version,
                    }
                    for transform, implementation in zip(
                        graph.transforms,
                        implementations,
                        strict=True,
                    )
                ],
            }
        )
    )


def _check_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("measurement_transforms", *path),
        category=category,
        details=details,
    )


def _execution_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object] | None = None,
    category: ProblemCategory,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.EXECUTION,
        location=model_location("measurement_transforms", *path),
        details=details,
    )


def _type_name(value: object) -> str:
    return f"{type(value).__module__}.{type(value).__qualname__}"


def _problem_detail(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return [_problem_detail(item) for item in selected]
    return repr(value)


def _invoke_host_kernel(
    kernel: HostMeasurementTransformKernel,
    call: HostMeasurementTransformCall,
) -> object:
    """Erase the static return contract so runtime provider checks stay real."""

    return kernel(call)


def _invoke_transform_validator(
    validator: HostMeasurementTransformValidator,
    transform: MeasurementTransformDef,
) -> object:
    """Erase the static result so the callback contract is checked at runtime."""

    return validator(transform)


def _materialize_kernel_outputs(value: object) -> dict[str, object]:
    """Read an untrusted callback mapping entirely inside one exception boundary."""

    if not isinstance(value, Mapping):
        msg = "host measurement transform outputs must be a mapping"
        raise TypeError(msg)
    mapping = cast("Mapping[object, object]", value)
    items = tuple(mapping.items())
    outputs: dict[str, object] = {}
    for port_id, output in items:
        if not isinstance(port_id, str):
            msg = "host measurement transform output ids must be strings"
            raise TypeError(msg)
        if port_id in outputs:
            msg = "host measurement transform output ids must be unique"
            raise ValueError(msg)
        outputs[port_id] = output
    return outputs


def _is_measurement_value(value: object) -> bool:
    if not isinstance(
        value,
        Quantity | ComplexQuantity | MeasurementArray,
    ):
        return False
    try:
        validated_measurement_value_copy(value)
    except (TypeError, ValueError):
        return False
    return True


__all__ = [
    "BoundHostMeasurementTransforms",
    "ExecutedHostMeasurementTransforms",
    "HostMeasurementTransformCall",
    "HostMeasurementTransformImplementation",
    "HostMeasurementTransformKernel",
    "HostMeasurementTransformValidator",
    "MeasurementTransformExecutionError",
    "MeasurementTransformPortValues",
    "SelectedHostMeasurementTransforms",
    "bind_host_measurement_transforms",
    "execute_host_measurement_transforms",
    "select_host_measurement_transforms",
]
