"""Backend-neutral typed value and pure-operation graph.

The graph is semantic data only.  Python kernels and authoring provenance are
carried by explicit sidecars so implementation choice and diagnostics cannot
change graph equality.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.relations.analysis import (
    PlanReferenceKind,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.verification import (
    RowType,
    TypedPlanImport,
    VerifiedRelationPlan,
)
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
)
from scopecat.compiler.semantic.operation_contract import (
    OperationContract,
)
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Route,
    Table,
    ValueType,
)
from scopecat.measurements.semantics import (
    MeasurementTransformRate,
    MeasurementTransformSemanticContract,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity as QuantityValue

type PlanExpression = ScalarExpr | SeriesExpr | RelationExpr
type VerifiedPlanExpression = VerifiedRelationPlan[PlanExpression]
type SemanticValueType = ValueType | Route


@dataclass(frozen=True, slots=True)
class ActionId:
    """Nominal identity in the semantic instrument-action symbol space."""

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

    def prefixed(self, *scope: str) -> ActionId:
        return ActionId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class OperationId:
    """Nominal identity in the semantic-operation symbol space."""

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

    def prefixed(self, *scope: str) -> OperationId:
        return OperationId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class DomainProgramId:
    """Nominal identity in the domain-program symbol space."""

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

    def prefixed(self, *scope: str) -> DomainProgramId:
        return DomainProgramId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class MeasurementTransformId:
    """Nominal identity in the authored measurement-transform symbol space."""

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

    def prefixed(self, *scope: str) -> MeasurementTransformId:
        return MeasurementTransformId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class ValueId:
    """Nominal identity in the semantic-value symbol space."""

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

    def prefixed(self, *scope: str) -> ValueId:
        return ValueId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class RowRegionId:
    """Nominal identity of one lexical semantic row region."""

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

    def prefixed(self, *scope: str) -> RowRegionId:
        return RowRegionId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class RowArgumentDef:
    """The typed row argument introduced by a semantic region."""

    id: RowScopeId
    value_type: Table


def state_each_region_id(row_argument_id: RowScopeId) -> RowRegionId:
    """Derive a region identity without conflating its nominal namespace."""

    symbol = row_argument_id.symbol
    return RowRegionId(
        SymbolId(
            scope=(*symbol.scope, "state_regions"),
            local_id=symbol.local_id,
        )
    )


def operation_result_id(operation_id: OperationId, port: str = "result") -> ValueId:
    if not port:
        msg = "operation output port ids must be non-empty"
        raise ValueError(msg)
    return ValueId(
        SymbolId(
            scope=(*operation_id.scope, operation_id.local_id, "outputs"),
            local_id=port,
        )
    )


@dataclass(frozen=True, slots=True, init=False)
class PlanExpressionSource:
    _expression: PlanExpression = field(hash=False, repr=False)
    _certified_type: ValueType
    _imports: tuple[TypedPlanImport, ...] = field(hash=False, repr=False)
    _row_signature: tuple[
        RowType | None,
        RowType | None,
        RowType | None,
        tuple[tuple[RowScopeId, RowType], ...],
    ] = field(hash=False, repr=False)
    _verified_plan: VerifiedPlanExpression = field(
        hash=False,
        repr=False,
        compare=False,
    )

    def __init__(
        self,
        verified_plan: VerifiedPlanExpression,
    ) -> None:
        object.__setattr__(self, "_expression", verified_plan.root)
        object.__setattr__(self, "_certified_type", verified_plan.certified_type)
        object.__setattr__(self, "_imports", verified_plan.imports)
        object.__setattr__(
            self,
            "_row_signature",
            _used_row_signature(verified_plan),
        )
        object.__setattr__(self, "_verified_plan", verified_plan)

    @property
    def expression(self) -> PlanExpression:
        """Return a defensive copy of the retained plan semantics."""

        return self._expression.model_copy(deep=True)

    @property
    def source_inputs(self) -> tuple[str, ...]:
        """Return input dependencies derived from the retained expression."""

        return self._verified_plan.references.ids(
            PlanReferenceKind.INPUT_SCALAR,
            PlanReferenceKind.INPUT_SERIES,
            PlanReferenceKind.INPUT_TABLE,
        )

    @property
    def certified_type(self) -> ValueType:
        return self._certified_type

    @property
    def imports(self) -> tuple[TypedPlanImport, ...]:
        return self._imports

    @property
    def used_row_signature(
        self,
    ) -> tuple[
        RowType | None,
        RowType | None,
        RowType | None,
        tuple[tuple[RowScopeId, RowType], ...],
    ]:
        return self._row_signature

    @property
    def verified_plan(self) -> VerifiedPlanExpression:
        return self._verified_plan


def _used_row_signature(
    verified_plan: VerifiedPlanExpression,
) -> tuple[
    RowType | None,
    RowType | None,
    RowType | None,
    tuple[tuple[RowScopeId, RowType], ...],
]:
    references = verified_plan.references.references
    free = verified_plan.free_row_references.references
    bindings = verified_plan.bindings
    point_names = {
        reference.id
        for reference in references
        if reference.kind is PlanReferenceKind.POINT_COLUMN
    }
    point_binding = bindings.point_row
    if point_names and point_binding is not None:
        columns = {column.id: column for column in point_binding.columns}
        selected_ids = {
            name if name in columns else name.split(".", maxsplit=1)[0]
            for name in point_names
        }
        selected_columns = tuple(
            column for column in point_binding.columns if column.id in selected_ids
        )
        point = (
            RowType(selected_columns, point_binding.allow_extra_columns)
            if selected_columns
            else None
        )
    else:
        point = None
    current = (
        bindings.current_row
        if any(
            reference.kind is PlanReferenceKind.CURRENT_COLUMN
            and reference.row_scope_id is None
            for reference in free
        )
        else None
    )
    outer = (
        bindings.outer_row
        if any(reference.kind is PlanReferenceKind.OUTER_COLUMN for reference in free)
        else None
    )
    nominal_ids = sorted(
        {
            reference.row_scope_id
            for reference in free
            if reference.kind is PlanReferenceKind.CURRENT_COLUMN
            and reference.row_scope_id is not None
        },
        key=lambda item: item.qualified_name,
    )
    nominal = tuple(
        (row_scope_id, bindings.row_arguments[row_scope_id])
        for row_scope_id in nominal_ids
    )
    return point, current, outer, nominal


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


@dataclass(frozen=True, slots=True)
class RouteValueSource:
    port_id: LogicalResourcePortId


@dataclass(frozen=True, slots=True)
class OperationOutputSource:
    operation_id: OperationId
    port: str = "result"

    def __post_init__(self) -> None:
        if not self.port:
            msg = "operation output port ids must be non-empty"
            raise ValueError(msg)


type ValueSource = (
    PlanExpressionSource | LiteralValueSource | RouteValueSource | OperationOutputSource
)


@dataclass(frozen=True, slots=True)
class ValueDef:
    """The sole owner of a value's type and availability facts."""

    id: ValueId
    value_type: SemanticValueType
    availability: ValueAvailability
    source: ValueSource
    owner_region_id: RowRegionId | None = None


