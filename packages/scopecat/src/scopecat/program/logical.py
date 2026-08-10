"""Canonical config-free logical program and its immutable leaf records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import scopecat.program.value_graph as graph_values
from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.point_identity import PointDomainLayout
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import DataType, ValueType
from scopecat.program.bindings import (
    ResourcePort,
)
from scopecat.program.expressions import ArrayExpr, ScalarExpr
from scopecat.program.measurement_contracts import (
    MeasurementPostprocessorKernel,
)
from scopecat.program.operations import ModuleInputPort
from scopecat.program.parameters import ParameterContract
from scopecat.program.point_domain import PointAxes
from scopecat.program.products import ModuleProductDecl, RecordSelection
from scopecat.program.recording import (
    LogicalRecordSelection,
    LogicalValueRecordSelection,
)
from scopecat.program.scans import AxisSpec, PointTraversal, RepeatMode
from scopecat.program.table_values import TableSource
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


type ValueSource = ArrayExpr | ScalarExpr | TableSource


@dataclass(frozen=True, slots=True)
class ValueDef:
    """One plan-available value; operation results live on their operation."""

    id: ValueId
    value_type: ValueType
    source: ValueSource


@dataclass(frozen=True, slots=True)
class LogicalComputeNode:
    id: graph_values.OperationId
    inputs: tuple[tuple[str, ValueId], ...]
    input_types: tuple[tuple[str, DataType], ...]
    result_id: ValueId
    result_type: DataType


@dataclass(frozen=True, slots=True)
class LogicalDomainExecution:
    """One program and its plan-stage logical product bindings."""

    id: str
    program: DomainProgramDef
    inputs: tuple[tuple[str, ValueId], ...] = ()
    compiler_inputs: tuple[tuple[str, ValueId], ...] = ()
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
class LogicalStateAssignment:
    """One closed desired-state edge in the logical value graph."""

    port_id: LogicalResourcePortId
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    property_id: str
    value_id: ValueId


@dataclass(frozen=True, slots=True)
class LogicalEnsureState:
    """One coherent group of logical desired-state assignments."""

    assignments: tuple[LogicalStateAssignment, ...]


@dataclass(frozen=True, slots=True)
class LogicalInvocationArgument:
    id: str
    value_id: ValueId


@dataclass(frozen=True, slots=True)
class LogicalInvocation:
    """One closed operation invocation over logical resources and values."""

    id: str
    port_id: LogicalResourcePortId
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    operation_id: str
    arguments: tuple[LogicalInvocationArgument, ...]
    scope: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return SymbolId(scope=self.scope, local_id=self.id).qualified_name


@dataclass(frozen=True, slots=True)
class ImplementationId:
    value: str


@dataclass(frozen=True, slots=True)
class LocalPythonImplementation:
    id: ImplementationId
    kernel: Callable[..., object] = field(repr=False, compare=False)


type LogicalEffect = (
    LogicalStateAssignment
    | LogicalEnsureState
    | LogicalInvocation
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
    record_selections: tuple[LogicalRecordSelection, ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    point_domain: PointAxes[ValueRef] = ()
    point_domain_layout: PointDomainLayout = "product_grid"
    point_repeat: int = 1
    point_repeat_mode: RepeatMode = "point"
    point_traversal: PointTraversal = "forward"
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
    success_state: LogicalEnsureState | None = None

    def __post_init__(self) -> None:
        if not self.experiment_id or not self.kind:
            raise ValueError("logical program requires an id and kind")
        object.__setattr__(
            self,
            "implementations",
            MappingProxyType(dict(self.implementations)),
        )

    @property
    def product_record_selections(self) -> tuple[RecordSelection, ...]:
        return tuple(
            selection
            for selection in self.record_selections
            if isinstance(selection, RecordSelection)
        )

    @property
    def value_record_selections(self) -> tuple[LogicalValueRecordSelection, ...]:
        return tuple(
            selection
            for selection in self.record_selections
            if isinstance(selection, LogicalValueRecordSelection)
        )

    @property
    def bindings(self) -> tuple[LogicalStateAssignment, ...]:
        effect_bindings = tuple(
            binding
            for effect in self.effects
            for binding in (
                (effect,)
                if isinstance(effect, LogicalStateAssignment)
                else effect.assignments
                if isinstance(effect, LogicalEnsureState)
                else ()
            )
        )
        return (
            *effect_bindings,
            *(() if self.success_state is None else self.success_state.assignments),
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
    def invocations(self) -> tuple[LogicalInvocation, ...]:
        return tuple(
            effect for effect in self.effects if isinstance(effect, LogicalInvocation)
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
