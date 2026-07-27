"""Target-independent typed meaning produced by the authoring compiler.

``CoreProgram`` keeps point composition, value dataflow, effect order, and
product ownership symbolic so one experiment definition can be specialized for
different physical systems. It is transient compiler data because accepted run
semantics, not intermediate compiler shape, form the durable boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.compiler.relations.uses import RelationUse, relation_use
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    LocalPythonImplementation,
    MeasurementPostprocessorId,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    ValueExpr,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.state import (
    LogicalStateResourceTarget,
    SetStateSpec,
)
from scopecat.domain.program import DomainProgramDef
from scopecat.graph.values import (
    ComputeOutput,
    ComputeResultRef,
    OperationId,
    ValueId,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
    product_use,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)
from scopecat.kernel.value_types import Scalar, ValueType
from scopecat.measurements.postprocessor_contract import (
    MeasurementPostprocessorKernel,
)
from scopecat.measurements.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.measurements.records import RecordUse


@dataclass(frozen=True, slots=True)
class ValueInput:
    """Proof-carrying value evaluated for one compute invocation."""

    value: ValueExpr

    @property
    def value_type(self) -> ValueType:
        return self.value.value_type


@dataclass(frozen=True, slots=True)
class ComputeEdge:
    """Explicit dependency on the result of another compute node."""

    value_id: ValueId
    expected_type: Scalar

    @property
    def value_type(self) -> Scalar:
        return self.expected_type


type ComputeInput = ValueInput | ComputeEdge


def _empty_value_inputs() -> dict[str, ValueInput]:
    return {}


def _empty_compute_inputs() -> dict[str, ComputeInput]:
    return {}


@dataclass(frozen=True, slots=True)
class TypedDomainResultBinding:
    """Exact logical product occurrences produced by one named domain result."""

    id: str
    product_id: ProductId
    product_use_ids: tuple[ProductUseId, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            msg = "typed domain result id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TypedDomainExecution:
    """One domain program with executable plan inputs and result bindings."""

    id: str
    program: DomainProgramDef
    inputs: Mapping[str, ValueInput] = field(default_factory=_empty_value_inputs)
    compiler_inputs: Mapping[str, ValueInput] = field(
        default_factory=_empty_value_inputs
    )
    results: tuple[TypedDomainResultBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("typed domain execution id must be non-empty")
        selected_inputs: dict[str, ValueInput] = dict(self.inputs)
        object.__setattr__(self, "inputs", selected_inputs)
        object.__setattr__(self, "compiler_inputs", dict(self.compiler_inputs))


type CoreEffect = SetStateSpec | TypedDomainExecution | AcquireEffect


@dataclass(frozen=True, slots=True)
class TypedMeasurementPostprocessorOutput:
    """One calculated product and all of its downstream use slots."""

    id: str
    product_id: ProductId
    product_use_ids: tuple[ProductUseId, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement postprocessor output id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TypedMeasurementPostprocessor:
    """One live point-local postprocessor retained by record demand."""

    id: MeasurementPostprocessorId
    input_product_id: ProductId
    input_product_use_id: ProductUseId
    outputs: tuple[TypedMeasurementPostprocessorOutput, ...]
    kernel: MeasurementPostprocessorKernel = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TypedComputeNode:
    """One typed pure-code node in the expanded compute graph."""

    id: OperationId
    implementation: LocalPythonImplementation
    result: ComputeOutput
    inputs: Mapping[str, ComputeInput] = field(default_factory=_empty_compute_inputs)

    def __post_init__(self) -> None:
        selected_inputs: dict[str, ComputeInput] = dict(self.inputs)
        object.__setattr__(self, "inputs", selected_inputs)


@dataclass(frozen=True, slots=True)
class LogicalResourceRequirement:
    """Stable logical capabilities plus point-local object selection.

    ``capabilities`` is the compile-time contract for the logical port, while
    ``entity_uses`` selects its objects at each point. Physical instrument and
    channel identity enter only during target materialization.
    """

    port_id: LogicalResourcePortId
    capabilities: tuple[str, ...] = ()
    entity_uses: tuple[RelationUse[ScalarValueExpr], ...] = ()


@dataclass(frozen=True, slots=True)
class CoreProgram:
    """Canonical typed and symbolic meaning of one authored experiment.

    The ordered ``effects`` sequence is authoritative so specialization can
    choose host or domain placement while retaining logical point identity,
    lexical parameter semantics, product ownership, and effect order.
    """

    id: str
    kind: str
    point_domain: PointDomain
    resource_requirements: tuple[LogicalResourceRequirement, ...] = ()
    parameter_overlays: tuple[PointParameterOverlay, ...] = ()
    compute_nodes: tuple[TypedComputeNode, ...] = ()
    effects: tuple[CoreEffect, ...] = ()
    measurement_postprocessors: tuple[TypedMeasurementPostprocessor, ...] = ()
    product_defs: tuple[ProductDef, ...] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[RecordUse, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.kind:
            msg = "core program id and kind must be non-empty"
            raise ValueError(msg)


def core_domain_executions(program: CoreProgram) -> tuple[TypedDomainExecution, ...]:
    return tuple(
        effect for effect in program.effects if isinstance(effect, TypedDomainExecution)
    )


def core_acquisitions(program: CoreProgram) -> tuple[AcquireEffect, ...]:
    return tuple(
        effect for effect in program.effects if isinstance(effect, AcquireEffect)
    )


def core_state(program: CoreProgram) -> tuple[SetStateSpec, ...]:
    return tuple(
        effect for effect in program.effects if isinstance(effect, SetStateSpec)
    )


def set_state_field(
    *,
    resource_port_id: LogicalResourcePortId,
    capability_id: str,
    field_path: str,
    value: ScalarValueExpr | ComputeResultRef,
) -> SetStateSpec:
    """Build desired state from orthogonal capability and field identities."""

    return SetStateSpec(
        resource_target=LogicalStateResourceTarget(port_id=resource_port_id),
        capability_id=capability_id,
        field_path=field_path,
        value_use=value if isinstance(value, ComputeResultRef) else relation_use(value),
    )


def product_axis(
    id: str,
    *,
    size: int,
    kind: str | None = None,
    unit: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> ProductAxisDef:
    return ProductAxisDef(
        id=id,
        kind=kind or id,
        size=size,
        unit=unit,
        metadata=metadata or {},
    )


def shot_axis(size: int) -> ProductAxisDef:
    return product_axis("shot", size=size, kind="shot", unit="count")


def record_product(
    product: ProductDef | ProductId,
    *,
    record_id: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> tuple[ProductUse, RecordUse]:
    """Create one product-use occurrence and one durable record consumer."""

    selected_id = product.id if isinstance(product, ProductDef) else product
    use = product_use(selected_id)
    return use, RecordUse(
        id=record_id or selected_id.qualified_name,
        product_use_id=use.id,
        metadata=metadata or {},
    )