@dataclass(frozen=True, slots=True)
class ValueUse:
    """A use contains only the identity of its target definition."""

    value_id: ValueId


@dataclass(frozen=True, slots=True)
class StateEachRegion:
    """A typed relation-row binder and the state uses in its lexical body."""

    id: RowRegionId
    row_argument: RowArgumentDef
    relation: ValueUse
    capability_id: str
    field_path: str
    value: ValueUse
    resource: ValueUse | None = None
    route_entities: tuple[ValueUse, ...] = ()
    resource_port: LogicalResourcePortId | None = None

    def __post_init__(self) -> None:
        if not self.capability_id or not self.field_path:
            msg = "state row regions require capability and field ids"
            raise ValueError(msg)
        if (self.resource is None) == (self.resource_port is None):
            msg = "state row regions require exactly one resource source"
            raise ValueError(msg)

    @property
    def body_entries(self) -> tuple[tuple[tuple[str, ...], ValueUse], ...]:
        entries: list[tuple[tuple[str, ...], ValueUse]] = (
            [(("resource",), self.resource)] if self.resource is not None else []
        )
        entries.append((("value",), self.value))
        entries.extend(
            (("route_entities", str(index)), use)
            for index, use in enumerate(self.route_entities)
        )
        return tuple(entries)


@dataclass(frozen=True, slots=True)
class SemanticOperation:
    id: OperationId
    contract: OperationContract
    inputs: tuple[tuple[str, ValueUse], ...]
    outputs: tuple[tuple[str, ValueId], ...]
    owner_region_id: RowRegionId | None = None

    def __post_init__(self) -> None:
        _require_unique_names("operation input", self.inputs)
        _require_unique_names("operation output", self.outputs)
        if not self.outputs:
            msg = "semantic operations require at least one output"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainInputPortDef:
    id: str
    value_type: ValueType

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("domain input port ids must be non-empty")


