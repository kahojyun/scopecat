"""Typed producer-neutral measurement transforms over logical value slots.

The graph owns pure semantic meaning and typed logical input/output edges.
Host callables are selected separately, after linking and before any producer
effect.  Runtime execution consumes only closed producer-neutral fragments and
returns values through the existing measurement assembly boundary.
"""

from __future__ import annotations

import heapq
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)

from scopecat._compiler.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    MaterializedLinkedPointSet,
)
from scopecat._compiler.point_domain import LogicalPointId
from scopecat._compiler.problems import compiler_problem
from scopecat._compiler.products import ProductDef
from scopecat._content_identity import content_fingerprint, stable_content_hash
from scopecat._frozen import (
    FrozenMapping,
    freeze_json_mapping,
    thaw_json_value,
)
from scopecat._measurement_value_contract import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat._product_identity import ProductUseId
from scopecat.errors import (
    CheckFailed,
    MeasurementTransformExecutionError,
    ProviderContractError,
)
from scopecat.measurement_values import (
    ClosedMeasurementProductValues,
    ClosedMeasurementValueFragment,
    MeasurementValueCandidate,
    SelectedMeasurementValueAssembly,
    assemble_measurement_values,
    measurement_value_contract_fingerprint,
    require_measurement_value_assembly,
    require_measurement_value_fragment,
    seal_measurement_value_fragment,
)
from scopecat.models.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.models.parameter import Quantity
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

type MeasurementTransformRate = Literal["point", "point_set"]
type MeasurementTransformPortValues = Mapping[str, MeasurementValue]
type HostMeasurementTransformKernel = Callable[
    ["HostMeasurementTransformCall"],
    Mapping[str, MeasurementValue],
]
type HostMeasurementTransformValidator = Callable[["MeasurementTransformDef"], None]

logger = logging.getLogger(__name__)


def _empty_semantic_parameters() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class MeasurementTransformId:
    """Nominal identity of one transform operation, separate from outputs."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.value), str):
            msg = "measurement transform identity must be a string"
            raise TypeError(msg)
        if not self.value:
            msg = "measurement transform identity must be non-empty"
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value


class MeasurementTransformSemanticContract(BaseModel):
    """Data-only pure meaning that a host or domain realization may satisfy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.measurement_transform_semantic.v1"] = (
        "scopecat.measurement_transform_semantic.v1"
    )
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    purity: Literal["pure"] = "pure"
    portability: Literal["portable", "host_only"] = "portable"
    parameters: Mapping[str, JsonValue] = Field(
        default_factory=_empty_semantic_parameters,
    )

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(
        cls,
        value: Mapping[str, JsonValue],
    ) -> FrozenMapping[str, JsonValue]:
        return freeze_json_mapping(
            value,
            path="measurement transform semantic parameters",
        )

    @field_serializer("parameters")
    def serialize_parameters(self, value: Mapping[str, JsonValue]) -> object:
        return thaw_json_value(value)

    @property
    def contract_fingerprint(self) -> str:
        return stable_content_hash(content_fingerprint(self))


