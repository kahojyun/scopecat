"""Backend-neutral typed value and pure-operation graph.

The graph is semantic data only.  Python kernels and authoring provenance are
carried by explicit sidecars so implementation choice and diagnostics cannot
change graph equality.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
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
    ExternalRowInterface,
    TypedPlanImport,
    VerifiedRelationPlan,
)
from scopecat.compiler.semantic.operation_contract import (
    OperationContract,
)
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Table, ValueType
from scopecat.measurements.semantics import (
    MeasurementTransformSemanticContract,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity as QuantityValue

type PlanExpression = ScalarExpr | SeriesExpr | RelationExpr
type VerifiedPlanExpression = VerifiedRelationPlan[PlanExpression]
type SemanticValueType = ValueType


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


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
class AcquireId:
    """Nominal identity in the acquisition-effect symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    def prefixed(self, *scope: str) -> AcquireId:
        return AcquireId(self.symbol.prefixed(*scope))


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
    _row_interface: ExternalRowInterface = field(hash=False, repr=False)
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
        object.__setattr__(self, "_row_interface", verified_plan.external_row_interface)
        object.__setattr__(self, "_verified_plan", verified_plan)

    @property
    def expression(self) -> PlanExpression:
        """Return a defensive copy of the retained plan semantics."""

        return deepcopy(self._expression)

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
    def verified_plan(self) -> VerifiedPlanExpression:
        return self._verified_plan


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
class OperationOutputSource:
    operation_id: OperationId
    port: str = "result"

    def __post_init__(self) -> None:
        if not self.port:
            msg = "operation output port ids must be non-empty"
            raise ValueError(msg)


type ValueSource = PlanExpressionSource | LiteralValueSource | OperationOutputSource


