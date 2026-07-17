"""Host selection, binding, and execution for measurement transforms.

The graph owns pure semantic meaning and typed logical input/output edges.
Host callables are selected separately, after linking and before any producer
effect.  Runtime execution consumes only closed producer-neutral fragments and
returns values through the existing measurement assembly boundary.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.typed.point_domain import LogicalPointId
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import (
    CheckFailed,
    MeasurementTransformExecutionError,
    ProviderContractError,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
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
    ClosedMeasurementProductValues,
    ClosedMeasurementValueFragment,
    MeasurementValueCandidate,
    SelectedMeasurementValueAssembly,
    assemble_measurement_values,
    seal_measurement_value_fragment,
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
class HostMeasurementTransformFragmentBinding:
    transform_id: NativeMeasurementTransformId
    fragment_id: str

    def __post_init__(self) -> None:
        if not self.fragment_id:
            msg = "host measurement transform fragment id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BoundHostMeasurementTransformPlan:
    """Structural transform/fragment binding selected before runtime effects.

    ``source_fragment_ids`` identifies the remaining ingress fragments.  This
    proof does not select or establish the producer realization of those
    source fragments; a host orchestration plan must close that separately.
    """

    selection: SelectedHostMeasurementTransforms = field(repr=False)
    value_assembly: SelectedMeasurementValueAssembly = field(repr=False)
    fragment_bindings: tuple[HostMeasurementTransformFragmentBinding, ...]
    source_fragment_ids: tuple[str, ...]
    contract_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        bindings = tuple(self.fragment_bindings)
        source_ids = tuple(self.source_fragment_ids)
        if (
            self.selection.graph.linked_contract_fingerprint
            != self.value_assembly.linked_contract_fingerprint
        ):
            msg = "host transform plan and value assembly belong to different plans"
            raise ValueError(msg)
        if len(bindings) != len(self.selection.graph.transforms):
            msg = "every selected host transform must have one fragment binding"
            raise ValueError(msg)
        if tuple(binding.transform_id for binding in bindings) != tuple(
            transform.id for transform in self.selection.graph.transforms
        ):
            msg = "host transform fragment bindings must follow graph order"
            raise ValueError(msg)
        fragment_ids = tuple(binding.fragment_id for binding in bindings)
        all_fragment_ids = (*fragment_ids, *source_ids)
        if len(all_fragment_ids) != len({*all_fragment_ids}):
            msg = "host transform and source fragment ids must be unique"
            raise ValueError(msg)
        if {*all_fragment_ids} != {
            fragment.id for fragment in self.value_assembly.fragments
        }:
            msg = "host transform plan must cover the selected value fragments"
            raise ValueError(msg)
        object.__setattr__(self, "fragment_bindings", bindings)
        object.__setattr__(self, "source_fragment_ids", source_ids)
        object.__setattr__(
            self,
            "contract_fingerprint",
            _bound_plan_fingerprint(
                self.selection,
                self.value_assembly,
                bindings,
                source_ids,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutedHostMeasurementTransforms:
    """Closed source/derived fragments and final canonical assembled values."""

    plan: BoundHostMeasurementTransformPlan = field(repr=False)
    source_fragments: tuple[ClosedMeasurementValueFragment, ...]
    transform_fragments: tuple[ClosedMeasurementValueFragment, ...]
    values: ClosedMeasurementProductValues

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_fragments", tuple(self.source_fragments))
        object.__setattr__(self, "transform_fragments", tuple(self.transform_fragments))
        if self.values.selection is not self.plan.value_assembly:
            msg = "executed host values must belong to the bound value assembly"
            raise ValueError(msg)


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
    value_assembly: SelectedMeasurementValueAssembly,
    fragment_bindings: Sequence[HostMeasurementTransformFragmentBinding],
) -> BoundHostMeasurementTransformPlan:
    """Bind transform outputs and source leaves to one value assembly."""

    selected = selection
    assembly = value_assembly
    supplied = tuple(fragment_bindings)

    graph = selected.graph
    problems: list[Problem] = []
    if assembly.linked_contract_fingerprint != graph.linked_contract_fingerprint:
        problems.append(
            _check_problem(
                "measurement_transform_assembly_contract_mismatch",
                "measurement transform graph and value assembly belong to "
                "different linked contracts",
                path=("value_assembly",),
                category=ProblemCategory.CONFLICT,
            )
        )
    transform_by_id = {transform.id: transform for transform in graph.transforms}
    binding_counts = Counter(binding.transform_id for binding in supplied)
    fragment_counts = Counter(binding.fragment_id for binding in supplied)
    by_transform: dict[
        NativeMeasurementTransformId, HostMeasurementTransformFragmentBinding
    ] = {}
    for binding_index, binding in enumerate(supplied):
        if binding_counts[binding.transform_id] > 1:
            problems.append(
                _check_problem(
                    "measurement_transform_fragment_binding_duplicate",
                    f"transform {binding.transform_id.value!r} has multiple fragment "
                    "bindings",
                    path=("fragment_bindings", binding_index),
                    category=ProblemCategory.CONFLICT,
                )
            )
        if fragment_counts[binding.fragment_id] > 1:
            problems.append(
                _check_problem(
                    "measurement_transform_fragment_owner_duplicate",
                    f"fragment {binding.fragment_id!r} is bound to multiple transforms",
                    path=("fragment_bindings", binding_index, "fragment_id"),
                    category=ProblemCategory.CONFLICT,
                )
            )
        transform = transform_by_id.get(binding.transform_id)
        if transform is None:
            problems.append(
                _check_problem(
                    "measurement_transform_fragment_binding_unknown",
                    f"fragment binding references unknown transform "
                    f"{binding.transform_id.value!r}",
                    path=("fragment_bindings", binding_index, "transform_id"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        by_transform.setdefault(binding.transform_id, binding)
        try:
            fragment = assembly.fragment(binding.fragment_id)
        except KeyError:
            problems.append(
                _check_problem(
                    "measurement_transform_output_fragment_missing",
                    f"transform {binding.transform_id.value!r} references unknown "
                    f"fragment {binding.fragment_id!r}",
                    path=("fragment_bindings", binding_index, "fragment_id"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        expected_output_ids = tuple(
            use_id for port in transform.outputs for use_id in port.product_use_ids
        )
        expected_outputs = set(expected_output_ids)
        if set(fragment.product_use_ids) != expected_outputs or len(
            fragment.product_use_ids
        ) != len(expected_output_ids):
            problems.append(
                _check_problem(
                    "measurement_transform_output_fragment_mismatch",
                    f"fragment {fragment.id!r} does not exactly own outputs of "
                    f"transform {transform.id.value!r}",
                    path=("fragment_bindings", binding_index, "fragment_id"),
                    category=ProblemCategory.CONFLICT,
                )
            )

    assembly_use_ids = set(assembly.product_use_ids)
    for transform_index, transform in enumerate(graph.transforms):
        if transform.id not in by_transform:
            problems.append(
                _check_problem(
                    "measurement_transform_fragment_binding_missing",
                    f"transform {transform.id.value!r} has no output fragment binding",
                    path=("transforms", transform_index, "fragment"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        for port_index, port in enumerate(transform.inputs):
            if port.product_use_id not in assembly_use_ids:
                problems.append(
                    _check_problem(
                        "measurement_transform_assembly_value_missing",
                        f"transform {transform.id.value!r} input {port.id!r} "
                        "is absent from the value assembly",
                        path=(
                            "transforms",
                            transform_index,
                            "inputs",
                            port_index,
                        ),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
        for port_index, port in enumerate(transform.outputs):
            for use_index, use_id in enumerate(port.product_use_ids):
                if use_id not in assembly_use_ids:
                    problems.append(
                        _check_problem(
                            "measurement_transform_assembly_value_missing",
                            f"transform {transform.id.value!r} output {port.id!r} "
                            "is absent from the value assembly",
                            path=(
                                "transforms",
                                transform_index,
                                "outputs",
                                port_index,
                                "product_use_ids",
                                use_index,
                            ),
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
    if problems:
        raise CheckFailed(problems)

    canonical_bindings = tuple(
        by_transform[transform.id] for transform in graph.transforms
    )
    transform_fragment_ids = {binding.fragment_id for binding in canonical_bindings}
    source_fragment_ids = tuple(
        fragment.id
        for fragment in assembly.fragments
        if fragment.id not in transform_fragment_ids
    )
    return BoundHostMeasurementTransformPlan(
        selected,
        assembly,
        canonical_bindings,
        source_fragment_ids,
    )


def execute_host_measurement_transforms(
    plan: BoundHostMeasurementTransformPlan,
    source_fragments: Sequence[ClosedMeasurementValueFragment],
) -> ExecutedHostMeasurementTransforms:
    """Execute POINT kernels in canonical graph order and assemble all values."""

    bound = plan
    supplied = tuple(source_fragments)

    by_id: dict[str, ClosedMeasurementValueFragment] = {}
    problems: list[Problem] = []
    expected_source_ids = set(bound.source_fragment_ids)
    for fragment_index, candidate in enumerate(supplied):
        fragment = candidate
        if fragment.fragment_id in by_id:
            problems.append(
                _execution_problem(
                    "measurement_transform_source_fragment_duplicate",
                    f"source fragment {fragment.fragment_id!r} is repeated",
                    path=("source_fragments", fragment_index),
                    category=ProblemCategory.CONFLICT,
                )
            )
            continue
        by_id[fragment.fragment_id] = fragment
        if fragment.fragment_id not in expected_source_ids:
            problems.append(
                _execution_problem(
                    "measurement_transform_source_fragment_unexpected",
                    f"fragment {fragment.fragment_id!r} is not a selected source",
                    path=("source_fragments", fragment_index),
                    category=ProblemCategory.INVALID_INPUT,
                )
            )
        if (
            fragment.selection.contract_fingerprint
            != bound.value_assembly.contract_fingerprint
        ):
            problems.append(
                _execution_problem(
                    "measurement_transform_source_contract_mismatch",
                    f"source fragment {fragment.fragment_id!r} belongs to another "
                    "value assembly",
                    path=("source_fragments", fragment_index),
                    category=ProblemCategory.INVALID_INPUT,
                )
            )
    for fragment_id in bound.source_fragment_ids:
        if fragment_id not in by_id:
            problems.append(
                _execution_problem(
                    "measurement_transform_source_fragment_missing",
                    f"selected source fragment {fragment_id!r} is missing",
                    path=("source_fragments", fragment_id),
                    category=ProblemCategory.INVALID_INPUT,
                )
            )
    if problems:
        raise MeasurementTransformExecutionError(problems)

    canonical_sources = tuple(by_id[item] for item in bound.source_fragment_ids)
    value_by_output = {
        (value.logical_point_id, value.product_use_id): value
        for fragment in canonical_sources
        for value in fragment.values
    }
    binding_by_transform = {
        binding.transform_id: binding for binding in bound.fragment_bindings
    }
    transform_fragments: list[ClosedMeasurementValueFragment] = []
    points = bound.selection.graph.linked_points.point_domain.points
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
        binding = binding_by_transform[transform.id]
        try:
            fragment = seal_measurement_value_fragment(
                bound.value_assembly,
                binding.fragment_id,
                candidates,
            )
        except ProviderContractError as error:
            msg = "prevalidated transform outputs failed fragment sealing"
            raise AssertionError(msg) from error
        transform_fragments.append(fragment)
        value_by_output.update(
            {
                (value.logical_point_id, value.product_use_id): value
                for value in fragment.values
            }
        )

    selected_transform_fragments = tuple(transform_fragments)
    try:
        values = assemble_measurement_values(
            bound.value_assembly,
            (*canonical_sources, *selected_transform_fragments),
        )
    except ProviderContractError as error:
        msg = "closed transform fragments failed their prevalidated assembly"
        raise AssertionError(msg) from error
    return ExecutedHostMeasurementTransforms(
        bound,
        canonical_sources,
        selected_transform_fragments,
        values,
    )


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


def _bound_plan_fingerprint(
    selection: SelectedHostMeasurementTransforms,
    assembly: SelectedMeasurementValueAssembly,
    bindings: Sequence[HostMeasurementTransformFragmentBinding],
    source_fragment_ids: Sequence[str],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.bound_host_measurement_transforms.v1",
                "selection_contract_fingerprint": selection.contract_fingerprint,
                "assembly_contract_fingerprint": assembly.contract_fingerprint,
                "fragment_bindings": tuple(bindings),
                "source_fragment_ids": tuple(source_fragment_ids),
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
    "BoundHostMeasurementTransformPlan",
    "ExecutedHostMeasurementTransforms",
    "HostMeasurementTransformCall",
    "HostMeasurementTransformFragmentBinding",
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