@dataclass(frozen=True, slots=True)
class MeasurementTransformPort:
    """Typed edge from one transform-local semantic role to a linked slot.

    ``id`` is the stable role understood by the semantic contract and its
    implementations. ``product_use_id`` is graph wiring and may change while
    the role-level semantic contract remains equal.
    """

    id: str
    product_use_id: ProductUseId
    product: ProductDef = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.id), str):
            msg = "measurement transform port id must be a string"
            raise TypeError(msg)
        if not self.id:
            msg = "measurement transform port id must be non-empty"
            raise ValueError(msg)
        if not isinstance(cast("object", self.product_use_id), ProductUseId):
            msg = "measurement transform ports require ProductUseId values"
            raise TypeError(msg)
        if not isinstance(cast("object", self.product), ProductDef):
            msg = "measurement transform ports require ProductDef contracts"
            raise TypeError(msg)
        object.__setattr__(self, "product", self.product.model_copy(deep=True))

    @property
    def contract_fingerprint(self) -> str:
        return stable_content_hash(
            content_fingerprint(
                {
                    "id": self.id,
                    "product_use_id": self.product_use_id.value,
                    "product": self.product,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class MeasurementTransformDef:
    """One multi-input, multi-output pure transform declaration."""

    id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    rate: MeasurementTransformRate
    inputs: tuple[MeasurementTransformPort, ...]
    outputs: tuple[MeasurementTransformPort, ...]

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.id), MeasurementTransformId):
            msg = "measurement transforms require MeasurementTransformId"
            raise TypeError(msg)
        if not isinstance(
            cast("object", self.semantic), MeasurementTransformSemanticContract
        ):
            msg = "measurement transforms require a semantic contract"
            raise TypeError(msg)
        if self.rate not in {"point", "point_set"}:
            msg = "measurement transform rate must be point or point_set"
            raise ValueError(msg)
        selected_inputs = tuple(self.inputs)
        selected_outputs = tuple(self.outputs)
        if any(
            not isinstance(cast("object", port), MeasurementTransformPort)
            for port in (*selected_inputs, *selected_outputs)
        ):
            msg = "measurement transform inputs and outputs require typed ports"
            raise TypeError(msg)
        object.__setattr__(self, "inputs", selected_inputs)
        object.__setattr__(self, "outputs", selected_outputs)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedMeasurementTransformGraph:
    """Closed typed DAG with canonical topological node order."""

    linked_points: MaterializedLinkedPointSet = field(repr=False)
    transforms: tuple[MeasurementTransformDef, ...]
    linked_contract_fingerprint: str
    contract_fingerprint: str

    def __init__(
        self,
        linked_points: MaterializedLinkedPointSet,
        transforms: tuple[MeasurementTransformDef, ...],
        linked_contract_fingerprint: str,
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "linked_points", linked_points)
        object.__setattr__(self, "transforms", transforms)
        object.__setattr__(
            self,
            "linked_contract_fingerprint",
            linked_contract_fingerprint,
        )
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


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
        if any(not isinstance(cast("object", value), str) for value in fields):
            msg = "host measurement transform implementation fields must be strings"
            raise TypeError(msg)
        if not all(fields):
            msg = "host measurement transform implementation fields must be non-empty"
            raise ValueError(msg)
        if self.rate not in {"point", "point_set"}:
            msg = "host measurement transform rate must be point or point_set"
            raise ValueError(msg)
        if not callable(self.validate_transform):
            msg = "host measurement transform validator must be callable"
            raise TypeError(msg)
        if not callable(self.kernel):
            msg = "host measurement transform implementation kernel must be callable"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformImplementationBinding:
    """Explicit selection of one implementation for one transform identity."""

    transform_id: MeasurementTransformId
    implementation_id: str

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.transform_id), MeasurementTransformId):
            msg = "host implementation bindings require MeasurementTransformId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.implementation_id), str):
            msg = "host implementation binding id must be a string"
            raise TypeError(msg)
        if not self.implementation_id:
            msg = "host implementation binding id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformCall:
    """Defensively snapshotted point-local invocation passed to a host kernel."""

    transform_id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    logical_point_id: LogicalPointId
    point_index: int
    input_ports: tuple[MeasurementTransformPort, ...]
    output_ports: tuple[MeasurementTransformPort, ...]
    inputs: Mapping[str, MeasurementValue]

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.transform_id), MeasurementTransformId):
            msg = "host transform calls require MeasurementTransformId"
            raise TypeError(msg)
        if not isinstance(
            cast("object", self.semantic),
            MeasurementTransformSemanticContract,
        ):
            msg = "host transform calls require a semantic contract"
            raise TypeError(msg)
        if not isinstance(cast("object", self.logical_point_id), LogicalPointId):
            msg = "host transform calls require LogicalPointId"
            raise TypeError(msg)
        if type(self.point_index) is not int or self.point_index < 0:
            msg = "host transform call point_index must be a non-negative integer"
            raise ValueError(msg)
        input_ports = tuple(self.input_ports)
        output_ports = tuple(self.output_ports)
        if any(
            not isinstance(cast("object", port), MeasurementTransformPort)
            for port in (*input_ports, *output_ports)
        ):
            msg = "host transform calls require typed input and output ports"
            raise TypeError(msg)
        if len({port.id for port in input_ports}) != len(input_ports):
            msg = "host transform call input port ids must be unique"
            raise ValueError(msg)
        if len({port.id for port in output_ports}) != len(output_ports):
            msg = "host transform call output port ids must be unique"
            raise ValueError(msg)
        raw_inputs = cast("Mapping[object, object]", cast("object", self.inputs))
        try:
            input_candidates = dict(raw_inputs)
        except Exception as error:
            msg = "host transform call inputs must be a readable mapping"
            raise TypeError(msg) from error
        if set(input_candidates) != {port.id for port in input_ports}:
            msg = "host transform call inputs must exactly match its input ports"
            raise ValueError(msg)
        if any(not isinstance(port_id, str) for port_id in input_candidates):
            msg = "host transform call input ids must be strings"
            raise TypeError(msg)
        if any(not _is_measurement_value(value) for value in input_candidates.values()):
            msg = "host transform call inputs must be MeasurementValue values"
            raise TypeError(msg)
        inputs = cast("dict[str, MeasurementValue]", input_candidates)
        object.__setattr__(
            self,
            "semantic",
            _snapshot_semantic(self.semantic),
        )
        object.__setattr__(
            self,
            "input_ports",
            tuple(_snapshot_port(port) for port in input_ports),
        )
        object.__setattr__(
            self,
            "output_ports",
            tuple(_snapshot_port(port) for port in output_ports),
        )
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(
                {
                    port_id: validated_measurement_value_copy(value)
                    for port_id, value in inputs.items()
                }
            ),
        )