@dataclass(frozen=True, slots=True)
class ValueDef:
    """The sole owner of a value's type, source, and lexical scope."""

    id: ValueId
    value_type: SemanticValueType
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
    resource_port: LogicalResourcePortId
    target_entities: tuple[ValueUse, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id or not self.field_path:
            msg = "state row regions require capability and field ids"
            raise ValueError(msg)

    @property
    def body_entries(self) -> tuple[tuple[tuple[str, ...], ValueUse], ...]:
        entries: list[tuple[tuple[str, ...], ValueUse]] = [(("value",), self.value)]
        entries.extend(
            (("target_entities", str(index)), use)
            for index, use in enumerate(self.target_entities)
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
class DomainResourcePortDef:
    id: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticDomainProgram:
    """Opaque dialect program retained without core interpretation."""

    id: DomainProgramId
    dialect_id: str
    dialect_version: str
    body: object = field(repr=False)
    input_ports: tuple[DomainInputPortDef, ...] = ()
    result_ports: tuple[DomainResultPortDef, ...] = ()
    resource_ports: tuple[DomainResourcePortDef, ...] = ()

    def __post_init__(self) -> None:
        if not self.dialect_id or not self.dialect_version:
            raise ValueError("domain dialect identity must be non-empty")
        _require_unique_names(
            "domain input port", tuple((p.id, p) for p in self.input_ports)
        )
        _require_unique_names(
            "domain result port", tuple((p.id, p) for p in self.result_ports)
        )
        _require_unique_names(
            "domain resource port", tuple((p.id, p) for p in self.resource_ports)
        )

    def __deepcopy__(self, _memo: dict[int, object]) -> SemanticDomainProgram:
        return self


@dataclass(frozen=True, slots=True)
class SemanticDomainExecution:
    """One program and its plan-stage logical product bindings."""

    id: str
    program: SemanticDomainProgram
    inputs: tuple[tuple[str, ValueUse], ...] = ()
    results: tuple[tuple[str, ProductId], ...] = ()
    resources: tuple[tuple[str, LogicalResourcePortId], ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("semantic domain execution id must be non-empty")
        _require_unique_names("domain execution input", self.inputs)
        _require_unique_names("domain execution result", self.results)
        _require_unique_names("domain execution resource", self.resources)


@dataclass(frozen=True, slots=True)
class SemanticMeasurementTransform:
    """One pure authored transform with explicit logical-product edges."""

    id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    inputs: tuple[tuple[str, ProductId], ...] = ()
    outputs: tuple[tuple[str, ProductId], ...] = ()

    def __post_init__(self) -> None:
        _require_unique_names("measurement transform input", self.inputs)
        _require_unique_names("measurement transform output", self.outputs)
        if not self.outputs:
            msg = "semantic measurement transforms require at least one output"
            raise ValueError(msg)


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
class AcquireProduct:
    """Provider-facing mapping for one product in an acquisition effect."""

    product_id: ProductId
    provider_key: str
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.provider_key:
            raise ValueError("acquired product provider key must be non-empty")
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
    """An ordered request to realize selected instrument products."""

    id: AcquireId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    products: tuple[AcquireProduct, ...]

    def __post_init__(self) -> None:
        if not self.products:
            raise ValueError("acquire effects require at least one product")
        if not self.capability_id:
            raise ValueError("acquire effect capability must be non-empty")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("acquire effect product ids must be unique")
        provider_keys = tuple(product.provider_key for product in self.products)
        if len(provider_keys) != len(set(provider_keys)):
            raise ValueError("acquire effect provider keys must be unique")

    @property
    def product_ids(self) -> tuple[ProductId, ...]:
        return tuple(product.product_id for product in self.products)


@dataclass(frozen=True, slots=True)
class BindingEffectRef:
    """Ordered reference to one assembly-level desired-state binding."""

    index: int

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("binding effect indices must be non-negative")


@dataclass(frozen=True, slots=True)
class StateEffectRef:
    """Ordered reference to one semantic row-scoped state effect."""

    id: RowRegionId


@dataclass(frozen=True, slots=True)
class ActionEffectRef:
    """Ordered reference to one semantic instrument action."""

    id: ActionId


@dataclass(frozen=True, slots=True)
class DomainEffectRef:
    """Ordered reference to one semantic domain-program execution."""

    id: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("domain effect ids must be non-empty")


@dataclass(frozen=True, slots=True)
class AcquireEffectRef:
    """Ordered reference to one semantic acquisition effect."""

    id: AcquireId


type SemanticEffectRef = (
    BindingEffectRef
    | StateEffectRef
    | ActionEffectRef
    | DomainEffectRef
    | AcquireEffectRef
)


@dataclass(frozen=True, slots=True)
class SemanticGraphIR:
    value_defs: tuple[ValueDef, ...] = ()
    operations: tuple[SemanticOperation, ...] = ()
    measurement_transforms: tuple[SemanticMeasurementTransform, ...] = ()
    domain_executions: tuple[SemanticDomainExecution, ...] = ()
    actions: tuple[InstrumentActionEffect, ...] = ()
    acquisitions: tuple[AcquireEffect, ...] = ()
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
    domain_sources: tuple[tuple[str, SourceAnchor], ...] = ()
    acquire_sources: tuple[tuple[AcquireId, SourceAnchor], ...] = ()


def merge_semantic_graphs(*graphs: SemanticGraphIR) -> SemanticGraphIR:
    return SemanticGraphIR(
        value_defs=tuple(item for graph in graphs for item in graph.value_defs),
        operations=tuple(item for graph in graphs for item in graph.operations),
        measurement_transforms=tuple(
            item for graph in graphs for item in graph.measurement_transforms
        ),
        domain_executions=tuple(
            execution for graph in graphs for execution in graph.domain_executions
        ),
        actions=tuple(item for graph in graphs for item in graph.actions),
        acquisitions=tuple(item for graph in graphs for item in graph.acquisitions),
        row_regions=tuple(item for graph in graphs for item in graph.row_regions),
    )


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
        domain_sources=tuple(
            item for source_map in source_maps for item in source_map.domain_sources
        ),
        acquire_sources=tuple(
            item for source_map in source_maps for item in source_map.acquire_sources
        ),
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


def _require_unique_names(label: str, values: tuple[tuple[str, object], ...]) -> None:
    names = tuple(name for name, _value in values)
    if any(not name for name in names):
        msg = f"{label} names must be non-empty"
        raise ValueError(msg)
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        msg = f"duplicate {label} names: " + ", ".join(duplicates)
        raise ValueError(msg)
