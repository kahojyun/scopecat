"""Validate and lower a composed authoring assembly into compiler values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from scopecat._compiler.parameter_overlays import PointParameterOverlay
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    ComputeEdge,
    RouteInput,
    TypedComputeNode,
    TypedComputeOutput,
    ValueInput,
    bind_each,
    set_state_field,
)
from scopecat._compiler.state import StateSpec
from scopecat._compute_result import ComputeResultRef
from scopecat._point_domain_algebra import (
    POINT_UNIT,
    PointDependentProduct,
    PointDomainAnalysis,
    PointDomainExpr,
    PointDomainPath,
    PointProduct,
    PointRelationRows,
    PointUnit,
    PointZip,
    analyze_point_domain,
)
from scopecat._relation_use import relation_use
from scopecat._relation_verification import RelationTypeBindings, RowType
from scopecat._relations import (
    CellValue,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    point_col,
)
from scopecat._resource_identity import LogicalResourcePortId
from scopecat._semantic_graph import (
    ImplementationCatalog,
    LiteralValueSource,
    OperationId,
    OperationOutputSource,
    PlanExpressionSource,
    RouteValueSource,
    ScalarBinarySemantics,
    SemanticOperation,
    StateEachRegion,
    ValueDef,
    ValueId,
    ValueUse,
    VerifiedSemanticGraph,
)
from scopecat._value_availability import ValueStage
from scopecat._value_expressions import (
    ScalarOrSeriesValueExpr,
    ScalarValueExpr,
    TableValueExpr,
    ValueExpr,
    verify_scalar_value_expr,
    verify_value_expr,
)
from scopecat._value_type_compatibility import require_assignable
from scopecat.authoring._binding_intents import ResourcePort
from scopecat.authoring._binding_lowering import (
    BindingSpec,
    require_port_capability,
)
from scopecat.authoring._context import ExperimentAuthoringContext
from scopecat.authoring._elaboration import SemanticExperimentIR
from scopecat.authoring._intents import ModuleInputPort, ParameterScanOverlayIntent
from scopecat.authoring._point_domain_intents import (
    PointDomainIntent,
    point_domain_intent_output_types,
)
from scopecat.authoring._value_binding import (
    bind_relation_input_refs,
    bind_scalar_input_refs,
    bind_value_input_refs,
    input_cell,
    literal_data_expr,
    value_input_refs,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_lower_table_value_ref,
    internal_lower_value_ref,
    internal_value_ref_bound_point_input_ids,
    internal_value_ref_free_point_input_ids,
)
from scopecat.authoring.value_types import Table as TableType
from scopecat.authoring.value_types import (
    ValueType,
    ValueValidationError,
    coerce_literal,
)
from scopecat.models.entity import EntityRef
from scopecat.value_types import Route


def lower_parameter_overlay_intent(
    ctx: ExperimentAuthoringContext,
    intent: ParameterScanOverlayIntent,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> PointParameterOverlay:
    definition = ctx.config.parameter_catalog.get(intent.table_id)
    if definition is None or not isinstance(definition.value_type, TableType):
        raise AssertionError("validated parameter overlay table is missing")
    columns = {column.id: column for column in definition.value_type.columns}
    try:
        target_column = columns[intent.column_id]
        key_types = {
            column_id: columns[column_id].value_type for column_id, _ in intent.key
        }
    except KeyError as error:
        raise AssertionError("validated parameter overlay column is missing") from error
    return PointParameterOverlay(
        table_id=intent.table_id,
        key_uses={
            name: relation_use(
                verify_scalar_value_expr(
                    bind_scalar_input_refs(
                        internal_lower_scalar_value_ref(value)
                        if isinstance(value, ValueRef)
                        else as_scalar_expr(value),
                        inputs,
                    ),
                    bindings=type_bindings,
                    expected_type=key_types[name],
                )
            )
            for name, value in intent.key
        },
        column_id=intent.column_id,
        value_use=relation_use(
            verify_scalar_value_expr(
                point_col(intent.point_id),
                bindings=type_bindings,
                expected_type=target_column.value_type,
            )
        ),
    )


def validate_entity_inputs(
    ctx: ExperimentAuthoringContext,
    entity_inputs: tuple[str, ...],
    inputs: Mapping[str, object],
) -> None:
    for input_id in entity_inputs:
        if input_id not in inputs:
            continue
        value = inputs.get(input_id)
        if isinstance(value, str) and value:
            ctx.require_entity(value)
            continue
        if isinstance(value, EntityRef):
            ctx.require_entity(value)
            continue
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            selected = cast("Sequence[EntityRef | str]", value)
            ctx.require_entities(selected)
            continue
        ctx.raise_problem(
            "module_entity_input_invalid",
            f"module entity input {input_id} must be an entity or entity series",
            "inputs",
            path=(input_id,),
        )


def lower_semantic_compute_graph(
    graph: VerifiedSemanticGraph,
    catalog: ImplementationCatalog,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> tuple[tuple[TypedComputeNode, ...], ImplementationCatalog]:
    """Lower execute-stage semantic operations to the current local artifact."""

    operations = {operation.id: operation for operation in graph.graph.operations}
    nodes = tuple(
        _lower_semantic_operation(
            operation,
            definitions=graph.value_defs,
            operations=operations,
            inputs=inputs,
            type_bindings=type_bindings,
        )
        for operation in graph.graph.operations
        if _operation_is_execute_stage(operation, graph.value_defs)
    )
    node_ids = {node.id for node in nodes}
    selected_catalog = ImplementationCatalog(
        local_python=tuple(
            implementation
            for implementation in catalog.local_python
            if implementation.operation_id in node_ids
        )
    )
    return nodes, selected_catalog


def _operation_is_execute_stage(
    operation: SemanticOperation,
    definitions: Mapping[ValueId, ValueDef],
) -> bool:
    return any(
        definitions[value_id].availability.stage is ValueStage.EXECUTE
        for _port, value_id in operation.outputs
        if value_id in definitions
    )


def _lower_semantic_operation(
    operation: SemanticOperation,
    *,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> TypedComputeNode:
    outputs = dict(operation.outputs)
    output = definitions[outputs["result"]]
    if isinstance(output.value_type, Route):
        raise AssertionError("semantic operation outputs cannot be route values")
    return TypedComputeNode(
        id=operation.id,
        contract=operation.contract,
        inputs={
            name: _lower_semantic_input(
                use.value_id,
                definitions=definitions,
                operations=operations,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            for name, use in operation.inputs
        },
        result=TypedComputeOutput(
            id=output.id,
            value_type=output.value_type,
            availability=output.availability,
        ),
    )


def _lower_semantic_input(
    value_id: ValueId,
    *,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> ValueInput | ComputeEdge | RouteInput:
    definition = definitions[value_id]
    source = definition.source
    if isinstance(source, RouteValueSource):
        if not isinstance(definition.value_type, Route):
            raise AssertionError("route sources must define route-typed values")
        return RouteInput(
            port_id=source.port_id,
            value_type=definition.value_type,
        )
    if isinstance(source, OperationOutputSource) and (
        definition.availability.stage is ValueStage.EXECUTE
    ):
        if isinstance(definition.value_type, Route):
            raise AssertionError("compute edges cannot carry route values")
        return ComputeEdge(
            value_id=definition.id,
            expected_type=definition.value_type,
        )
    if isinstance(definition.value_type, Route):
        raise AssertionError("plan values cannot carry route types")
    expression = _semantic_plan_expression(
        value_id,
        definitions=definitions,
        operations=operations,
        active=frozenset(),
    )
    origin_input_ids = tuple(value_input_refs(expression))
    return ValueInput(
        value=verify_value_expr(
            bind_value_input_refs(expression, inputs),
            bindings=type_bindings,
            expected_type=definition.value_type,
        ),
        origin_input_ids=origin_input_ids,
    )


def _semantic_plan_expression(
    value_id: ValueId,
    *,
    definitions: Mapping[ValueId, ValueDef],
    operations: Mapping[OperationId, SemanticOperation],
    active: frozenset[ValueId],
) -> ScalarExpr | SeriesExpr | RelationExpr:
    if value_id in active:
        raise AssertionError("verified semantic graph contains a plan-value cycle")
    definition = definitions[value_id]
    source = definition.source
    if isinstance(source, PlanExpressionSource):
        return source.expression
    if isinstance(source, LiteralValueSource):
        return literal_data_expr(source.value)
    if not isinstance(source, OperationOutputSource):
        raise AssertionError("route and execute values cannot become plan expressions")
    operation = operations[source.operation_id]
    if not isinstance(operation.contract.semantics, ScalarBinarySemantics):
        raise AssertionError("only core scalar operations can be plan-inlined")
    uses = dict(operation.inputs)
    nested_active = active | {value_id}
    left = _semantic_plan_expression(
        uses["left"].value_id,
        definitions=definitions,
        operations=operations,
        active=nested_active,
    )
    right = _semantic_plan_expression(
        uses["right"].value_id,
        definitions=definitions,
        operations=operations,
        active=nested_active,
    )
    if not isinstance(left, ScalarExpr) or not isinstance(right, ScalarExpr):
        raise AssertionError("scalar semantic operands must lower to scalar plans")
    return ScalarExpr(
        kind="binary",
        op=operation.contract.semantics.operator,
        left=left,
        right=right,
    )


def lower_state_region(
    ctx: ExperimentAuthoringContext,
    region: StateEachRegion,
    graph: VerifiedSemanticGraph,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePort],
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> StateSpec:
    if region.resource_port is not None:
        port = resource_ports.get(region.resource_port)
        if port is None:
            ctx.raise_problem(
                "module_unknown_resource_port",
                "state binding references unknown resource port "
                f"{region.resource_port}",
                "state",
            )
        require_port_capability(ctx, port, region.capability_id)
    operations = {operation.id: operation for operation in graph.graph.operations}
    row_type = RowType.from_table(region.row_argument.value_type)
    body_bindings = replace(
        type_bindings,
        current_row=row_type,
        row_arguments={**type_bindings.row_arguments, region.row_argument.id: row_type},
    )
    resource = (
        None
        if region.resource_port is not None
        else _lower_state_region_scalar(
            _required_region_use(region.resource, role="resource"),
            graph=graph,
            operations=operations,
            inputs=inputs,
            role="resource",
            type_bindings=body_bindings,
        )
    )
    relation = _lower_state_region_plan_value(
        region.relation,
        graph=graph,
        operations=operations,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    if not isinstance(relation, TableValueExpr):
        raise AssertionError("verified state region relation must be table-shaped")
    state_value = _lower_state_region_value(
        region.value,
        graph=graph,
        operations=operations,
        inputs=inputs,
        type_bindings=body_bindings,
    )
    return bind_each(
        relation,
        set_state_field(
            resource,
            resource_port_id=region.resource_port,
            capability_id=region.capability_id,
            field_path=region.field_path,
            value=state_value,
            route_entities=tuple(
                _lower_state_region_route(
                    route,
                    graph=graph,
                    operations=operations,
                    inputs=inputs,
                    type_bindings=body_bindings,
                )
                for route in region.route_entities
            ),
        ),
        row_scope_id=region.row_argument.id,
    )


def _lower_state_region_value(
    use: ValueUse,
    *,
    graph: VerifiedSemanticGraph,
    operations: Mapping[OperationId, SemanticOperation],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> ScalarValueExpr | ComputeResultRef:
    definition = graph.value_defs[use.value_id]
    if isinstance(definition.source, OperationOutputSource) and (
        definition.availability.stage is ValueStage.EXECUTE
    ):
        return ComputeResultRef(value_id=definition.id)
    value = _lower_state_region_plan_value(
        use,
        graph=graph,
        operations=operations,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    if not isinstance(value, ScalarValueExpr):
        raise AssertionError("verified state region value must be scalar-shaped")
    return value


def _lower_state_region_scalar(
    use: ValueUse,
    *,
    graph: VerifiedSemanticGraph,
    operations: Mapping[OperationId, SemanticOperation],
    inputs: Mapping[str, object],
    role: str,
    type_bindings: RelationTypeBindings,
) -> ScalarValueExpr:
    value = _lower_state_region_plan_value(
        use,
        graph=graph,
        operations=operations,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    if not isinstance(value, ScalarValueExpr):
        raise AssertionError(f"verified state region {role} must be scalar-shaped")
    return value


def _lower_state_region_route(
    use: ValueUse,
    *,
    graph: VerifiedSemanticGraph,
    operations: Mapping[OperationId, SemanticOperation],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> ScalarOrSeriesValueExpr:
    value = _lower_state_region_plan_value(
        use,
        graph=graph,
        operations=operations,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    if isinstance(value, TableValueExpr):
        raise AssertionError("verified state route must be scalar- or series-shaped")
    return value


def _lower_state_region_plan_value(
    use: ValueUse,
    *,
    graph: VerifiedSemanticGraph,
    operations: Mapping[OperationId, SemanticOperation],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> ValueExpr:
    definition = graph.value_defs[use.value_id]
    if isinstance(definition.value_type, Route):
        raise AssertionError("state plan values cannot be route-shaped")
    expression = _semantic_plan_expression(
        use.value_id,
        definitions=graph.value_defs,
        operations=operations,
        active=frozenset(),
    )
    return verify_value_expr(
        bind_value_input_refs(expression, inputs),
        bindings=type_bindings,
        expected_type=definition.value_type,
    )


def _required_region_use(use: ValueUse | None, *, role: str) -> ValueUse:
    if use is None:
        raise AssertionError(f"verified state region has no {role} use")
    return use


def validate_assembly_conflicts(
    ctx: ExperimentAuthoringContext,
    assembly: SemanticExperimentIR,
) -> None:
    _reject_duplicates(
        ctx,
        ids=[
            *(record.id for record in assembly.records),
            *(
                selection.record_id or selection.product_id.qualified_name
                for selection in assembly.record_selections
            ),
        ],
        code="module_record_duplicate",
        message="experiment assembly defines duplicate records",
        path="records",
    )
    _reject_duplicates(
        ctx,
        ids=[product.qualified_id for product in assembly.product_ports],
        code="module_product_duplicate",
        message="experiment assembly defines duplicate products",
        path="products",
    )
    _reject_duplicates(
        ctx,
        ids=[
            operation.id.qualified_name
            for operation in assembly.semantic_graph.operations
        ],
        code="module_compute_node_duplicate",
        message="experiment assembly defines duplicate program nodes",
        path="compute_nodes",
    )


def coerce_assembly_inputs(
    ctx: ExperimentAuthoringContext,
    ports: Sequence[ModuleInputPort],
    inputs: Mapping[str, object],
) -> dict[str, object]:
    declared: dict[str, ValueType] = {}
    for port in ports:
        existing = declared.get(port.id)
        if existing is not None and existing != port.value_type:
            ctx.raise_problem(
                "module_input_type_conflict",
                f"module input {port.id} has incompatible value types",
                "inputs",
                path=(port.id,),
            )
        declared[port.id] = port.value_type
    result = dict(inputs)
    for input_id, value_type in declared.items():
        if input_id not in result:
            continue
        value = result[input_id]
        if isinstance(value, ValueRef):
            try:
                require_assignable(
                    value.value_type,
                    value_type,
                    path=("inputs", input_id),
                )
            except ValueValidationError as error:
                ctx.raise_problem(
                    "module_input_type_mismatch",
                    str(error),
                    "inputs",
                    path=(input_id,),
                )
            continue
        try:
            result[input_id] = coerce_literal(
                value_type,
                value,
                path=("inputs", input_id),
            )
        except ValueValidationError as error:
            ctx.raise_problem(
                "module_input_type_mismatch",
                str(error),
                "inputs",
                path=(input_id,),
            )
    return result


def validate_consumed_inputs(
    ctx: ExperimentAuthoringContext,
    assembly: SemanticExperimentIR,
    inputs: Mapping[str, object],
) -> None:
    """Reject only free module inputs that the assembled program actually uses."""

    point_input_ids = set(point_domain_intent_output_types(assembly.point_domain))
    point_domain_dependencies = _point_domain_input_dependencies(
        assembly.point_domain,
        inputs=inputs,
    )
    consumed_dependencies: set[str] = set()
    values: list[object] = []
    values.extend(
        source
        for port in assembly.resource_ports
        for source in port.selector.entity_inputs
    )
    values.extend(binding.value for binding in assembly.bindings)
    values.extend(
        value for overlay in assembly.parameter_overlays for _name, value in overlay.key
    )
    consumed_dependencies.update(
        input_id
        for definition in assembly.semantic_graph.value_defs
        if isinstance(definition.source, PlanExpressionSource)
        for input_id in definition.source.source_inputs
    )
    values.extend(axis.size for record in assembly.records for axis in record.axes)
    values.extend(
        axis.size for product in assembly.product_ports for axis in product.axes
    )
    for value in values:
        consumed_dependencies.update(_nested_input_dependencies(value, inputs=inputs))

    provided = set(inputs)
    missing = sorted(
        (point_domain_dependencies - provided)
        | (consumed_dependencies - provided - point_input_ids)
    )
    if missing:
        ctx.raise_problem(
            "module_input_binding_missing",
            "experiment assembly consumes module inputs without bindings or point "
            "values: " + ", ".join(missing),
            "inputs",
        )


def _point_domain_input_dependencies(
    domain: PointDomainIntent,
    *,
    inputs: Mapping[str, object],
) -> set[str]:
    """Return imports not closed by directional point-domain composition."""

    def visit(node: PointDomainIntent) -> tuple[set[str], set[str]]:
        if isinstance(node, PointUnit):
            return set(), set()
        if isinstance(node, PointRelationRows):
            return (
                _nested_input_dependencies(node.rows, inputs=inputs)
                - internal_value_ref_bound_point_input_ids(node.rows),
                set(internal_value_ref_free_point_input_ids(node.rows)),
            )
        if isinstance(node, PointProduct):
            children = tuple(visit(factor) for factor in node.factors)
        elif isinstance(node, PointZip):
            children = tuple(visit(source) for source in node.sources)
        else:
            left_dependencies, left_point_inputs = visit(node.left)
            right_dependencies, right_point_inputs = visit(node.right)
            bound_ids = set(point_domain_intent_output_types(node.left))
            closed_right_inputs = right_point_inputs & bound_ids
            return (
                left_dependencies | (right_dependencies - closed_right_inputs),
                left_point_inputs | (right_point_inputs - bound_ids),
            )
        return (
            {
                input_id
                for dependencies, _point_inputs in children
                for input_id in dependencies
            },
            {
                input_id
                for _dependencies, point_inputs in children
                for input_id in point_inputs
            },
        )

    dependencies, _point_inputs = visit(domain)
    return dependencies


def _nested_input_dependencies(
    value: object,
    *,
    inputs: Mapping[str, object],
    seen: frozenset[int] = frozenset(),
) -> set[str]:
    if isinstance(value, ValueRef):
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            return set()
        return set(
            value_input_refs(
                bind_value_input_refs(
                    lowered,
                    inputs,
                    preserve_unbound_inputs=True,
                )
            )
        )
    if isinstance(value, Mapping):
        selected = cast("Mapping[object, object]", value)
        marker = id(selected)
        if marker in seen:
            return set()
        nested_seen = seen | {marker}
        return {
            input_id
            for item in selected.values()
            for input_id in _nested_input_dependencies(
                item,
                inputs=inputs,
                seen=nested_seen,
            )
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        selected = cast("Sequence[object]", value)
        marker = id(selected)
        if marker in seen:
            return set()
        nested_seen = seen | {marker}
        return {
            input_id
            for item in selected
            for input_id in _nested_input_dependencies(
                item,
                inputs=inputs,
                seen=nested_seen,
            )
        }
    return set()


def _reject_duplicates(
    ctx: ExperimentAuthoringContext,
    *,
    ids: Sequence[str],
    code: str,
    message: str,
    path: str,
) -> None:
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        ctx.raise_problem(
            code,
            f"{message}: {', '.join(duplicates)}",
            path,
        )


def lower_point_domain(
    point_domain: PointDomainIntent,
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
    entity_input_ids: Sequence[str] = (),
) -> PointDomain:
    """Bind and verify every relation leaf under its exact algebra role."""

    analysis = analyze_point_domain(
        point_domain,
        leaf_value_type=_point_domain_leaf_value_type,
    )
    root = _lower_point_domain_node(
        point_domain,
        path=(),
        ambient_row=type_bindings.point_row,
        analysis=analysis,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    value_type = analysis.root.value_type
    point_column_ids = {column.id for column in value_type.columns}
    return PointDomain(
        root=root,
        entity_columns=tuple(
            column_id
            for column_id in dict.fromkeys(entity_input_ids)
            if column_id in point_column_ids
        ),
    )


def _lower_point_domain_node(
    node: PointDomainIntent,
    *,
    path: PointDomainPath,
    ambient_row: RowType | None,
    analysis: PointDomainAnalysis,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> PointDomainExpr[TableValueExpr]:
    if isinstance(node, PointUnit):
        return POINT_UNIT
    if isinstance(node, PointRelationRows):
        value_type = _point_domain_leaf_value_type(node.rows, path)
        return PointRelationRows(
            verify_value_expr(
                bind_relation_input_refs(
                    internal_lower_table_value_ref(node.rows),
                    inputs,
                ),
                bindings=replace(type_bindings, point_row=ambient_row),
                expected_type=value_type,
            ),
            relation_use_id=node.relation_use_id,
        )
    if isinstance(node, PointProduct):
        return PointProduct(
            tuple(
                _lower_point_domain_node(
                    factor,
                    path=(*path, "factors", index),
                    ambient_row=ambient_row,
                    analysis=analysis,
                    inputs=inputs,
                    type_bindings=type_bindings,
                )
                for index, factor in enumerate(node.factors)
            )
        )
    if isinstance(node, PointZip):
        return PointZip(
            tuple(
                _lower_point_domain_node(
                    source,
                    path=(*path, "sources", index),
                    ambient_row=ambient_row,
                    analysis=analysis,
                    inputs=inputs,
                    type_bindings=type_bindings,
                )
                for index, source in enumerate(node.sources)
            )
        )
    left_path = (*path, "left")
    left = _lower_point_domain_node(
        node.left,
        path=left_path,
        ambient_row=ambient_row,
        analysis=analysis,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    right_ambient = _extend_point_row(
        ambient_row,
        analysis.facts[left_path].value_type,
    )
    right = _lower_point_domain_node(
        node.right,
        path=(*path, "right"),
        ambient_row=right_ambient,
        analysis=analysis,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    return PointDependentProduct(left, right)


def _point_domain_leaf_value_type(
    value: ValueRef,
    _path: PointDomainPath,
) -> TableType:
    value_type = value.value_type
    if not isinstance(value_type, TableType):
        msg = "point-domain relation leaf must be table-shaped"
        raise TypeError(msg)
    return value_type


def _extend_point_row(parent: RowType | None, child: TableType) -> RowType:
    return RowType(
        (*(() if parent is None else parent.columns), *child.columns),
        (False if parent is None else parent.allow_extra_columns)
        or child.allow_extra_columns,
    )


def state_specs(
    bindings: Sequence[BindingSpec],
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> list[StateSpec]:
    specs: list[StateSpec] = []
    for binding in bindings:
        value = binding.value
        specs.append(
            set_state_field(
                resource_port_id=binding.resource_port_id,
                capability_id=binding.capability_id,
                field_path=binding.field_path,
                value=(
                    value
                    if isinstance(value, ComputeResultRef)
                    else verify_scalar_value_expr(
                        bind_scalar_input_refs(value, inputs),
                        bindings=type_bindings,
                        expected_type=binding.value_type,
                    )
                ),
            )
        )
    return specs


def input_row(inputs: Mapping[str, object]) -> dict[str, CellValue]:
    row: dict[str, CellValue] = {}
    for key, value in inputs.items():
        try:
            row[key] = input_cell(value)
        except TypeError:
            continue
    return row