@dataclass(frozen=True, slots=True, init=False)
class SelectedHostMeasurementTransforms:
    """Exact host implementation selection for a verified graph."""

    graph: VerifiedMeasurementTransformGraph = field(repr=False)
    implementations: tuple[HostMeasurementTransformImplementation, ...]
    contract_fingerprint: str

    def __init__(
        self,
        graph: VerifiedMeasurementTransformGraph,
        implementations: tuple[HostMeasurementTransformImplementation, ...],
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "graph", graph)
        object.__setattr__(self, "implementations", implementations)
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


@dataclass(frozen=True, slots=True)
class HostMeasurementTransformFragmentBinding:
    transform_id: MeasurementTransformId
    fragment_id: str

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.transform_id), MeasurementTransformId):
            msg = "host transform fragment bindings require MeasurementTransformId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.fragment_id), str):
            msg = "host transform fragment id must be a string"
            raise TypeError(msg)
        if not self.fragment_id:
            msg = "host measurement transform fragment id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, init=False)
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
    contract_fingerprint: str

    def __init__(
        self,
        selection: SelectedHostMeasurementTransforms,
        value_assembly: SelectedMeasurementValueAssembly,
        fragment_bindings: tuple[HostMeasurementTransformFragmentBinding, ...],
        source_fragment_ids: tuple[str, ...],
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "value_assembly", value_assembly)
        object.__setattr__(self, "fragment_bindings", fragment_bindings)
        object.__setattr__(self, "source_fragment_ids", source_fragment_ids)
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


