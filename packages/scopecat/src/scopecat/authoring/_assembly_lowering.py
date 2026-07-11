"""Validate and lower a composed authoring assembly into compiler values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat._compiler.parameter_overlays import (
    PointParameterOverlay,
    TypedOverlayExpression,
)
from scopecat._compiler.program import (
    ComputeEdge,
    RouteInput,
    TypedComputeNode,
    TypedPointSource,
    ValueInput,
    bind_each,
    set_state,
)
from scopecat._compiler.state import StateSpec
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    CellValue,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    col,
    literal_rows,
    values,
)
from scopecat._value_expressions import as_value_expr
from scopecat.authoring._binding_intents import ResourcePort
from scopecat.authoring._binding_lowering import (
    BindingSpec,
    require_port_capability,
)
from scopecat.authoring._context import ExperimentAuthoringContext
from scopecat.authoring._intents import (
    ClosedScalarValue,
    ComputeNodeInputValue,
    ComputeNodeIntent,
    ModuleInputPort,
    ParameterScanOverlayIntent,
    StateEachIntent,
    StateRouteValue,
)
from scopecat.authoring._module_composition import ExperimentAssemblyInternal
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
    require_assignable,
)
from scopecat.authoring._value_type_compatibility import literal_scalar_type
from scopecat.authoring.value_types import Table as TableType
from scopecat.authoring.value_types import (
    ValueType,
    ValueValidationError,
    coerce_literal,
)
from scopecat.authoring.values import RouteRef
from scopecat.models.entity import EntityRef


def lower_parameter_overlay_intent(
    ctx: ExperimentAuthoringContext,
    intent: ParameterScanOverlayIntent,
    inputs: Mapping[str, object],
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
        key={
            name: TypedOverlayExpression(
                expr=bind_scalar_input_refs(
                    internal_lower_scalar_value_ref(value)
                    if isinstance(value, ValueRef)
                    else as_scalar_expr(value),
                    inputs,
                ),
                value_type=key_types[name],
            )
            for name, value in intent.key
        },
        column_id=intent.column_id,
        value=TypedOverlayExpression(
            expr=col(intent.point_id),
            value_type=target_column.value_type,
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
        ctx.raise_diagnostic(
            "module_entity_input_invalid",
            f"module entity input {input_id} must be an entity or entity series",
            input_id,
        )


def lower_compute_node_intent(
    node: ComputeNodeIntent,
    inputs: Mapping[str, object],
) -> TypedComputeNode:
    return TypedComputeNode(
        id=node.node_id,
        inputs={
            name: compute_node_input(
                value,
                inputs,
            )
            for name, value in node.inputs
        },
        output_type=node.output_type,
        fn=node.fn,
    )


def lower_state_intent(
    ctx: ExperimentAuthoringContext,
    intent: StateEachIntent,
    resource_ports: Mapping[str, ResourcePort],
    inputs: Mapping[str, object],
) -> StateSpec:
    capability_id = _state_field_capability(ctx, intent.field)
    if intent.resource_port is not None:
        port = resource_ports.get(intent.resource_port)
        if port is None:
            ctx.raise_diagnostic(
                "module_unknown_resource_port",
                "state binding references unknown resource port "
                f"{intent.resource_port}",
                "state",
            )
        require_port_capability(ctx, port, capability_id)
    return bind_each(
        bind_relation_input_refs(
            internal_lower_table_value_ref(intent.relation),
            inputs,
            unbound_to_outer=True,
        ),
        set_state(
            _bind_scalar_value_ref(
                intent.resource,
                inputs,
                unbound_to_outer=True,
            ),
            intent.field,
            _bind_state_value(
                intent.value,
                inputs,
                unbound_to_outer=True,
            ),
            route_entities=tuple(
                _bind_state_route_expr(
                    ctx,
                    entity,
                    inputs,
                    unbound_to_outer=True,
                )
                for entity in intent.route_entities
            ),
        ),
    )


def validate_assembly_conflicts(
    ctx: ExperimentAuthoringContext,
    assembly: ExperimentAssemblyInternal,
) -> None:
    _reject_duplicates(
        ctx,
        ids=[
            *(record.id for record in assembly.records),
            *(
                selection.record_id or selection.product_id
                for selection in assembly.record_selections
            ),
        ],
        code="module_record_duplicate",
        message="experiment assembly defines duplicate records",
        path="records",
    )
    _reject_duplicates(
        ctx,
        ids=[product.id for product in assembly.product_ports],
        code="module_product_duplicate",
        message="experiment assembly defines duplicate products",
        path="products",
    )
    _reject_duplicates(
        ctx,
        ids=[node.node_id.qualified_name for node in assembly.compute_nodes],
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
            ctx.raise_diagnostic(
                "module_input_type_conflict",
                f"module input {port.id} has incompatible value types",
                f"inputs.{port.id}",
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
                    path=f"inputs.{input_id}",
                )
            except ValueValidationError as error:
                ctx.raise_diagnostic(
                    "module_input_type_mismatch",
                    str(error),
                    error.path,
                )
            continue
        try:
            result[input_id] = coerce_literal(
                value_type,
                value,
                path=f"inputs.{input_id}",
            )
        except ValueValidationError as error:
            ctx.raise_diagnostic(
                "module_input_type_mismatch",
                str(error),
                error.path,
            )
    return result


def validate_consumed_inputs(
    ctx: ExperimentAuthoringContext,
    assembly: ExperimentAssemblyInternal,
    inputs: Mapping[str, object],
) -> None:
    """Reject only free module inputs that the assembled program actually uses."""

    point_input_ids = (
        {column.id for column in assembly.point_source.value_type.columns}
        if assembly.point_source is not None
        and isinstance(assembly.point_source.value_type, TableType)
        else set[str]()
    )
    point_source_dependencies = _nested_input_dependencies(
        assembly.point_source,
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
    for intent in assembly.state_intents:
        values.extend(
            (
                intent.relation,
                intent.resource,
                intent.value,
                *intent.route_entities,
            )
        )
    values.extend(
        value for overlay in assembly.parameter_overlays for _name, value in overlay.key
    )
    values.extend(
        value for node in assembly.compute_nodes for _name, value in node.inputs
    )
    values.extend(axis.size for record in assembly.records for axis in record.axes)
    values.extend(
        axis.size for product in assembly.product_ports for axis in product.axes
    )
    for value in values:
        consumed_dependencies.update(_nested_input_dependencies(value, inputs=inputs))

    provided = set(inputs)
    missing = sorted(
        (point_source_dependencies - provided)
        | (consumed_dependencies - provided - point_input_ids)
    )
    if missing:
        ctx.raise_diagnostic(
            "module_input_binding_missing",
            "experiment assembly consumes module inputs without bindings or point "
            "values: " + ", ".join(missing),
            "inputs",
        )


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
        ctx.raise_diagnostic(
            code,
            f"{message}: {', '.join(duplicates)}",
            path,
        )


def lower_point_source(
    point_source: ValueRef | None,
    *,
    inputs: Mapping[str, object],
    entity_input_ids: Sequence[str] = (),
) -> TypedPointSource:
    """Bind invocation inputs while retaining config-dependent point intent."""

    if point_source is None:
        relation = literal_rows([{}])
        value_type = TableType(columns=(), min_rows=1, max_rows=1)
    else:
        relation = internal_lower_table_value_ref(point_source)
        value_type = point_source.value_type
        if not isinstance(value_type, TableType):
            raise AssertionError("validated point source must remain table-shaped")
    return TypedPointSource(
        expr=bind_relation_input_refs(relation, inputs),
        value_type=value_type,
        entity_column_ids=tuple(dict.fromkeys(entity_input_ids)),
    )


def compute_node_input(
    value: ComputeNodeInputValue,
    inputs: Mapping[str, object],
) -> ValueInput | ComputeEdge | RouteInput:
    if isinstance(value, ValueRef):
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            return ComputeEdge(
                producer=lowered.node_id,
                value_type=value.value_type,
            )
        source_inputs = value_input_refs(lowered)
        bound = bind_value_input_refs(lowered, inputs)
        return ValueInput(
            value=as_value_expr(bound),
            source_inputs=tuple(source_inputs),
            value_type=value.value_type,
        )
    if isinstance(value, RouteRef):
        return RouteInput(
            port_id=value.port_id,
            value_type=value.value_type,
        )
    expression = literal_data_expr(value)
    bound = bind_value_input_refs(expression, inputs)
    return ValueInput(
        value=as_value_expr(bound),
        source_inputs=(),
        value_type=literal_scalar_type(value),
    )


def state_specs(
    bindings: Sequence[BindingSpec],
    *,
    inputs: Mapping[str, object],
) -> list[StateSpec]:
    specs: list[StateSpec] = []
    for binding in bindings:
        value = binding.value
        specs.append(
            set_state(
                binding.resource_id,
                f"{binding.capability_id}.{binding.field_path}",
                (
                    value
                    if isinstance(value, ComputeResultRef)
                    else bind_scalar_input_refs(value, inputs)
                ),
            )
        )
    return specs


def _bind_state_value(
    value: ValueRef | ClosedScalarValue,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
) -> ScalarExpr | ComputeResultRef:
    if isinstance(value, ValueRef):
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            return lowered
        if not isinstance(lowered, ScalarExpr):
            msg = "state value must be scalar-shaped"
            raise TypeError(msg)
        expression = lowered
    else:
        expression = as_scalar_expr(value)
    return bind_scalar_input_refs(
        expression,
        inputs,
        unbound_to_outer=unbound_to_outer,
    )


def _bind_scalar_value_ref(
    value: ValueRef | ClosedScalarValue,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
) -> ScalarExpr:
    if isinstance(value, ValueRef):
        lowered = internal_lower_value_ref(value)
        if not isinstance(lowered, ScalarExpr):
            msg = "state resource must be a scalar expression"
            raise TypeError(msg)
        expression = lowered
    else:
        expression = as_scalar_expr(value)
    return bind_scalar_input_refs(
        expression,
        inputs,
        unbound_to_outer=unbound_to_outer,
    )


def _bind_state_route_expr(
    ctx: ExperimentAuthoringContext,
    expression: StateRouteValue,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
) -> ScalarExpr | SeriesExpr:
    if isinstance(expression, ValueRef):
        lowered = internal_lower_value_ref(expression)
        if isinstance(lowered, ComputeResultRef | RelationExpr):
            ctx.raise_diagnostic(
                "module_resource_entity_input_invalid",
                "state route entity source must be scalar or series-shaped",
                "state.route_entities",
            )
        selected_expression = lowered
    elif isinstance(expression, tuple):
        selected_expression = values([input_cell(value) for value in expression])
    else:
        selected_expression = as_scalar_expr(expression)
    bound = bind_value_input_refs(
        selected_expression,
        inputs,
        unbound_to_outer=unbound_to_outer,
    )
    if isinstance(bound, RelationExpr):
        ctx.raise_diagnostic(
            "module_state_route_entity_invalid",
            "state route entity source must be scalar or series-shaped",
            "state.route_entities",
        )
    return bound


def _state_field_capability(
    ctx: ExperimentAuthoringContext,
    field: str,
) -> str:
    capability_id, separator, field_path = field.partition(".")
    if not separator or not capability_id or not field_path:
        ctx.raise_diagnostic(
            "module_state_field_invalid",
            "state field must use 'capability.field' syntax",
            "state.field",
        )
    return capability_id


def input_row(inputs: Mapping[str, object]) -> dict[str, CellValue]:
    row: dict[str, CellValue] = {}
    for key, value in inputs.items():
        try:
            row[key] = input_cell(value)
        except TypeError:
            continue
    return row