@dataclass(frozen=True, slots=True)
class DomainResultPortDef:
    id: str
    contract: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("domain result port ids must be non-empty")


@dataclass(frozen=True, slots=True)
class SemanticDomainProgram:
    """Opaque dialect program retained without core interpretation."""

    id: DomainProgramId
    dialect_id: str
    dialect_version: str
    body: object = field(repr=False)
    input_ports: tuple[DomainInputPortDef, ...] = ()
    result_ports: tuple[DomainResultPortDef, ...] = ()

    def __post_init__(self) -> None:
        if not self.dialect_id or not self.dialect_version:
            raise ValueError("domain dialect identity must be non-empty")
        _require_unique_names(
            "domain input port", tuple((p.id, p) for p in self.input_ports)
        )
        _require_unique_names(
            "domain result port", tuple((p.id, p) for p in self.result_ports)
        )

    def __deepcopy__(self, _memo: dict[int, object]) -> SemanticDomainProgram:
        return self


@dataclass(frozen=True, slots=True)
class SemanticDomainExecution:
    """One program and its plan-stage logical product bindings."""

    program: SemanticDomainProgram
    inputs: tuple[tuple[str, ValueUse], ...] = ()
    results: tuple[tuple[str, ProductId], ...] = ()

    def __post_init__(self) -> None:
        _require_unique_names("domain execution input", self.inputs)
        _require_unique_names("domain execution result", self.results)


@dataclass(frozen=True, slots=True)
class SemanticMeasurementTransform:
    """One pure authored transform with explicit logical-product edges."""

    id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    rate: MeasurementTransformRate
    inputs: tuple[tuple[str, ProductId], ...] = ()
    outputs: tuple[tuple[str, ProductId], ...] = ()

    def __post_init__(self) -> None:
        if self.rate != "point":
            msg = "semantic measurement transform rate is unsupported"
            raise ValueError(msg)
        _require_unique_names("measurement transform input", self.inputs)
        _require_unique_names("measurement transform output", self.outputs)
        if not self.outputs:
            msg = "semantic measurement transforms require at least one output"
            raise ValueError(msg)
        object.__setattr__(self, "semantic", self.semantic.model_copy(deep=True))


@dataclass(frozen=True, slots=True)
class InstrumentActionEffect:
    """An ordered point effect that must be delivered exactly once per attempt."""

    id: ActionId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    fields: tuple[tuple[str, ValueUse], ...] = ()

    def __post_init__(self) -> None:
        _require_unique_names("action field", self.fields)
        if not self.capability_id:
            msg = "instrument action capability ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SemanticGraphIR:
    value_defs: tuple[ValueDef, ...] = ()
    operations: tuple[SemanticOperation, ...] = ()
    measurement_transforms: tuple[SemanticMeasurementTransform, ...] = ()
    domain_execution: SemanticDomainExecution | None = None
    actions: tuple[InstrumentActionEffect, ...] = ()
    row_regions: tuple[StateEachRegion, ...] = ()


