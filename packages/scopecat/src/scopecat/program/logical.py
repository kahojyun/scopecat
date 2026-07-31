"""Canonical config-free logical program and its immutable leaf records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast, override

import scopecat.graph.values as graph_values
from scopecat.domain.program import DomainProgramDef
from scopecat.graph.relations.analysis import plan_input_refs
from scopecat.graph.relations.model import (
    ScalarExpr,
)
from scopecat.graph.relations.point_domain import PointAxes
from scopecat.graph.table_values import TableSource
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Scalar, ValueType
from scopecat.measurements.postprocessor_contract import (
    MeasurementPostprocessorKernel,
)
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
)
from scopecat.program.operations import ModuleInputPort
from scopecat.program.parameters import ParameterContract
from scopecat.program.products import ModuleProductDecl, RecordSelection
from scopecat.program.scans import AxisSpec
from scopecat.program.value_refs import PointValueDependency, ValueRef


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class AcquireId:
    """Nominal identity in the acquisition-effect symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    def prefixed(self, *scope: str) -> AcquireId:
        return AcquireId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class MeasurementPostprocessorId:
    """Nominal identity in the authored measurement-postprocessor symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol.scope

    @property
    def local_id(self) -> str:
        return self.symbol.local_id

    def prefixed(self, *scope: str) -> MeasurementPostprocessorId:
        return MeasurementPostprocessorId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True, eq=False)
class PlanExpressionSource:
    """A symbolic expression whose proof belongs to the whole logical program."""

    expression: ScalarExpr = field(repr=False)

    @property
    def source_inputs(self) -> tuple[str, ...]:
        """Return input dependencies derived from the retained expression."""

        return plan_input_refs(self.expression)

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, PlanExpressionSource) and (
            self.expression == other.expression
        )

    @override
    def __hash__(self) -> int:
        # Scalar literals may contain unhashable record cells.
        return hash((PlanExpressionSource, type(self.expression)))


@dataclass(frozen=True, slots=True, init=False)
class LiteralValueSource:
    """A closed scalar captured by value at semantic elaboration time."""

    _value: object = field(hash=False, repr=False)

    def __init__(self, value: object) -> None:
        object.__setattr__(self, "_value", _snapshot_literal(value))

    @property
    def value(self) -> object:
        """Return a defensive copy of the retained literal."""

        return _snapshot_literal(self._value)


type ValueSource = PlanExpressionSource | LiteralValueSource | TableSource


@dataclass(frozen=True, slots=True)
class ValueDef:
    """One plan-available value; operation results live on their operation."""

    id: graph_values.ValueId
    value_type: ValueType
    source: ValueSource


@dataclass(frozen=True, slots=True)
class LogicalComputeNode:
    id: graph_values.OperationId
    inputs: tuple[tuple[str, graph_values.ValueId], ...]
    result_id: graph_values.ValueId
    result_type: Scalar


@dataclass(frozen=True, slots=True)
class LogicalDomainExecution:
    """One program and its plan-stage logical product bindings."""

    id: str
    program: DomainProgramDef
    inputs: tuple[tuple[str, graph_values.ValueId], ...] = ()
    compiler_inputs: tuple[tuple[str, graph_values.ValueId], ...] = ()
    results: tuple[tuple[str, ProductId], ...] = ()


@dataclass(frozen=True, slots=True)
class LogicalMeasurementPostprocessor:
    """One point-local Python calculation with explicit product edges."""

    id: MeasurementPostprocessorId
    input: ProductId
    outputs: tuple[tuple[str, ProductId], ...]
    kernel: MeasurementPostprocessorKernel = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class AcquireResult:
    """Map one hardware acquisition result to a logical product."""

    product_id: ProductId
    result_id: str
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"acquired product {self.product_id.qualified_name!r} metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class AcquireEffect:
    """Ordered acquisition through one logical resource interface."""

    id: AcquireId
    resource_port_id: LogicalResourcePortId
    interface_id: InterfaceId
    acquisition_id: str
    results: tuple[AcquireResult, ...]
    component_path: tuple[str, ...] = ()

    @property
    def product_ids(self) -> tuple[ProductId, ...]:
        return tuple(result.product_id for result in self.results)


@dataclass(frozen=True, slots=True)
class ImplementationId:
    value: str


@dataclass(frozen=True, slots=True)
class LocalPythonImplementation:
    id: ImplementationId
    kernel: Callable[..., object] = field(repr=False, compare=False)


type LogicalEffect = (
    BindingIntent
    | EnsureStateIntent
    | InvocationIntent
    | LogicalDomainExecution
    | AcquireEffect
)


@dataclass(frozen=True, kw_only=True)
class LogicalProgram:
    """Closed, flat, config-free program consumed by compiler binding."""

    experiment_id: str
    kind: str
    inputs: dict[str, object] = field(default_factory=dict)
    input_ports: tuple[ModuleInputPort, ...] = ()
    entity_inputs: tuple[str, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    point_dependencies: tuple[PointValueDependency, ...] = ()
    parameter_overlays: tuple[AxisSpec, ...] = ()
    product_declarations: tuple[ModuleProductDecl, ...] = ()
    record_selections: tuple[RecordSelection, ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    point_domain: PointAxes[ValueRef] = ()
    value_defs: tuple[ValueDef, ...] = ()
    compute_nodes: tuple[LogicalComputeNode, ...] = ()
    measurement_postprocessors: tuple[LogicalMeasurementPostprocessor, ...] = ()
    implementations: Mapping[graph_values.OperationId, LocalPythonImplementation] = (
        field(
            default_factory=dict[
                graph_values.OperationId,
                LocalPythonImplementation,
            ],
            repr=False,
            compare=False,
        )
    )
    effects: tuple[LogicalEffect, ...] = ()
    final_state: EnsureStateIntent | None = None

    def __post_init__(self) -> None:
        if not self.experiment_id or not self.kind:
            raise ValueError("logical program requires an id and kind")
        object.__setattr__(
            self,
            "implementations",
            MappingProxyType(dict(self.implementations)),
        )

    @property
    def bindings(self) -> tuple[BindingIntent, ...]:
        effect_bindings = tuple(
            binding
            for effect in self.effects
            for binding in (
                (effect,)
                if isinstance(effect, BindingIntent)
                else effect.assignments
                if isinstance(effect, EnsureStateIntent)
                else ()
            )
        )
        return (
            *effect_bindings,
            *(() if self.final_state is None else self.final_state.assignments),
        )

    @property
    def product_effects(
        self,
    ) -> tuple[LogicalDomainExecution | AcquireEffect, ...]:
        return tuple(
            effect
            for effect in self.effects
            if isinstance(effect, LogicalDomainExecution | AcquireEffect)
        )

    @property
    def invocations(self) -> tuple[InvocationIntent, ...]:
        return tuple(
            effect for effect in self.effects if isinstance(effect, InvocationIntent)
        )

    @property
    def domain_executions(self) -> tuple[LogicalDomainExecution, ...]:
        return tuple(
            effect
            for effect in self.effects
            if isinstance(effect, LogicalDomainExecution)
        )

    @property
    def acquisitions(self) -> tuple[AcquireEffect, ...]:
        return tuple(
            effect for effect in self.effects if isinstance(effect, AcquireEffect)
        )


def _snapshot_literal(value: object) -> object:
    """Snapshot closed data without cloning opaque runtime payload bodies."""

    if isinstance(value, PayloadValue):
        return value
    if isinstance(value, EntityRef | QuantityValue):
        return value.model_copy(deep=True)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {
            key: _snapshot_literal(nested_value)
            for key, nested_value in mapping.items()
        }
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [_snapshot_literal(item) for item in items]
    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return tuple(_snapshot_literal(item) for item in items)
    # Unknown objects belong to the opaque payload/implementation boundary.
    # Their identity is semantic data; attempting a generic deepcopy would make
    # construction depend on incidental handle internals such as locks/devices.
    return value
