"""Backend-neutral typed value and pure-operation graph.

The graph is semantic data only.  Python kernels and authoring provenance are
carried by explicit sidecars so implementation choice and diagnostics cannot
change graph equality.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat._operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    EffectClass,
    OpaqueSemantics,
    OperationContract,
    OperationContractIssue,
    PlacementConstraint,
    Portability,
    ScalarBinarySemantics,
    operation_contract_issues,
    scalar_binary_operation_contract,
)
from scopecat._relation_analysis import (
    PlanReferenceKind,
)
from scopecat._relation_verification import (
    ParameterLookupSignature,
    PlanImportNamespace,
    RowType,
    TypedPlanImport,
    VerifiedRelationPlan,
)
from scopecat._relations import RelationExpr, RowScopeId, ScalarExpr, SeriesExpr
from scopecat._resource_identity import LogicalResourcePortId
from scopecat._scalar_operators import is_scalar_operator, scalar_operator_result_type
from scopecat._symbols import SymbolId
from scopecat._value_availability import (
    ValueAvailability,
    ValueRate,
    ValueStage,
)
from scopecat._value_type_compatibility import is_assignable
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity as QuantityValue
from scopecat.models.value import PayloadValue
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.value_types import (
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Route,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.value_validation import ValueValidationError, validate_literal

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
        if not isinstance(cast("object", verified_plan), VerifiedRelationPlan):
            msg = "plan expression sources require a VerifiedRelationPlan"
            raise TypeError(msg)
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

    @property
    def body_uses(self) -> tuple[ValueUse, ...]:
        return tuple(use for _path, use in self.body_entries)


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


@dataclass(frozen=True, slots=True)
class VerifiedSemanticGraph:
    graph: SemanticGraphIR
    value_defs: Mapping[ValueId, ValueDef] = field(
        init=False,
        compare=False,
        hash=False,
    )
    row_regions: Mapping[RowRegionId, StateEachRegion] = field(
        init=False,
        compare=False,
        hash=False,
    )
    actions: Mapping[ActionId, InstrumentActionEffect] = field(
        init=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        definitions = {
            definition.id: definition for definition in self.graph.value_defs
        }
        regions = {region.id: region for region in self.graph.row_regions}
        actions = {action.id: action for action in self.graph.actions}
        object.__setattr__(self, "value_defs", MappingProxyType(definitions))
        object.__setattr__(self, "row_regions", MappingProxyType(regions))
        object.__setattr__(self, "actions", MappingProxyType(actions))


def verify_semantic_graph(graph: SemanticGraphIR) -> VerifiedSemanticGraph:
    """Validate closure and normalize dataflow while preserving state order."""

    problems: list[Problem] = []
    definitions, ambiguous_value_ids = _definitions_by_id(
        graph.value_defs,
        problems,
    )
    operations, ambiguous_operation_ids = _operations_by_id(
        graph.operations,
        problems,
    )
    actions, ambiguous_action_ids = _actions_by_id(graph.actions, problems)
    regions, ambiguous_region_ids = _regions_by_id(graph.row_regions, problems)
    unambiguous_operations = tuple(
        operation
        for operation in graph.operations
        if operation.id not in ambiguous_operation_ids
    )
    _verify_uses(
        unambiguous_operations,
        definitions,
        ambiguous_value_ids,
        problems,
    )
    _verify_actions(
        tuple(actions.values()),
        definitions,
        ambiguous_value_ids,
        problems,
    )
    _verify_outputs(
        unambiguous_operations,
        definitions,
        ambiguous_value_ids,
        ambiguous_operation_ids,
        problems,
    )
    _verify_row_regions(
        tuple(regions.values()),
        definitions,
        ambiguous_value_ids,
        problems,
    )
    _verify_operation_regions(
        unambiguous_operations,
        definitions,
        regions,
        ambiguous_region_ids,
        problems,
    )
    _verify_value_sources(
        tuple(definitions.values()),
        regions,
        ambiguous_region_ids,
        problems,
    )
    _verify_plan_environment_consistency(tuple(definitions.values()), problems)
    _verify_operation_contracts(unambiguous_operations, problems)
    _verify_opaque_operations(unambiguous_operations, definitions, problems)
    _verify_scalar_operations(unambiguous_operations, definitions, problems)
    ordered_operations = _topological_operations(
        unambiguous_operations,
        definitions,
        operations,
        ambiguous_operation_ids,
        problems,
    )
    if problems:
        from scopecat.errors import CheckFailed

        raise CheckFailed(problems)
    ordered_defs = tuple(
        sorted(graph.value_defs, key=lambda item: item.id.qualified_name)
    )
    normalized = SemanticGraphIR(
        value_defs=ordered_defs,
        operations=ordered_operations,
        actions=tuple(
            action for action in graph.actions if action.id not in ambiguous_action_ids
        ),
        # State regions retain authored order: desired-state sequencing is
        # semantic, unlike declaration maps normalized only by identity.
        row_regions=graph.row_regions,
    )
    return VerifiedSemanticGraph(normalized)


def verify_implementation_catalog(
    graph: SemanticGraphIR,
    catalog: ImplementationCatalog,
) -> ImplementationCatalog:
    """Verify implementation identity, ownership, and declared contract."""

    problems: list[Problem] = []
    operations = {operation.id: operation for operation in graph.operations}
    implementation_ids: set[ImplementationId] = set()
    for implementation in sorted(
        catalog.local_python,
        key=lambda item: (
            item.operation_id.qualified_name,
            item.id.value,
            (
                item.operation_contract != operation.contract
                if (operation := operations.get(item.operation_id)) is not None
                else False
            ),
        ),
    ):
        if implementation.id in implementation_ids:
            problems.append(
                _problem(
                    "semantic_implementation_duplicate",
                    f"implementation {implementation.id.value!r} is duplicated",
                    "implementations",
                    implementation.id.value,
                    category=ProblemCategory.CONFLICT,
                )
            )
        implementation_ids.add(implementation.id)
        operation = operations.get(implementation.operation_id)
        if operation is None:
            problems.append(
                _problem(
                    "semantic_implementation_orphan",
                    "implementation references unknown operation "
                    f"{implementation.operation_id.qualified_name!r}",
                    "implementations",
                    implementation.id.value,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        if implementation.operation_contract != operation.contract:
            problems.append(
                _problem(
                    "semantic_implementation_contract_mismatch",
                    "implementation contract does not match its semantic operation: "
                    f"{implementation.id.value!r}",
                    "implementations",
                    implementation.id.value,
                    category=ProblemCategory.CONFLICT,
                )
            )
    if problems:
        from scopecat.errors import CheckFailed

        raise CheckFailed(problems)
    return ImplementationCatalog(
        local_python=tuple(
            sorted(
                catalog.local_python,
                key=lambda item: (
                    item.operation_id.qualified_name,
                    item.id.value,
                ),
            )
        )
    )


def verify_source_map(graph: SemanticGraphIR, source_map: SourceMap) -> SourceMap:
    """Require one provenance anchor for every semantic declaration."""

    problems: list[Problem] = []
    operation_ids = {operation.id for operation in graph.operations}
    value_ids = {definition.id for definition in graph.value_defs}
    row_region_ids = {region.id for region in graph.row_regions}
    action_ids = {action.id for action in graph.actions}
    operation_sources = _verify_source_entries(
        "operation",
        source_map.operation_sources,
        operation_ids,
        problems,
    )
    value_sources = _verify_source_entries(
        "value",
        source_map.value_sources,
        value_ids,
        problems,
    )
    action_sources = _verify_source_entries(
        "action",
        source_map.action_sources,
        action_ids,
        problems,
    )
    row_region_sources = _verify_source_entries(
        "row_region",
        source_map.row_region_sources,
        row_region_ids,
        problems,
    )
    if problems:
        from scopecat.errors import CheckFailed

        raise CheckFailed(problems)
    return SourceMap(
        operation_sources=tuple(
            sorted(operation_sources.items(), key=lambda item: item[0].qualified_name)
        ),
        value_sources=tuple(
            sorted(value_sources.items(), key=lambda item: item[0].qualified_name)
        ),
        action_sources=tuple(
            sorted(action_sources.items(), key=lambda item: item[0].qualified_name)
        ),
        row_region_sources=tuple(
            sorted(
                row_region_sources.items(),
                key=lambda item: item[0].qualified_name,
            )
        ),
    )


def _verify_source_entries[
    Identity: (ActionId, OperationId, RowRegionId, ValueId),
](
    kind: str,
    entries: tuple[tuple[Identity, SourceAnchor], ...],
    expected: set[Identity],
    problems: list[Problem],
) -> dict[Identity, SourceAnchor]:
    selected: dict[Identity, SourceAnchor] = {}
    for identity, anchor in entries:
        if identity in selected:
            problems.append(
                _problem(
                    f"semantic_source_map_{kind}_duplicate",
                    f"{kind} {identity.qualified_name!r} has duplicate source anchors",
                    "source_map",
                    kind + "s",
                    identity.qualified_name,
                    category=ProblemCategory.CONFLICT,
                )
            )
        selected[identity] = anchor
        if identity not in expected:
            problems.append(
                _problem(
                    f"semantic_source_map_{kind}_orphan",
                    f"source anchor references unknown {kind} "
                    f"{identity.qualified_name!r}",
                    "source_map",
                    kind + "s",
                    identity.qualified_name,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
    for identity in sorted(
        expected - set(selected), key=lambda item: item.qualified_name
    ):
        problems.append(
            _problem(
                f"semantic_source_map_{kind}_missing",
                f"{kind} {identity.qualified_name!r} has no source anchor",
                "source_map",
                kind + "s",
                identity.qualified_name,
                category=ProblemCategory.NOT_FOUND,
            )
        )
    return selected


def merge_semantic_graphs(*graphs: SemanticGraphIR) -> SemanticGraphIR:
    return SemanticGraphIR(
        value_defs=tuple(item for graph in graphs for item in graph.value_defs),
        operations=tuple(item for graph in graphs for item in graph.operations),
        actions=tuple(item for graph in graphs for item in graph.actions),
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
    )


def _definitions_by_id(
    definitions: tuple[ValueDef, ...],
    problems: list[Problem],
) -> tuple[dict[ValueId, ValueDef], frozenset[ValueId]]:
    grouped: dict[ValueId, list[ValueDef]] = {}
    for definition in definitions:
        grouped.setdefault(definition.id, []).append(definition)
    ambiguous = frozenset(
        value_id for value_id, declarations in grouped.items() if len(declarations) > 1
    )
    for value_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "semantic_value_definition_duplicate",
                f"value {value_id.qualified_name!r} is defined more than once",
                "values",
                value_id.qualified_name,
                category=ProblemCategory.CONFLICT,
            )
        )
    selected = {
        value_id: grouped[value_id][0]
        for value_id in sorted(grouped, key=lambda item: item.qualified_name)
        if value_id not in ambiguous
    }
    return selected, ambiguous


def _operations_by_id(
    operations: tuple[SemanticOperation, ...],
    problems: list[Problem],
) -> tuple[dict[OperationId, SemanticOperation], frozenset[OperationId]]:
    grouped: dict[OperationId, list[SemanticOperation]] = {}
    for operation in operations:
        grouped.setdefault(operation.id, []).append(operation)
    ambiguous = frozenset(
        operation_id
        for operation_id, declarations in grouped.items()
        if len(declarations) > 1
    )
    for operation_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "semantic_operation_duplicate",
                f"operation {operation_id.qualified_name!r} is declared more than once",
                "operations",
                operation_id.qualified_name,
                category=ProblemCategory.CONFLICT,
            )
        )
    selected = {
        operation_id: grouped[operation_id][0]
        for operation_id in sorted(grouped, key=lambda item: item.qualified_name)
        if operation_id not in ambiguous
    }
    return selected, ambiguous


def _actions_by_id(
    actions: tuple[InstrumentActionEffect, ...],
    problems: list[Problem],
) -> tuple[dict[ActionId, InstrumentActionEffect], frozenset[ActionId]]:
    grouped: dict[ActionId, list[InstrumentActionEffect]] = {}
    for action in actions:
        grouped.setdefault(action.id, []).append(action)
    ambiguous = frozenset(
        action_id
        for action_id, declarations in grouped.items()
        if len(declarations) > 1
    )
    for action_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "semantic_action_duplicate",
                f"action {action_id.qualified_name!r} is declared more than once",
                "actions",
                action_id.qualified_name,
                category=ProblemCategory.CONFLICT,
            )
        )
    selected = {
        action_id: grouped[action_id][0]
        for action_id in sorted(grouped, key=lambda item: item.qualified_name)
        if action_id not in ambiguous
    }
    return selected, ambiguous


def _verify_actions(
    actions: tuple[InstrumentActionEffect, ...],
    definitions: Mapping[ValueId, ValueDef],
    ambiguous_value_ids: frozenset[ValueId],
    problems: list[Problem],
) -> None:
    for action in actions:
        for field_name, use in action.fields:
            definition = definitions.get(use.value_id)
            if definition is None:
                if use.value_id not in ambiguous_value_ids:
                    problems.append(
                        _problem(
                            "semantic_action_field_dangling",
                            f"action field {field_name!r} references unknown value "
                            f"{use.value_id.qualified_name!r}",
                            "actions",
                            action.id.qualified_name,
                            "fields",
                            field_name,
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                continue
            if definition.owner_region_id is not None:
                problems.append(
                    _problem(
                        "semantic_action_field_region_invalid",
                        f"action field {field_name!r} is owned by a row region",
                        "actions",
                        action.id.qualified_name,
                        "fields",
                        field_name,
                    )
                )


def _regions_by_id(
    regions: tuple[StateEachRegion, ...],
    problems: list[Problem],
) -> tuple[dict[RowRegionId, StateEachRegion], frozenset[RowRegionId]]:
    grouped: dict[RowRegionId, list[StateEachRegion]] = {}
    for region in regions:
        grouped.setdefault(region.id, []).append(region)
    ambiguous = frozenset(
        region_id
        for region_id, declarations in grouped.items()
        if len(declarations) > 1
    )
    for region_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "semantic_row_region_duplicate",
                f"row region {region_id.qualified_name!r} is declared more than once",
                "row_regions",
                region_id.qualified_name,
                category=ProblemCategory.CONFLICT,
            )
        )
    selected = {
        region_id: grouped[region_id][0]
        for region_id in sorted(grouped, key=lambda item: item.qualified_name)
        if region_id not in ambiguous
    }
    return selected, ambiguous


def _verify_row_regions(
    declared: tuple[StateEachRegion, ...],
    definitions: Mapping[ValueId, ValueDef],
    ambiguous_value_ids: frozenset[ValueId],
    problems: list[Problem],
) -> None:
    row_arguments: dict[RowScopeId, RowRegionId] = {}
    for region in declared:
        location = ("row_regions", region.id.qualified_name)
        existing = row_arguments.get(region.row_argument.id)
        if existing is not None and existing != region.id:
            problems.append(
                _problem(
                    "semantic_row_argument_duplicate",
                    "row argument "
                    f"{region.row_argument.id.qualified_name!r} is declared by "
                    "more than one region",
                    *location,
                    category=ProblemCategory.CONFLICT,
                )
            )
        row_arguments[region.row_argument.id] = region.id
        relation = definitions.get(region.relation.value_id)
        if relation is None and region.relation.value_id not in ambiguous_value_ids:
            problems.append(
                _problem(
                    "semantic_row_region_relation_dangling",
                    "row region relation references unknown value "
                    f"{region.relation.value_id.qualified_name!r}",
                    *location,
                    "relation",
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        elif relation is not None:
            if relation.value_type != region.row_argument.value_type:
                problems.append(
                    _problem(
                        "semantic_row_region_relation_type_mismatch",
                        "row argument type does not match its relation value",
                        *location,
                        "relation",
                    )
                )
            if not isinstance(relation.value_type, Table):
                problems.append(
                    _problem(
                        "semantic_row_region_relation_shape_invalid",
                        "row region relation must be table-shaped",
                        *location,
                        "relation",
                    )
                )
            if not _region_is_visible_from(
                relation.owner_region_id,
                None,
            ):
                problems.append(
                    _problem(
                        "semantic_row_region_relation_visibility_invalid",
                        "row region relation is not visible before its row "
                        "argument is introduced",
                        *location,
                        "relation",
                    )
                )

        for path, use in region.body_entries:
            definition = definitions.get(use.value_id)
            if definition is None:
                if use.value_id not in ambiguous_value_ids:
                    problems.append(
                        _problem(
                            "semantic_row_region_body_use_dangling",
                            "row region body references unknown value "
                            f"{use.value_id.qualified_name!r}",
                            *location,
                            *path,
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                continue
            if not _region_is_visible_from(
                definition.owner_region_id,
                region.id,
            ):
                problems.append(
                    _problem(
                        "semantic_row_region_body_visibility_invalid",
                        "row region body references a value owned by a "
                        "different row region",
                        *location,
                        *path,
                    )
                )
        _verify_region_body_shapes(region, definitions, problems)


def _verify_region_body_shapes(
    region: StateEachRegion,
    definitions: Mapping[ValueId, ValueDef],
    problems: list[Problem],
) -> None:
    location = ("row_regions", region.id.qualified_name)
    if region.resource is not None:
        resource = definitions.get(region.resource.value_id)
        if resource is not None:
            resource_type = resource.value_type
            if not isinstance(resource_type, Scalar):
                problems.append(
                    _problem(
                        "semantic_row_region_resource_shape_invalid",
                        "row region resource must be scalar-shaped",
                        *location,
                        "resource",
                    )
                )
            elif (
                resource_type.nullable
                or not isinstance(resource_type.atom, String)
                or resource_type.atom.max_length == 0
            ):
                problems.append(
                    _problem(
                        "semantic_row_region_resource_type_invalid",
                        "row region resource must be a non-null string",
                        *location,
                        "resource",
                    )
                )
    value = definitions.get(region.value.value_id)
    if value is not None and not isinstance(value.value_type, Scalar):
        problems.append(
            _problem(
                "semantic_row_region_value_shape_invalid",
                "row region state value must be scalar-shaped",
                *location,
                "value",
            )
        )
    elif value is not None and not _valid_region_state_value_type(value):
        problems.append(
            _problem(
                "semantic_row_region_value_type_invalid",
                "row region state value must be a non-null finite number or "
                "quantity at plan stage, or a payload at execute stage",
                *location,
                "value",
            )
        )
    for index, use in enumerate(region.route_entities):
        route = definitions.get(use.value_id)
        if route is not None and not isinstance(route.value_type, Scalar | Series):
            problems.append(
                _problem(
                    "semantic_row_region_route_shape_invalid",
                    "row region route entity must be scalar- or series-shaped",
                    *location,
                    "route_entities",
                    str(index),
                )
            )
        elif route is not None and not _valid_region_route_type(route):
            problems.append(
                _problem(
                    "semantic_row_region_route_type_invalid",
                    "row region route entities must be non-null strings or "
                    "entity references and must not be statically empty",
                    *location,
                    "route_entities",
                    str(index),
                )
            )


def _valid_region_state_value_type(definition: ValueDef) -> bool:
    value_type = definition.value_type
    if not isinstance(value_type, Scalar) or value_type.nullable:
        return False
    atom = value_type.atom
    if definition.availability.stage is ValueStage.EXECUTE:
        return isinstance(atom, Payload)
    if definition.availability.stage is not ValueStage.PLAN:
        return False
    if isinstance(atom, Int):
        try:
            return all(
                bound is None or math.isfinite(float(bound))
                for bound in (atom.minimum, atom.maximum)
            )
        except OverflowError:
            return False
    return isinstance(atom, Float | Quantity) and atom.finite


def _valid_region_route_type(definition: ValueDef) -> bool:
    source = definition.source
    if isinstance(source, PlanExpressionSource):
        expression = source.expression
        if (
            isinstance(expression, SeriesExpr)
            and expression.kind == "values"
            and any(
                not (
                    isinstance(item, EntityRef)
                    or (isinstance(item, str) and bool(item))
                )
                for item in expression.items or ()
            )
        ):
            return False
    value_type = definition.value_type
    if isinstance(value_type, Scalar):
        item_type = value_type
    elif isinstance(value_type, Series):
        if value_type.max_length == 0:
            return False
        item_type = value_type.item_type
    else:
        return False
    return (
        not item_type.nullable
        and isinstance(item_type.atom, Entity | String)
        and not (isinstance(item_type.atom, String) and item_type.atom.max_length == 0)
    )


def _verify_operation_regions(
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    regions: Mapping[RowRegionId, StateEachRegion],
    ambiguous_region_ids: frozenset[RowRegionId],
    problems: list[Problem],
) -> None:
    for operation in operations:
        owner = operation.owner_region_id
        if (
            owner is not None
            and owner not in regions
            and owner not in ambiguous_region_ids
        ):
            problems.append(
                _problem(
                    "semantic_operation_owner_region_unknown",
                    f"operation owner region {owner.qualified_name!r} is unknown",
                    "operations",
                    operation.id.qualified_name,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        for input_name, use in operation.inputs:
            definition = definitions.get(use.value_id)
            if definition is None:
                continue
            if not _region_is_visible_from(
                definition.owner_region_id,
                owner,
            ):
                problems.append(
                    _problem(
                        "semantic_operation_input_region_invalid",
                        f"operation input {input_name!r} is owned by an "
                        "invisible row region",
                        "operations",
                        operation.id.qualified_name,
                        "inputs",
                        input_name,
                    )
                )
        for port, value_id in operation.outputs:
            definition = definitions.get(value_id)
            if definition is not None and definition.owner_region_id != owner:
                problems.append(
                    _problem(
                        "semantic_operation_output_region_mismatch",
                        f"operation output {port!r} is not owned by the "
                        "operation's row region",
                        "operations",
                        operation.id.qualified_name,
                        "outputs",
                        port,
                    )
                )
            if (
                definition is not None
                and owner is not None
                and definition.availability.stage is not ValueStage.PLAN
            ):
                problems.append(
                    _problem(
                        "semantic_row_region_operation_stage_invalid",
                        "row-region operations must be fully evaluable at plan stage",
                        "operations",
                        operation.id.qualified_name,
                        "outputs",
                        port,
                    )
                )


def _region_is_visible_from(
    declared: RowRegionId | None,
    consumer: RowRegionId | None,
) -> bool:
    return declared is None or declared == consumer


def _verify_uses(
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    ambiguous_value_ids: frozenset[ValueId],
    problems: list[Problem],
) -> None:
    for operation in operations:
        for input_name, use in operation.inputs:
            if use.value_id in definitions or use.value_id in ambiguous_value_ids:
                continue
            problems.append(
                _problem(
                    "semantic_value_use_dangling",
                    f"operation {operation.id.qualified_name!r} input "
                    f"{input_name!r} references unknown value "
                    f"{use.value_id.qualified_name!r}",
                    "operations",
                    operation.id.qualified_name,
                    "inputs",
                    input_name,
                    category=ProblemCategory.NOT_FOUND,
                )
            )


def _verify_outputs(
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    ambiguous_value_ids: frozenset[ValueId],
    ambiguous_operation_ids: frozenset[OperationId],
    problems: list[Problem],
) -> None:
    declared_outputs: set[ValueId] = set()
    for operation in operations:
        for port, value_id in operation.outputs:
            declared_outputs.add(value_id)
            if value_id in ambiguous_value_ids:
                continue
            definition = definitions.get(value_id)
            if definition is None:
                problems.append(
                    _problem(
                        "semantic_operation_output_missing_definition",
                        f"operation {operation.id.qualified_name!r} output "
                        f"{port!r} has no value definition",
                        "operations",
                        operation.id.qualified_name,
                        "outputs",
                        port,
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
                continue
            expected = OperationOutputSource(operation.id, port)
            if definition.source != expected:
                problems.append(
                    _problem(
                        "semantic_operation_output_source_mismatch",
                        f"value {value_id.qualified_name!r} does not point back "
                        f"to operation {operation.id.qualified_name!r} output {port!r}",
                        "values",
                        value_id.qualified_name,
                    )
                )
    for definition in definitions.values():
        if not isinstance(definition.source, OperationOutputSource):
            continue
        if definition.source.operation_id in ambiguous_operation_ids:
            continue
        if definition.id in declared_outputs:
            continue
        problems.append(
            _problem(
                "semantic_value_producer_missing_output",
                f"value {definition.id.qualified_name!r} names producer "
                f"{definition.source.operation_id.qualified_name!r}, but that "
                "operation does not declare the value",
                "values",
                definition.id.qualified_name,
                category=ProblemCategory.NOT_FOUND,
            )
        )


def _verify_scalar_operations(
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    problems: list[Problem],
) -> None:
    for operation in operations:
        semantics = operation.contract.semantics
        if not isinstance(semantics, ScalarBinarySemantics):
            continue
        if not is_scalar_operator(semantics.operator):
            continue
        inputs = dict(operation.inputs)
        outputs = dict(operation.outputs)
        if set(inputs) != {"left", "right"} or set(outputs) != {"result"}:
            problems.append(
                _problem(
                    "semantic_scalar_binary_shape_invalid",
                    "scalar binary operation requires left/right inputs and one "
                    "result output",
                    "operations",
                    operation.id.qualified_name,
                )
            )
            continue
        left = definitions.get(inputs["left"].value_id)
        right = definitions.get(inputs["right"].value_id)
        result = definitions.get(outputs["result"])
        if left is None or right is None or result is None:
            continue
        if not isinstance(left.value_type, Scalar) or not isinstance(
            right.value_type, Scalar
        ):
            problems.append(
                _problem(
                    "semantic_scalar_binary_input_type_invalid",
                    "scalar binary operation inputs must be scalar-shaped",
                    "operations",
                    operation.id.qualified_name,
                )
            )
            continue
        try:
            expected_type = scalar_operator_result_type(
                left.value_type,
                right.value_type,
                semantics.operator,
                left_is_null_literal=(
                    isinstance(left.source, LiteralValueSource)
                    and left.source.value is None
                ),
                right_is_null_literal=(
                    isinstance(right.source, LiteralValueSource)
                    and right.source.value is None
                ),
            )
        except (TypeError, ValueError) as error:
            problems.append(
                _problem(
                    "semantic_scalar_binary_input_type_invalid",
                    str(error),
                    "operations",
                    operation.id.qualified_name,
                )
            )
            continue
        if result.value_type != expected_type:
            problems.append(
                _problem(
                    "semantic_scalar_binary_result_type_mismatch",
                    f"scalar operation result type {result.value_type!r} does not "
                    f"match inferred type {expected_type!r}",
                    "values",
                    result.id.qualified_name,
                )
            )
        expected_availability = ValueAvailability.combined(
            left.availability,
            right.availability,
        )
        if result.availability != expected_availability:
            problems.append(
                _problem(
                    "semantic_scalar_binary_availability_mismatch",
                    "scalar operation result availability does not match its operands",
                    "values",
                    result.id.qualified_name,
                )
            )


def _verify_value_sources(
    definitions: tuple[ValueDef, ...],
    regions: Mapping[RowRegionId, StateEachRegion],
    ambiguous_region_ids: frozenset[RowRegionId],
    problems: list[Problem],
) -> None:
    for definition in definitions:
        source = definition.source
        value_type = definition.value_type
        owner = definition.owner_region_id
        if (
            owner is not None
            and owner not in regions
            and owner not in ambiguous_region_ids
        ):
            problems.append(
                _problem(
                    "semantic_value_owner_region_unknown",
                    f"value owner region {owner.qualified_name!r} is unknown",
                    "values",
                    definition.id.qualified_name,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        if isinstance(source, PlanExpressionSource):
            expression = source.expression
            valid_type = (
                (isinstance(expression, ScalarExpr) and isinstance(value_type, Scalar))
                or (
                    isinstance(expression, SeriesExpr)
                    and isinstance(value_type, Series)
                )
                or (
                    isinstance(expression, RelationExpr)
                    and isinstance(value_type, Table)
                )
            )
            if not valid_type or not (
                isinstance(value_type, Scalar | Series | Table)
                and is_assignable(source.certified_type, value_type)
            ):
                _append_source_type_mismatch(definition, problems)
            _verify_plan_source_region(definition, source, regions, problems)
            point_dependent = source.used_row_signature[0] is not None
            row_dependent = bool(source.verified_plan.free_row_references.references)
            expected_rate = (
                ValueRate.ROW
                if row_dependent
                else ValueRate.POINT
                if point_dependent
                else ValueRate.RUN
            )
            if (
                definition.availability.stage is ValueStage.PLAN
                and definition.availability.rate is not expected_rate
            ):
                problems.append(
                    _problem(
                        "semantic_plan_expression_rate_mismatch",
                        "plan expression value rate "
                        f"{definition.availability.rate.value!r} does not match "
                        f"inferred rate {expected_rate.value!r}",
                        "values",
                        definition.id.qualified_name,
                    )
                )
            if definition.availability.stage is not ValueStage.PLAN:
                problems.append(
                    _problem(
                        "semantic_plan_expression_availability_invalid",
                        "plan expression values must be available at plan stage; "
                        "their run/point/row rate remains explicit provenance",
                        "values",
                        definition.id.qualified_name,
                    )
                )
            continue
        if isinstance(source, LiteralValueSource):
            if not isinstance(value_type, Scalar):
                _append_source_type_mismatch(definition, problems)
            else:
                try:
                    validate_literal(value_type, source.value, path=())
                except ValueValidationError as error:
                    problems.append(
                        _problem(
                            "semantic_literal_value_type_mismatch",
                            f"literal for value {definition.id.qualified_name!r} "
                            f"does not match {value_type!r}: {error.reason}",
                            "values",
                            definition.id.qualified_name,
                        )
                    )
            _verify_source_availability(
                definition,
                expected=ValueAvailability(ValueStage.PLAN, ValueRate.RUN),
                code="semantic_literal_availability_invalid",
                label="literal",
                problems=problems,
            )
            continue
        if isinstance(source, RouteValueSource):
            if not isinstance(value_type, Route):
                _append_source_type_mismatch(definition, problems)
            _verify_source_availability(
                definition,
                expected=ValueAvailability(ValueStage.PLAN, ValueRate.POINT),
                code="semantic_route_availability_invalid",
                label="route",
                problems=problems,
            )
            continue
        if isinstance(value_type, Route):
            _append_source_type_mismatch(definition, problems)


def _verify_plan_source_region(
    definition: ValueDef,
    source: PlanExpressionSource,
    regions: Mapping[RowRegionId, StateEachRegion],
    problems: list[Problem],
) -> None:
    free = source.verified_plan.free_row_references.references
    if not free:
        return
    owner = definition.owner_region_id
    region = regions.get(owner) if owner is not None else None
    if region is None:
        problems.append(
            _problem(
                "semantic_relation_scope_unowned",
                "row-dependent verified plan has no owning row region",
                "values",
                definition.id.qualified_name,
            )
        )
        return

    expected_row = RowType.from_table(region.row_argument.value_type)
    bindings = source.verified_plan.bindings
    for reference in free:
        if reference.kind is PlanReferenceKind.CURRENT_COLUMN:
            if reference.row_scope_id is None:
                actual = bindings.current_row
            elif reference.row_scope_id == region.row_argument.id:
                actual = bindings.row_arguments.get(reference.row_scope_id)
            else:
                actual = None
        elif reference.kind is PlanReferenceKind.OUTER_COLUMN:
            actual = None
        else:
            continue
        if actual == expected_row:
            continue
        problems.append(
            _problem(
                "semantic_relation_scope_unbound",
                "verified row reference is not certified against its owning "
                f"region {region.id.qualified_name!r}",
                "values",
                definition.id.qualified_name,
            )
        )


def _verify_plan_environment_consistency(
    definitions: tuple[ValueDef, ...],
    problems: list[Problem],
) -> None:
    direct: dict[
        tuple[PlanImportNamespace, str],
        tuple[ValueType, ValueId],
    ] = {}
    lookups: dict[
        tuple[str, tuple[str, ...], str],
        tuple[ParameterLookupSignature, ValueId],
    ] = {}
    point_columns: dict[str, tuple[TableColumn, ValueId]] = {}
    reported: set[tuple[str, str]] = set()

    for definition in definitions:
        source = definition.source
        if not isinstance(source, PlanExpressionSource):
            continue
        for imported in source.imports:
            lookup = imported.lookup
            if lookup is None:
                key = (imported.namespace, imported.id)
                previous = direct.get(key)
                if previous is None:
                    direct[key] = imported.value_type, definition.id
                elif previous[0] != imported.value_type:
                    _append_environment_conflict(
                        "semantic_plan_import_type_conflict",
                        f"{imported.namespace.value} {imported.id!r} is imported "
                        "with incompatible types",
                        definition.id,
                        reported,
                        problems,
                    )
                continue
            lookup_key = (
                lookup.table_id,
                tuple(key for key, _value_type in lookup.key_input_types),
                lookup.column_id,
            )
            previous_lookup = lookups.get(lookup_key)
            if previous_lookup is None:
                lookups[lookup_key] = lookup, definition.id
            elif previous_lookup[0].result_type != lookup.result_type:
                _append_environment_conflict(
                    "semantic_parameter_lookup_type_conflict",
                    f"parameter lookup {lookup.table_id!r}."
                    f"{lookup.column_id!r} has incompatible result types",
                    definition.id,
                    reported,
                    problems,
                )

        point_row = source.used_row_signature[0]
        if point_row is None:
            continue
        for column in point_row.columns:
            previous_column = point_columns.get(column.id)
            if previous_column is None:
                point_columns[column.id] = column, definition.id
            elif previous_column[0] != column:
                _append_environment_conflict(
                    "semantic_point_row_type_conflict",
                    f"point column {column.id!r} is used with incompatible types",
                    definition.id,
                    reported,
                    problems,
                )

    direct_parameters = {
        import_id: entry
        for (namespace, import_id), entry in direct.items()
        if namespace is PlanImportNamespace.PARAMETER
    }
    for lookup, definition_id in lookups.values():
        direct_entry = direct_parameters.get(lookup.table_id)
        if direct_entry is None:
            continue
        direct_type, _direct_definition_id = direct_entry
        if not isinstance(direct_type, Table):
            _append_environment_conflict(
                "semantic_parameter_lookup_type_conflict",
                f"parameter {lookup.table_id!r} is imported both as a lookup "
                "table and a non-table value",
                definition_id,
                reported,
                problems,
            )
            continue
        columns = {column.id: column for column in direct_type.columns}
        key_columns_missing = any(
            column_id not in columns and not direct_type.allow_extra_columns
            for column_id, _input_type in lookup.key_input_types
        )
        result_column = columns.get(lookup.column_id)
        result_conflicts = (
            result_column is not None
            and (
                not result_column.required
                or not is_assignable(
                    result_column.value_type,
                    lookup.result_type,
                )
            )
        ) or (result_column is None and not direct_type.allow_extra_columns)
        if key_columns_missing or result_conflicts:
            _append_environment_conflict(
                "semantic_parameter_lookup_type_conflict",
                f"parameter lookup {lookup.table_id!r}."
                f"{lookup.column_id!r} conflicts with its imported table type",
                definition_id,
                reported,
                problems,
            )


def _append_environment_conflict(
    code: str,
    message: str,
    definition_id: ValueId,
    reported: set[tuple[str, str]],
    problems: list[Problem],
) -> None:
    marker = code, message
    if marker in reported:
        return
    reported.add(marker)
    problems.append(
        _problem(
            code,
            message,
            "values",
            definition_id.qualified_name,
            category=ProblemCategory.CONFLICT,
        )
    )


def _append_source_type_mismatch(
    definition: ValueDef,
    problems: list[Problem],
) -> None:
    problems.append(
        _problem(
            "semantic_value_source_type_mismatch",
            f"value {definition.id.qualified_name!r} source is incompatible "
            f"with type {definition.value_type!r}",
            "values",
            definition.id.qualified_name,
        )
    )


def _verify_source_availability(
    definition: ValueDef,
    *,
    expected: ValueAvailability,
    code: str,
    label: str,
    problems: list[Problem],
) -> None:
    if definition.availability == expected:
        return
    problems.append(
        _problem(
            code,
            f"{label} values must have {expected.stage.value}/"
            f"{expected.rate.value} availability",
            "values",
            definition.id.qualified_name,
        )
    )


def _verify_opaque_operations(
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    problems: list[Problem],
) -> None:
    for operation in operations:
        if not isinstance(operation.contract.semantics, OpaqueSemantics):
            continue
        if any(
            definitions.get(value_id) is None
            or definitions[value_id].source != OperationOutputSource(operation.id, port)
            for port, value_id in operation.outputs
        ):
            # Output reciprocity owns missing/mismatched definitions.  Do not
            # derive shape or availability facts from a non-reciprocal edge.
            continue
        outputs = dict(operation.outputs)
        if set(outputs) != {"result"}:
            problems.append(
                _problem(
                    "semantic_opaque_operation_shape_invalid",
                    "opaque local operations require exactly one result output",
                    "operations",
                    operation.id.qualified_name,
                )
            )
            continue
        result = definitions.get(outputs["result"])
        if result is None:
            continue
        if result.availability != ValueAvailability(
            stage=ValueStage.EXECUTE,
            rate=ValueRate.POINT,
        ):
            problems.append(
                _problem(
                    "semantic_opaque_operation_availability_invalid",
                    "opaque local operation results must be execute/point values",
                    "values",
                    result.id.qualified_name,
                )
            )


def _verify_operation_contracts(
    operations: tuple[SemanticOperation, ...],
    problems: list[Problem],
) -> None:
    for operation in operations:
        for issue in operation_contract_issues(operation.contract):
            problems.append(
                _problem(
                    issue.code,
                    issue.message,
                    "operations",
                    operation.id.qualified_name,
                )
            )


def _topological_operations(
    declared: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
    ambiguous_operation_ids: frozenset[OperationId],
    problems: list[Problem],
) -> tuple[SemanticOperation, ...]:
    dependencies: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    dependents: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    for operation in declared:
        for _name, use in operation.inputs:
            definition = definitions.get(use.value_id)
            if definition is None or not isinstance(
                definition.source, OperationOutputSource
            ):
                continue
            producer = definition.source.operation_id
            if producer in ambiguous_operation_ids:
                continue
            if producer not in operations:
                problems.append(
                    _problem(
                        "semantic_operation_producer_missing",
                        f"value {definition.id.qualified_name!r} references unknown "
                        f"producer {producer.qualified_name!r}",
                        "values",
                        definition.id.qualified_name,
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
                continue
            dependencies[operation.id].add(producer)
            dependents[producer].add(operation.id)
    indegree = {
        operation_id: len(upstream) for operation_id, upstream in dependencies.items()
    }
    ready = [
        (operation_id.qualified_name, operation_id)
        for operation_id, count in indegree.items()
        if count == 0
    ]
    heapq.heapify(ready)
    ordered: list[SemanticOperation] = []
    while ready:
        _name, operation_id = heapq.heappop(ready)
        ordered.append(operations[operation_id])
        for dependent in sorted(
            dependents[operation_id], key=lambda item: item.qualified_name
        ):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (dependent.qualified_name, dependent))
    if len(ordered) != len(operations):
        cyclic = sorted(
            (operation_id for operation_id, count in indegree.items() if count > 0),
            key=lambda item: item.qualified_name,
        )
        first = cyclic[0]
        problems.append(
            _problem(
                "semantic_operation_cycle",
                "semantic operation graph contains a cycle involving: "
                + ", ".join(item.qualified_name for item in cyclic),
                "operations",
                first.qualified_name,
                category=ProblemCategory.CONFLICT,
            )
        )
        return tuple(sorted(declared, key=lambda item: item.id.qualified_name))
    return tuple(ordered)


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


def _problem(
    code: str,
    message: str,
    root: str,
    *path: str,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
) -> Problem:
    return blocking_problem(
        code=code,
        category=category,
        phase=ProblemPhase.AUTHORING,
        message=message,
        location=model_location(root, *path),
    )


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
    "LOCAL_OPAQUE_OPERATION_CONTRACT",
    "ActionId",
    "EffectClass",
    "ImplementationCatalog",
    "ImplementationId",
    "InstrumentActionEffect",
    "LiteralValueSource",
    "LocalPythonImplementation",
    "OpaqueSemantics",
    "OperationContract",
    "OperationContractIssue",
    "OperationId",
    "OperationOutputSource",
    "PlacementConstraint",
    "PlanExpressionSource",
    "Portability",
    "RouteValueSource",
    "RowArgumentDef",
    "RowRegionId",
    "ScalarBinarySemantics",
    "SemanticGraphIR",
    "SemanticOperation",
    "SemanticValueType",
    "SourceAnchor",
    "SourceMap",
    "StateEachRegion",
    "ValueDef",
    "ValueId",
    "ValueUse",
    "VerifiedSemanticGraph",
    "merge_implementation_catalogs",
    "merge_semantic_graphs",
    "merge_source_maps",
    "operation_contract_issues",
    "operation_result_id",
    "scalar_binary_operation_contract",
    "state_each_region_id",
    "verify_implementation_catalog",
    "verify_semantic_graph",
    "verify_source_map",
]