@dataclass(frozen=True, slots=True)
class ImplementationId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "implementation ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class LocalPythonImplementation:
    id: ImplementationId
    operation_id: OperationId
    operation_contract: OperationContract
    kernel: Callable[..., object] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self.kernel):
            msg = "local Python implementation kernel must be callable"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class ImplementationCatalog:
    local_python: tuple[LocalPythonImplementation, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    kind: str
    declaration_id: str
    composition_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.kind or not self.declaration_id:
            msg = "semantic source anchors require kind and declaration id"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SourceMap:
    operation_sources: tuple[tuple[OperationId, SourceAnchor], ...] = ()
    value_sources: tuple[tuple[ValueId, SourceAnchor], ...] = ()
    action_sources: tuple[tuple[ActionId, SourceAnchor], ...] = ()
    row_region_sources: tuple[tuple[RowRegionId, SourceAnchor], ...] = ()


def merge_semantic_graphs(*graphs: SemanticGraphIR) -> SemanticGraphIR:
    return SemanticGraphIR(
        value_defs=tuple(item for graph in graphs for item in graph.value_defs),
        operations=tuple(item for graph in graphs for item in graph.operations),
        measurement_transforms=tuple(
            item for graph in graphs for item in graph.measurement_transforms
        ),
        domain_execution=_merge_optional_domain_value(
            "domain execution",
            tuple(graph.domain_execution for graph in graphs),
        ),
        actions=tuple(item for graph in graphs for item in graph.actions),
        row_regions=tuple(item for graph in graphs for item in graph.row_regions),
    )


def _merge_optional_domain_value[T](
    label: str,
    values: tuple[T | None, ...],
) -> T | None:
    selected = tuple(value for value in values if value is not None)
    if len(selected) > 1:
        raise ValueError(f"semantic graph merge found more than one {label}")
    return selected[0] if selected else None


def merge_implementation_catalogs(
    *catalogs: ImplementationCatalog,
) -> ImplementationCatalog:
    return ImplementationCatalog(
        local_python=tuple(
            item for catalog in catalogs for item in catalog.local_python
        )
    )


def merge_source_maps(*source_maps: SourceMap) -> SourceMap:
    return SourceMap(
        operation_sources=tuple(
            item for source_map in source_maps for item in source_map.operation_sources
        ),
        value_sources=tuple(
            item for source_map in source_maps for item in source_map.value_sources
        ),
        action_sources=tuple(
            item for source_map in source_maps for item in source_map.action_sources
        ),
        row_region_sources=tuple(
            item for source_map in source_maps for item in source_map.row_region_sources
        ),
    )


def _snapshot_literal(value: object) -> object:
    """Snapshot closed data without cloning opaque runtime payload bodies."""

    if isinstance(value, PayloadValue):
        return value.model_copy(update={"payload": value.payload})
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


def _require_unique_names(label: str, values: tuple[tuple[str, object], ...]) -> None:
    names = tuple(name for name, _value in values)
    if any(not name for name in names):
        msg = f"{label} names must be non-empty"
        raise ValueError(msg)
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        msg = f"duplicate {label} names: " + ", ".join(duplicates)
        raise ValueError(msg)


__all__ = [
    "ActionId",
    "ImplementationCatalog",
    "ImplementationId",
    "InstrumentActionEffect",
    "LiteralValueSource",
    "LocalPythonImplementation",
    "MeasurementTransformId",
    "OperationId",
    "OperationOutputSource",
    "PlanExpression",
    "PlanExpressionSource",
    "RouteValueSource",
    "RowArgumentDef",
    "RowRegionId",
    "SemanticGraphIR",
    "SemanticMeasurementTransform",
    "SemanticOperation",
    "SemanticValueType",
    "SourceAnchor",
    "SourceMap",
    "StateEachRegion",
    "ValueDef",
    "ValueId",
    "ValueSource",
    "ValueUse",
    "merge_implementation_catalogs",
    "merge_semantic_graphs",
    "merge_source_maps",
    "operation_result_id",
    "state_each_region_id",
]
