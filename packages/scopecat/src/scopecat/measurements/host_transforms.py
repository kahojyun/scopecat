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
from scopecat.measurements.semantics import (
    MeasurementTransformRate,
    MeasurementTransformSemanticContract,
)
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

type MeasurementTransformPortValues = Mapping[str, MeasurementValue]
type HostMeasurementTransformKernel = Callable[
    ["HostMeasurementTransformCall"],
    Mapping[str, MeasurementValue],
]
type HostMeasurementTransformValidator = Callable[["MeasurementTransformDef"], None]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformImplementation:
    """Transient host callable sidecar for one semantic family and rate."""

    id: str
    semantic_id: str
    semantic_version: str
    rate: MeasurementTransformRate
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
        if self.rate != "point":
            msg = "host measurement transform rate must be point"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformImplementationBinding:
    """Explicit selection of one implementation for one transform identity."""

    transform_id: NativeMeasurementTransformId
    implementation_id: str

    def __post_init__(self) -> None:
        if not self.implementation_id:
            msg = "host implementation binding id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformCall:
    """Point-local invocation with copied measurement inputs for a host kernel."""

    transform_id: NativeMeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    logical_point_id: LogicalPointId
    point_index: int
    input_ports: tuple[MeasurementTransformInputPort, ...]
    output_ports: tuple[MeasurementTransformOutputPort, ...]
    inputs: Mapping[str, MeasurementValue]

    def __post_init__(self) -> None:
        if self.point_index < 0:
            msg = "host transform call point_index must be a non-negative integer"
            raise ValueError(msg)
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
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(
                {
                    port_id: validated_measurement_value_copy(value)
                    for port_id, value in input_candidates.items()
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
                or implementation.rate != transform.rate
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
    bindings: Sequence[HostMeasurementTransformImplementationBinding],
) -> SelectedHostMeasurementTransforms:
    """Select explicitly bound host implementations for every POINT transform."""

    selected_graph = graph
    candidates = tuple(implementations)
    supplied_bindings = tuple(bindings)

    problems: list[Problem] = []
    implementation_counts = Counter(candidate.id for candidate in candidates)
    implementations_by_id: dict[str, HostMeasurementTransformImplementation] = {}
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
        implementations_by_id.setdefault(candidate.id, candidate)

    transforms_by_id = {
        transform.id: transform for transform in selected_graph.transforms
    }
    binding_counts = Counter(binding.transform_id for binding in supplied_bindings)
    binding_by_transform: dict[
        NativeMeasurementTransformId,
        HostMeasurementTransformImplementationBinding,
    ] = {}
    for binding_index, binding in enumerate(supplied_bindings):
        if binding_counts[binding.transform_id] > 1:
            problems.append(
                _check_problem(
                    "measurement_transform_host_binding_duplicate",
                    f"transform {binding.transform_id.value!r} has multiple host "
                    "implementation bindings",
                    path=("implementation_bindings", binding_index),
                    category=ProblemCategory.CONFLICT,
                )
            )
        if binding.transform_id not in transforms_by_id:
            problems.append(
                _check_problem(
                    "measurement_transform_host_binding_unknown_transform",
                    f"host implementation binding references unknown transform "
                    f"{binding.transform_id.value!r}",
                    path=(
                        "implementation_bindings",
                        binding_index,
                        "transform_id",
                    ),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        binding_by_transform.setdefault(binding.transform_id, binding)
        if binding.implementation_id not in implementations_by_id:
            problems.append(
                _check_problem(
                    "measurement_transform_host_binding_unknown_implementation",
                    f"transform {binding.transform_id.value!r} selects unknown host "
                    f"implementation {binding.implementation_id!r}",
                    path=(
                        "implementation_bindings",
                        binding_index,
                        "implementation_id",
                    ),
                    category=ProblemCategory.NOT_FOUND,
                )
            )

    selected: list[HostMeasurementTransformImplementation] = []
    for transform_index, transform in enumerate(selected_graph.transforms):
        binding = binding_by_transform.get(transform.id)
        if binding is None:
            problems.append(
                _check_problem(
                    "measurement_transform_host_binding_missing",
                    f"measurement transform {transform.id.value!r} has no explicit "
                    "host implementation binding",
                    path=("transforms", transform_index, "implementation"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        implementation = implementations_by_id.get(binding.implementation_id)
        if implementation is None:
            continue
        if (
            implementation.semantic_id != transform.semantic.id
            or implementation.semantic_version != transform.semantic.version
            or implementation.rate != transform.rate
        ):
            problems.append(
                _check_problem(
                    "measurement_transform_host_implementation_incompatible",
                    f"host implementation {implementation.id!r} does not match "
                    f"transform {transform.id.value!r} semantic family, version, "
                    "and rate",
                    path=("transforms", transform_index, "implementation"),
                    category=ProblemCategory.CONFLICT,
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
) -> ExecutedHostMeasurementTransforms:
    """Execute POINT kernels in graph order over logical value candidates."""

    bound = plan
    supplied = tuple(source_values)
    points = bound.selection.graph.catalog.point_catalog.points
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

    derived_values: list[MeasurementValueCandidate] = []
    for transform, implementation in zip(
        bound.selection.graph.transforms,
        bound.selection.implementations,
        strict=True,
    ):
        candidates: list[MeasurementValueCandidate] = []
        for point in points:
            try:
                inputs = {
                    port.id: value_by_output[
                        (point.logical_id, port.product_use_id)
                    ].value
                    for port in transform.inputs
                }
            except KeyError as error:
                msg = "bound measurement transform plan lost one closed graph input"
                raise AssertionError(msg) from error
            call = HostMeasurementTransformCall(
                transform_id=transform.id,
                semantic=transform.semantic,
                logical_point_id=point.logical_id,
                point_index=point.logical_ordinal,
                input_ports=transform.inputs,
                output_ports=transform.outputs,
                inputs=inputs,
            )
            try:
                raw_candidate = _invoke_host_kernel(implementation.kernel, call)
            except Exception as error:
                # Kernel messages can contain sensitive input; omit the traceback.
                logger.error(  # noqa: TRY400
                    "host measurement transform kernel raised",
                    extra={
                        "transform_id": transform.id.value,
                        "implementation_id": implementation.id,
                        "semantic_id": transform.semantic.id,
                        "logical_point_id": point.logical_id.value,
                        "point_index": point.logical_ordinal,
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
                            path=(
                                "transforms",
                                transform.id.value,
                                "kernel",
                                point.logical_ordinal,
                            ),
                            details={
                                "exception_type": _type_name(error),
                                "transform_id": transform.id.value,
                                "implementation_id": implementation.id,
                                "semantic_id": transform.semantic.id,
                                "logical_point_id": point.logical_id.value,
                                "point_index": point.logical_ordinal,
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
                            path=(
                                "transforms",
                                transform.id.value,
                                "outputs",
                                point.logical_ordinal,
                            ),
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
                            path=(
                                "transforms",
                                transform.id.value,
                                "outputs",
                                point.logical_ordinal,
                            ),
                            details={
                                "expected": sorted(expected_port_ids),
                                "actual": sorted(
                                    repr(item) for item in actual_port_ids
                                ),
                            },
                            category=ProblemCategory.OPERATION,
                        ),
                    )
                )
            for port in transform.outputs:
                value = raw_outputs[port.id]
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
                        "rate": implementation.rate,
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
    if not isinstance(value, Quantity | ComplexQuantity | MeasurementArray):
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
    "HostMeasurementTransformImplementationBinding",
    "HostMeasurementTransformKernel",
    "HostMeasurementTransformValidator",
    "MeasurementTransformExecutionError",
    "MeasurementTransformPortValues",
    "SelectedHostMeasurementTransforms",
    "bind_host_measurement_transforms",
    "execute_host_measurement_transforms",
    "select_host_measurement_transforms",
]