@dataclass(frozen=True, slots=True, init=False)
class ExecutedHostMeasurementTransforms:
    """Closed source/derived fragments and final canonical assembled values."""

    plan: BoundHostMeasurementTransformPlan = field(repr=False)
    source_fragments: tuple[ClosedMeasurementValueFragment, ...]
    transform_fragments: tuple[ClosedMeasurementValueFragment, ...]
    values: ClosedMeasurementProductValues

    def __init__(
        self,
        plan: BoundHostMeasurementTransformPlan,
        source_fragments: tuple[ClosedMeasurementValueFragment, ...],
        transform_fragments: tuple[ClosedMeasurementValueFragment, ...],
        values: ClosedMeasurementProductValues,
    ) -> None:
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "source_fragments", source_fragments)
        object.__setattr__(self, "transform_fragments", transform_fragments)
        object.__setattr__(self, "values", values)


def verify_measurement_transform_graph(
    linked_points: MaterializedLinkedPointSet,
    transforms: Sequence[MeasurementTransformDef],
) -> VerifiedMeasurementTransformGraph:
    """Close a typed transform DAG without choosing a runtime implementation."""

    if not isinstance(
        cast("object", linked_points),
        MaterializedLinkedPoints | MaterializedLinkedPointBatch,
    ):
        msg = "measurement transform graphs require materialized linked points"
        raise TypeError(msg)
    supplied = tuple(transforms)
    if any(
        not isinstance(cast("object", transform), MeasurementTransformDef)
        for transform in supplied
    ):
        msg = "measurement transform graphs require MeasurementTransformDef values"
        raise TypeError(msg)

    problems: list[Problem] = []
    valid_declarations: list[MeasurementTransformDef] = []
    for transform_index, transform in enumerate(supplied):
        try:
            valid_declarations.append(_snapshot_transform(transform))
        except (AttributeError, TypeError, ValueError) as error:
            problems.append(
                _check_problem(
                    "measurement_transform_declaration_invalid",
                    "measurement transform declaration fields are invalid",
                    path=("transforms", transform_index),
                    details={"error_type": _type_name(error)},
                )
            )
    declarations = tuple(valid_declarations)

    linked_plan = linked_points.linked_plan
    uses_by_id = {use.id: use for use in linked_plan.product_uses}
    products_by_id = {product.id: product for product in linked_plan.product_defs}

    transform_counts = Counter(transform.id for transform in declarations)
    for transform_id, count in transform_counts.items():
        if count > 1:
            problems.append(
                _check_problem(
                    "measurement_transform_duplicate",
                    f"measurement transform {transform_id.value!r} is duplicated",
                    path=("transforms", transform_id.value),
                    category=ProblemCategory.CONFLICT,
                )
            )

    owner_by_output: dict[ProductUseId, MeasurementTransformId] = {}
    for transform_index, transform in enumerate(declarations):
        if not transform.outputs:
            problems.append(
                _check_problem(
                    "measurement_transform_outputs_empty",
                    f"measurement transform {transform.id.value!r} has no outputs",
                    path=("transforms", transform_index, "outputs"),
                )
            )
        for direction, ports in (
            ("inputs", transform.inputs),
            ("outputs", transform.outputs),
        ):
            port_counts = Counter(port.id for port in ports)
            for port_id, count in port_counts.items():
                if count > 1:
                    problems.append(
                        _check_problem(
                            "measurement_transform_port_duplicate",
                            f"measurement transform {transform.id.value!r} repeats "
                            f"{direction[:-1]} port {port_id!r}",
                            path=(
                                "transforms",
                                transform_index,
                                direction,
                                port_id,
                            ),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
            for port_index, port in enumerate(ports):
                use = uses_by_id.get(port.product_use_id)
                if use is None:
                    problems.append(
                        _check_problem(
                            "measurement_transform_product_use_missing",
                            f"measurement transform port {port.id!r} references "
                            f"unknown product use {port.product_use_id.value!r}",
                            path=(
                                "transforms",
                                transform_index,
                                direction,
                                port_index,
                                "product_use_id",
                            ),
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                    continue
                expected_product = products_by_id.get(use.product_id)
                if expected_product is None:
                    problems.append(
                        _check_problem(
                            "measurement_transform_product_missing",
                            f"measurement transform port {port.id!r} references "
                            "a product use without a definition",
                            path=(
                                "transforms",
                                transform_index,
                                direction,
                                port_index,
                                "product",
                            ),
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                elif port.product != expected_product:
                    problems.append(
                        _check_problem(
                            "measurement_transform_product_contract_mismatch",
                            f"measurement transform port {port.id!r} does not retain "
                            "the exact linked product contract",
                            path=(
                                "transforms",
                                transform_index,
                                direction,
                                port_index,
                                "product",
                            ),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                if direction == "outputs":
                    existing = owner_by_output.get(port.product_use_id)
                    if existing is not None:
                        problems.append(
                            _check_problem(
                                "measurement_transform_output_owner_duplicate",
                                f"product use {port.product_use_id.value!r} is output "
                                f"by transforms {existing.value!r} and "
                                f"{transform.id.value!r}",
                                path=(
                                    "transforms",
                                    transform_index,
                                    "outputs",
                                    port_index,
                                ),
                                category=ProblemCategory.CONFLICT,
                            )
                        )
                    else:
                        owner_by_output[port.product_use_id] = transform.id

    canonical = _canonical_topological_order(declarations, owner_by_output)
    if canonical is None:
        problems.append(
            _check_problem(
                "measurement_transform_cycle",
                "measurement transform graph contains a dependency cycle",
                path=("transforms",),
                category=ProblemCategory.CONFLICT,
            )
        )
    if problems:
        raise CheckFailed(problems)
    if canonical is None:
        raise AssertionError("successful transform verification lost topology")

    selected = tuple(_snapshot_transform(transform) for transform in canonical)
    linked_fingerprint = measurement_value_contract_fingerprint(linked_points)
    contract_fingerprint = _graph_contract_fingerprint(
        linked_fingerprint,
        selected,
    )
    return VerifiedMeasurementTransformGraph(
        linked_points,
        selected,
        linked_fingerprint,
        contract_fingerprint,
    )


def select_host_measurement_transforms(
    graph: VerifiedMeasurementTransformGraph,
    implementations: Sequence[HostMeasurementTransformImplementation],
    bindings: Sequence[HostMeasurementTransformImplementationBinding],
) -> SelectedHostMeasurementTransforms:
    """Select explicitly bound host implementations for every POINT transform."""

    selected_graph = _require_verified_graph(graph)
    raw_candidates = tuple(implementations)
    if any(
        not isinstance(
            cast("object", implementation),
            HostMeasurementTransformImplementation,
        )
        for implementation in raw_candidates
    ):
        msg = "host transform selection requires implementation sidecars"
        raise TypeError(msg)
    candidates = tuple(
        _snapshot_implementation(implementation) for implementation in raw_candidates
    )
    supplied_bindings = tuple(bindings)
    if any(
        not isinstance(
            cast("object", binding),
            HostMeasurementTransformImplementationBinding,
        )
        for binding in supplied_bindings
    ):
        msg = "host transform selection requires explicit implementation bindings"
        raise TypeError(msg)

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
        MeasurementTransformId,
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
        if transform.rate == "point_set":
            problems.append(
                _check_problem(
                    "measurement_transform_host_rate_unsupported",
                    f"host execution does not support point_set transform "
                    f"{transform.id.value!r}",
                    path=("transforms", transform_index, "rate"),
                    category=ProblemCategory.UNAVAILABLE,
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
                _snapshot_transform(transform),
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
    fingerprint = _host_selection_fingerprint(selected_graph, selected_tuple)
    return SelectedHostMeasurementTransforms(
        selected_graph,
        selected_tuple,
        fingerprint,
    )


def bind_host_measurement_transforms(
    selection: SelectedHostMeasurementTransforms,
    value_assembly: SelectedMeasurementValueAssembly,
    fragment_bindings: Sequence[HostMeasurementTransformFragmentBinding],
) -> BoundHostMeasurementTransformPlan:
    """Bind transform outputs and source leaves to one value assembly."""

    selected = _require_host_selection(selection)
    assembly = require_measurement_value_assembly(value_assembly)
    supplied = tuple(fragment_bindings)
    if any(
        not isinstance(
            cast("object", binding),
            HostMeasurementTransformFragmentBinding,
        )
        for binding in supplied
    ):
        msg = "host transform binding requires fragment bindings"
        raise TypeError(msg)

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
        MeasurementTransformId, HostMeasurementTransformFragmentBinding
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
        expected_outputs = {port.product_use_id for port in transform.outputs}
        if set(fragment.product_use_ids) != expected_outputs or len(
            fragment.product_use_ids
        ) != len(transform.outputs):
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
        for direction, ports in (
            ("inputs", transform.inputs),
            ("outputs", transform.outputs),
        ):
            for port_index, port in enumerate(ports):
                if port.product_use_id not in assembly_use_ids:
                    problems.append(
                        _check_problem(
                            "measurement_transform_assembly_value_missing",
                            f"transform {transform.id.value!r} {direction[:-1]} "
                            f"{port.id!r} is absent from the value assembly",
                            path=(
                                "transforms",
                                transform_index,
                                direction,
                                port_index,
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
    fingerprint = _bound_plan_fingerprint(
        selected,
        assembly,
        canonical_bindings,
        source_fragment_ids,
    )
    return BoundHostMeasurementTransformPlan(
        selected,
        assembly,
        canonical_bindings,
        source_fragment_ids,
        fingerprint,
    )


def execute_host_measurement_transforms(
    plan: BoundHostMeasurementTransformPlan,
    source_fragments: Sequence[ClosedMeasurementValueFragment],
) -> ExecutedHostMeasurementTransforms:
    """Execute POINT kernels in canonical graph order and assemble all values."""

    bound = _require_bound_host_plan(plan)
    supplied = tuple(source_fragments)
    if any(
        not isinstance(cast("object", fragment), ClosedMeasurementValueFragment)
        for fragment in supplied
    ):
        msg = "host transform execution requires closed measurement fragments"
        raise TypeError(msg)

    by_id: dict[str, ClosedMeasurementValueFragment] = {}
    problems: list[Problem] = []
    expected_source_ids = set(bound.source_fragment_ids)
    for fragment_index, candidate in enumerate(supplied):
        try:
            fragment = require_measurement_value_fragment(candidate)
        except (KeyError, TypeError, ValueError) as error:
            problems.append(
                _execution_problem(
                    "measurement_transform_source_fragment_invalid",
                    "host transform source fragment is invalid",
                    path=("source_fragments", fragment_index),
                    details={"error_type": _type_name(error)},
                    category=ProblemCategory.INVALID_INPUT,
                )
            )
            continue
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
                semantic=_snapshot_semantic(transform.semantic),
                logical_point_id=point.logical_id,
                point_index=point.logical_ordinal,
                input_ports=transform.inputs,
                output_ports=transform.outputs,
                inputs=inputs,
            )
            try:
                raw_candidate = _invoke_host_kernel(implementation.kernel, call)
            except Exception as error:
                logger.error(
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
                candidates.append(
                    MeasurementValueCandidate(
                        logical_point_id=point.logical_id,
                        product_use_id=port.product_use_id,
                        value=cast("MeasurementValue", value),
                    )
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


def _snapshot_transform(
    transform: MeasurementTransformDef,
) -> MeasurementTransformDef:
    return MeasurementTransformDef(
        id=transform.id,
        semantic=_snapshot_semantic(transform.semantic),
        rate=transform.rate,
        inputs=tuple(
            _snapshot_port(port)
            for port in sorted(transform.inputs, key=lambda item: item.id)
        ),
        outputs=tuple(
            _snapshot_port(port)
            for port in sorted(transform.outputs, key=lambda item: item.id)
        ),
    )


def _snapshot_semantic(
    semantic: MeasurementTransformSemanticContract,
) -> MeasurementTransformSemanticContract:
    return semantic.model_copy(deep=True)


def _snapshot_port(port: MeasurementTransformPort) -> MeasurementTransformPort:
    return MeasurementTransformPort(
        id=port.id,
        product_use_id=port.product_use_id,
        product=port.product,
    )


def _snapshot_implementation(
    implementation: HostMeasurementTransformImplementation,
) -> HostMeasurementTransformImplementation:
    return HostMeasurementTransformImplementation(
        id=implementation.id,
        semantic_id=implementation.semantic_id,
        semantic_version=implementation.semantic_version,
        rate=implementation.rate,
        implementation_fingerprint=implementation.implementation_fingerprint,
        validate_transform=implementation.validate_transform,
        kernel=implementation.kernel,
    )


def _canonical_topological_order(
    transforms: Sequence[MeasurementTransformDef],
    owner_by_output: Mapping[ProductUseId, MeasurementTransformId],
) -> tuple[MeasurementTransformDef, ...] | None:
    by_id: dict[MeasurementTransformId, MeasurementTransformDef] = {}
    for transform in transforms:
        by_id.setdefault(transform.id, transform)
    dependencies: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform_id: set() for transform_id in by_id
    }
    dependants: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform_id: set() for transform_id in by_id
    }
    for transform_id, transform in by_id.items():
        for port in transform.inputs:
            owner = owner_by_output.get(port.product_use_id)
            if owner is None or owner not in by_id:
                continue
            dependencies[transform_id].add(owner)
            dependants[owner].add(transform_id)
    ready = [
        (transform_id.value, transform_id)
        for transform_id, owners in dependencies.items()
        if not owners
    ]
    heapq.heapify(ready)
    ordered: list[MeasurementTransformDef] = []
    while ready:
        _name, transform_id = heapq.heappop(ready)
        ordered.append(by_id[transform_id])
        for dependant in sorted(
            dependants[transform_id],
            key=lambda item: item.value,
        ):
            dependencies[dependant].discard(transform_id)
            if not dependencies[dependant]:
                heapq.heappush(ready, (dependant.value, dependant))
    if len(ordered) != len(by_id):
        return None
    return tuple(ordered)


def _require_verified_graph(
    graph: VerifiedMeasurementTransformGraph,
) -> VerifiedMeasurementTransformGraph:
    if not isinstance(cast("object", graph), VerifiedMeasurementTransformGraph):
        msg = "host transform selection requires a verified transform graph"
        raise TypeError(msg)
    return graph


def _require_host_selection(
    selection: SelectedHostMeasurementTransforms,
) -> SelectedHostMeasurementTransforms:
    if not isinstance(
        cast("object", selection),
        SelectedHostMeasurementTransforms,
    ):
        msg = "host transform binding requires SelectedHostMeasurementTransforms"
        raise TypeError(msg)
    return selection


def _require_bound_host_plan(
    plan: BoundHostMeasurementTransformPlan,
) -> BoundHostMeasurementTransformPlan:
    if not isinstance(cast("object", plan), BoundHostMeasurementTransformPlan):
        msg = "host transform execution requires BoundHostMeasurementTransformPlan"
        raise TypeError(msg)
    return plan


def _graph_contract_fingerprint(
    linked_fingerprint: str,
    transforms: Sequence[MeasurementTransformDef],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurement_transform_graph.v1",
                "linked_contract_fingerprint": linked_fingerprint,
                "transforms": tuple(transforms),
            }
        )
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
    "MeasurementTransformDef",
    "MeasurementTransformExecutionError",
    "MeasurementTransformId",
    "MeasurementTransformPort",
    "MeasurementTransformPortValues",
    "MeasurementTransformRate",
    "MeasurementTransformSemanticContract",
    "ProductDef",
    "ProductUseId",
    "SelectedHostMeasurementTransforms",
    "VerifiedMeasurementTransformGraph",
    "bind_host_measurement_transforms",
    "execute_host_measurement_transforms",
    "select_host_measurement_transforms",
    "verify_measurement_transform_graph",
]
