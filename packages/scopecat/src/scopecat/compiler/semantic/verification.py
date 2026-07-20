"""Backend-neutral typed value and pure-operation graph.

The graph is semantic data only.  Python kernels and authoring provenance are
carried by explicit sidecars so implementation choice and diagnostics cannot
change graph equality.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat.compiler.relations.analysis import (
    PlanReferenceKind,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    ValuesSeriesExpr,
)
from scopecat.compiler.relations.operators import (
    is_scalar_operator,
    scalar_operator_result_type,
)
from scopecat.compiler.relations.verification import (
    ParameterLookupSignature,
    PlanImportNamespace,
    RowType,
)
from scopecat.compiler.semantic.dependencies import (
    residual_operation_ids,
    residual_value_ids,
)
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    AcquireId,
    ActionId,
    ImplementationCatalog,
    ImplementationId,
    InstrumentActionEffect,
    LiteralValueSource,
    MeasurementTransformId,
    OperationId,
    OperationOutputSource,
    PlanExpressionSource,
    RowRegionId,
    SemanticDomainExecution,
    SemanticGraphIR,
    SemanticMeasurementTransform,
    SemanticOperation,
    SourceAnchor,
    SourceMap,
    StateEachRegion,
    ValueDef,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import (
    OpaqueSemantics,
    ScalarBinarySemantics,
    operation_contract_issues,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import (
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.kernel.value_validation import ValueValidationError, validate_literal
from scopecat.records.entity import EntityRef


@dataclass(frozen=True, slots=True)
class VerifiedSemanticGraph:
    graph: SemanticGraphIR
    value_defs: Mapping[ValueId, ValueDef] = field(
        init=False,
        compare=False,
        hash=False,
    )
    operations: Mapping[OperationId, SemanticOperation] = field(
        init=False,
        compare=False,
        hash=False,
    )
    residual_value_ids: frozenset[ValueId] = field(
        init=False,
        compare=False,
        hash=False,
    )
    residual_operation_ids: frozenset[OperationId] = field(
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
    measurement_transforms: Mapping[
        MeasurementTransformId,
        SemanticMeasurementTransform,
    ] = field(
        init=False,
        compare=False,
        hash=False,
    )
    domain_executions: tuple[SemanticDomainExecution, ...] = field(
        init=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        definitions = {
            definition.id: definition for definition in self.graph.value_defs
        }
        operations = {operation.id: operation for operation in self.graph.operations}
        regions = {region.id: region for region in self.graph.row_regions}
        actions = {action.id: action for action in self.graph.actions}
        measurement_transforms = {
            transform.id: transform for transform in self.graph.measurement_transforms
        }
        object.__setattr__(self, "value_defs", MappingProxyType(definitions))
        object.__setattr__(self, "operations", MappingProxyType(operations))
        object.__setattr__(
            self,
            "residual_value_ids",
            residual_value_ids(definitions, self.graph.operations),
        )
        object.__setattr__(
            self,
            "residual_operation_ids",
            residual_operation_ids(definitions, self.graph.operations),
        )
        object.__setattr__(self, "row_regions", MappingProxyType(regions))
        object.__setattr__(self, "actions", MappingProxyType(actions))
        object.__setattr__(
            self,
            "measurement_transforms",
            MappingProxyType(measurement_transforms),
        )
        object.__setattr__(self, "domain_executions", self.graph.domain_executions)


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
    _measurement_transforms, ambiguous_measurement_transform_ids = (
        _measurement_transforms_by_id(graph.measurement_transforms, problems)
    )
    regions, ambiguous_region_ids = _regions_by_id(graph.row_regions, problems)
    unambiguous_operations = tuple(
        operation
        for operation in graph.operations
        if operation.id not in ambiguous_operation_ids
    )
    operations_by_id = {operation.id: operation for operation in unambiguous_operations}
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
    execution_ids = tuple(execution.id for execution in graph.domain_executions)
    if len(execution_ids) != len(set(execution_ids)):
        problems.append(
            _problem(
                "semantic_domain_execution_id_duplicate",
                "domain execution ids must be unique",
                "domain_executions",
                category=ProblemCategory.CONFLICT,
            )
        )
    acquisition_ids = tuple(acquire.id for acquire in graph.acquisitions)
    if len(acquisition_ids) != len(set(acquisition_ids)):
        problems.append(
            _problem(
                "semantic_acquire_id_duplicate",
                "acquisition ids must be unique",
                "acquisitions",
                category=ProblemCategory.CONFLICT,
            )
        )
    for execution_index, execution in enumerate(graph.domain_executions):
        _verify_domain_execution(
            execution,
            definitions,
            operations_by_id,
            ambiguous_value_ids,
            problems,
            execution_index=execution_index,
        )
    unambiguous_measurement_transforms = tuple(
        transform
        for transform in graph.measurement_transforms
        if transform.id not in ambiguous_measurement_transform_ids
    )
    _verify_product_owners(
        graph.acquisitions,
        graph.domain_executions,
        unambiguous_measurement_transforms,
        problems,
    )
    ordered_measurement_transforms = _topological_measurement_transforms(
        unambiguous_measurement_transforms,
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
        operations_by_id,
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
        raise CheckFailed(problems)
    ordered_defs = tuple(
        sorted(graph.value_defs, key=lambda item: item.id.qualified_name)
    )
    normalized = SemanticGraphIR(
        value_defs=ordered_defs,
        operations=ordered_operations,
        measurement_transforms=ordered_measurement_transforms,
        domain_executions=graph.domain_executions,
        actions=tuple(
            action for action in graph.actions if action.id not in ambiguous_action_ids
        ),
        acquisitions=graph.acquisitions,
        # State regions retain authored order: desired-state sequencing is
        # semantic, unlike declaration maps normalized only by identity.
        row_regions=graph.row_regions,
    )
    return VerifiedSemanticGraph(normalized)


def _measurement_transforms_by_id(
    transforms: tuple[SemanticMeasurementTransform, ...],
    problems: list[Problem],
) -> tuple[
    dict[MeasurementTransformId, SemanticMeasurementTransform],
    frozenset[MeasurementTransformId],
]:
    grouped: dict[MeasurementTransformId, list[SemanticMeasurementTransform]] = {}
    for transform in transforms:
        grouped.setdefault(transform.id, []).append(transform)
    ambiguous = frozenset(
        transform_id
        for transform_id, declarations in grouped.items()
        if len(declarations) > 1
    )
    for transform_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "semantic_measurement_transform_duplicate",
                "measurement transform "
                f"{transform_id.qualified_name!r} is declared more than once",
                "measurement_transforms",
                transform_id.qualified_name,
                category=ProblemCategory.CONFLICT,
            )
        )
    return (
        {
            transform_id: declarations[0]
            for transform_id, declarations in grouped.items()
            if transform_id not in ambiguous
        },
        ambiguous,
    )


def _verify_product_owners(
    acquisitions: tuple[AcquireEffect, ...],
    executions: tuple[SemanticDomainExecution, ...],
    transforms: tuple[SemanticMeasurementTransform, ...],
    problems: list[Problem],
) -> None:
    owners: dict[object, tuple[str, str]] = {}
    for acquire in acquisitions:
        for product in acquire.products:
            existing = owners.get(product.product_id)
            if existing is not None:
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "semantic_product_producer_duplicate",
                        f"logical product {product.product_id.qualified_name!r} is "
                        f"produced by both {owner}/{owner_port!r} and acquisition "
                        f"{acquire.id.qualified_name!r}/{product.provider_key!r}",
                        "acquisitions",
                        acquire.id.qualified_name,
                        "products",
                        product.provider_key,
                        category=ProblemCategory.CONFLICT,
                    )
                )
                continue
            owners[product.product_id] = (
                f"acquisition {acquire.id.qualified_name!r}",
                product.provider_key,
            )
    for execution in executions:
        for result_id, product_id in execution.results:
            existing = owners.get(product_id)
            if existing is not None:
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "semantic_product_producer_duplicate",
                        f"logical product {product_id.qualified_name!r} is produced "
                        f"by both {owner}/{owner_port!r} and domain execution "
                        f"{execution.id!r}/{result_id!r}",
                        "domain_executions",
                        execution.id,
                        "results",
                        result_id,
                        category=ProblemCategory.CONFLICT,
                    )
                )
                continue
            owners[product_id] = (f"domain execution {execution.id!r}", result_id)
    for transform in transforms:
        for role, product_id in transform.outputs:
            existing = owners.get(product_id)
            if existing is not None:
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "semantic_product_producer_duplicate",
                        f"logical product {product_id.qualified_name!r} is "
                        f"produced by both {owner}/{owner_port!r} and measurement "
                        f"transform {transform.id.qualified_name!r}/{role!r}",
                        "measurement_transforms",
                        transform.id.qualified_name,
                        "outputs",
                        role,
                        category=ProblemCategory.CONFLICT,
                    )
                )
                continue
            owners[product_id] = (
                f"measurement transform {transform.id.qualified_name!r}",
                role,
            )


def _topological_measurement_transforms(
    transforms: tuple[SemanticMeasurementTransform, ...],
    problems: list[Problem],
) -> tuple[SemanticMeasurementTransform, ...]:
    by_id = {transform.id: transform for transform in transforms}
    owner_by_output = {
        product_id: transform.id
        for transform in transforms
        for _role, product_id in transform.outputs
    }
    dependencies: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform.id: set() for transform in transforms
    }
    dependants: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform.id: set() for transform in transforms
    }
    for transform in transforms:
        for _role, product_id in transform.inputs:
            owner = owner_by_output.get(product_id)
            if owner is None:
                continue
            dependencies[transform.id].add(owner)
            dependants[owner].add(transform.id)
    ready = [
        (transform_id.qualified_name, transform_id)
        for transform_id, owners in dependencies.items()
        if not owners
    ]
    heapq.heapify(ready)
    ordered: list[SemanticMeasurementTransform] = []
    while ready:
        _name, transform_id = heapq.heappop(ready)
        ordered.append(by_id[transform_id])
        for dependant in sorted(
            dependants[transform_id],
            key=lambda item: item.qualified_name,
        ):
            dependencies[dependant].discard(transform_id)
            if not dependencies[dependant]:
                heapq.heappush(
                    ready,
                    (dependant.qualified_name, dependant),
                )
    if len(ordered) == len(transforms):
        return tuple(ordered)
    cycle_ids = tuple(
        sorted(
            (transform_id for transform_id, owners in dependencies.items() if owners),
            key=lambda item: item.qualified_name,
        )
    )
    first = cycle_ids[0]
    problems.append(
        _problem(
            "semantic_measurement_transform_cycle",
            "measurement transform graph contains a dependency cycle: "
            + ", ".join(item.qualified_name for item in cycle_ids),
            "measurement_transforms",
            first.qualified_name,
            category=ProblemCategory.CONFLICT,
        )
    )
    return transforms


def _verify_domain_execution(
    execution: SemanticDomainExecution,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
    ambiguous_value_ids: frozenset[ValueId],
    problems: list[Problem],
    *,
    execution_index: int,
) -> None:
    program = execution.program
    product_owners: dict[object, str] = {}
    location = ("domain_executions", str(execution_index))
    expected_inputs = tuple(port.id for port in program.input_ports)
    if tuple(name for name, _use in execution.inputs) != expected_inputs:
        problems.append(
            _problem(
                "semantic_domain_execution_input_contract_mismatch",
                "domain execution inputs do not match the declared program ports",
                *location,
                "inputs",
            )
        )
    expected_results = tuple(port.id for port in program.result_ports)
    if tuple(name for name, _product in execution.results) != expected_results:
        problems.append(
            _problem(
                "semantic_domain_execution_result_contract_mismatch",
                "domain execution results do not match the declared program ports",
                *location,
                "results",
            )
        )
    expected_resources = tuple(port.id for port in program.resource_ports)
    if tuple(name for name, _resource in execution.resources) != expected_resources:
        problems.append(
            _problem(
                "semantic_domain_execution_resource_contract_mismatch",
                "domain execution resources do not match the declared program ports",
                *location,
                "resources",
            )
        )
    input_ports = {port.id: port for port in program.input_ports}
    for name, use in execution.inputs:
        definition = definitions.get(use.value_id)
        if definition is None:
            if use.value_id not in ambiguous_value_ids:
                problems.append(
                    _problem(
                        "semantic_domain_execution_input_dangling",
                        f"domain execution input {name!r} references unknown value "
                        f"{use.value_id.qualified_name!r}",
                        *location,
                        "inputs",
                        name,
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
            continue
        port = input_ports.get(name)
        if port is not None and not is_assignable(
            definition.value_type,
            port.value_type,
        ):
            problems.append(
                _problem(
                    "semantic_domain_execution_input_type_mismatch",
                    f"domain execution input {name!r} is not assignable to its "
                    "declared port type",
                    *location,
                    "inputs",
                    name,
                )
            )
        if _value_is_residual(definition, definitions, operations):
            problems.append(
                _problem(
                    "semantic_domain_execution_input_stage_unavailable",
                    f"domain execution input {name!r} must be available at plan stage",
                    *location,
                    "inputs",
                    name,
                )
            )
        if definition.owner_region_id is not None:
            problems.append(
                _problem(
                    "semantic_domain_execution_input_region_invalid",
                    f"domain execution input {name!r} is owned by a row region",
                    *location,
                    "inputs",
                    name,
                )
            )
    for result_name, product_id in execution.results:
        existing = product_owners.get(product_id)
        if existing is not None:
            problems.append(
                _problem(
                    "semantic_domain_product_producer_duplicate",
                    f"logical product {product_id.qualified_name!r} is "
                    "produced by both "
                    f"domain execution results {existing!r} and {result_name!r}",
                    *location,
                    "results",
                    result_name,
                    category=ProblemCategory.CONFLICT,
                )
            )
        else:
            product_owners[product_id] = result_name


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
    domain_sources = _verify_optional_string_source_entries(
        "domain",
        source_map.domain_sources,
        {execution.id for execution in graph.domain_executions},
        problems,
    )
    acquire_sources = _verify_optional_source_entries(
        "acquire",
        source_map.acquire_sources,
        {acquire.id for acquire in graph.acquisitions},
        problems,
    )
    if problems:
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
        domain_sources=tuple(sorted(domain_sources.items())),
        acquire_sources=tuple(
            sorted(acquire_sources.items(), key=lambda item: item[0].qualified_name)
        ),
    )


def _verify_optional_string_source_entries(
    kind: str,
    entries: tuple[tuple[str, SourceAnchor], ...],
    expected: set[str],
    problems: list[Problem],
) -> dict[str, SourceAnchor]:
    selected: dict[str, SourceAnchor] = {}
    for identity, anchor in entries:
        if identity in selected:
            problems.append(
                _problem(
                    f"semantic_source_map_{kind}_duplicate",
                    f"{kind} {identity!r} has duplicate source anchors",
                    "source_map",
                    kind + "s",
                    identity,
                    category=ProblemCategory.CONFLICT,
                )
            )
        elif identity not in expected:
            problems.append(
                _problem(
                    f"semantic_source_map_{kind}_orphan",
                    f"source anchor references unknown {kind} {identity!r}",
                    "source_map",
                    kind + "s",
                    identity,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        selected[identity] = anchor
    return selected


def _verify_optional_source_entries[
    Identity: (AcquireId),
](
    kind: str,
    entries: tuple[tuple[Identity, SourceAnchor], ...],
    expected: set[Identity],
    problems: list[Problem],
) -> dict[Identity, SourceAnchor]:
    if not entries:
        return {}
    return _verify_source_entries(kind, entries, expected, problems)


def _verify_source_entries[
    Identity: (AcquireId, ActionId, OperationId, RowRegionId, ValueId),
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
    operations: Mapping[OperationId, SemanticOperation],
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
        _verify_region_body_shapes(region, definitions, operations, problems)


def _verify_region_body_shapes(
    region: StateEachRegion,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
    problems: list[Problem],
) -> None:
    location = ("row_regions", region.id.qualified_name)
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
    elif value is not None and not _valid_region_state_value_type(
        value, definitions, operations
    ):
        problems.append(
            _problem(
                "semantic_row_region_value_type_invalid",
                "row region state value must be a non-null finite number or "
                "quantity at plan stage, or a payload at execute stage",
                *location,
                "value",
            )
        )
    for index, use in enumerate(region.target_entities):
        target = definitions.get(use.value_id)
        if target is not None and not isinstance(target.value_type, Scalar | Series):
            problems.append(
                _problem(
                    "semantic_row_region_target_shape_invalid",
                    "row region target entity must be scalar- or series-shaped",
                    *location,
                    "target_entities",
                    str(index),
                )
            )
        elif target is not None and not _valid_region_target_type(target):
            problems.append(
                _problem(
                    "semantic_row_region_target_type_invalid",
                    "row region target entities must be non-null strings or "
                    "entity references and must not be statically empty",
                    *location,
                    "target_entities",
                    str(index),
                )
            )


def _valid_region_state_value_type(
    definition: ValueDef,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
) -> bool:
    value_type = definition.value_type
    if not isinstance(value_type, Scalar) or value_type.nullable:
        return False
    atom = value_type.atom
    if _value_is_residual(definition, definitions, operations):
        return isinstance(atom, Payload)
    if isinstance(atom, Int):
        try:
            return all(
                bound is None or math.isfinite(float(bound))
                for bound in (atom.minimum, atom.maximum)
            )
        except OverflowError:
            return False
    return isinstance(atom, Float | Quantity) and atom.finite


def _valid_region_target_type(definition: ValueDef) -> bool:
    source = definition.source
    if isinstance(source, PlanExpressionSource):
        expression = source.expression
        if isinstance(expression, ValuesSeriesExpr) and any(
            not (isinstance(item, EntityRef) or (isinstance(item, str) and bool(item)))
            for item in expression.items
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
                and isinstance(operation.contract.semantics, OpaqueSemantics)
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
            if not valid_type or not is_assignable(source.certified_type, value_type):
                _append_source_type_mismatch(definition, problems)
            _verify_plan_source_region(definition, source, regions, problems)
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
            continue


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


def _value_is_residual(
    definition: ValueDef,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
) -> bool:
    return definition.id in residual_value_ids(
        definitions,
        tuple(operations.values()),
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
            # Output reciprocity owns missing/mismatched definitions.
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
