"""Lower verified logical-program values into config-bound compiler values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entity,
)
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
    raise_frontend_problem,
)
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
from scopecat.compiler.frontend.value_binding import (
    bind_scalar_input_refs,
    bind_table_source,
    expression_input_refs,
    input_cell,
)
from scopecat.compiler.parameter_overlays import PointParameterOverlay
from scopecat.compiler.point_domain import PointDomain
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    verify_scalar_expression,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
    as_scalar_expr,
)
from scopecat.program.logical import LogicalProgram
from scopecat.program.operations import ModuleInputPort
from scopecat.program.point_domain import (
    PointAxes,
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDomainLayout,
)
from scopecat.program.scans import (
    AxisSpec,
    parameter_cell_lookup,
)
from scopecat.program.table_values import InputTableSource
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
)
from scopecat.program.value_types import Table as TableType
from scopecat.program.value_types import ValueType, ValueValidationError, coerce_literal
from scopecat.records.config import Topology
from scopecat.records.parameter import ParameterCatalog


def lower_parameter_overlay_intent(
    parameter_catalog: ParameterCatalog,
    static_evaluator: StaticRelationEvaluator,
    intent: AxisSpec,
    inputs: Mapping[str, object],
    *,
    type_bindings: ExpressionTypeBindings,
) -> PointParameterOverlay:
    lookup, key = parameter_cell_lookup(intent)
    definition = parameter_catalog.get(lookup.table_id)
    if definition is None or not isinstance(definition.value_type, TableType):
        raise AssertionError("validated parameter overlay table is missing")
    columns = {column.id: column for column in definition.value_type.columns}
    try:
        target_column = columns[lookup.column_id]
        key_types = {column_id: columns[column_id].value_type for column_id, _ in key}
    except KeyError as error:
        raise AssertionError("validated parameter overlay column is missing") from error
    try:
        require_assignable(
            intent.value_type,
            target_column.value_type,
            path=("parameter_overlays", intent.id),
        )
    except ValueValidationError as error:
        raise_frontend_problem(
            "authoring_parameter_scan_type_mismatch",
            f"parameter scan cannot write the selected column: {error}",
            "parameters",
            path=(lookup.table_id, "columns", lookup.column_id),
        )
    key_values: dict[str, CellValue] = {}
    for name, value in key:
        expression = (
            internal_lower_scalar_value_ref(value)
            if isinstance(value, ValueRef)
            else as_scalar_expr(value, value_type=key_types[name])
        )
        key_values[name] = static_evaluator.scalar(
            bind_scalar_input_refs(expression, inputs),
            bindings=type_bindings,
            expected_type=key_types[name],
            inputs=input_row(inputs),
        )
    try:
        row_index = static_evaluator.parameters.lookup_row_index(
            lookup.table_id,
            key_values,
        )
    except (KeyError, ValueError) as error:
        raise_frontend_problem(
            "experiment_parameter_overlay_row_not_found",
            f"parameter scan cell could not be selected: {error}",
            "parameter_overlays",
            path=(intent.id, "key"),
        )
    return PointParameterOverlay(
        table_id=lookup.table_id,
        row_index=row_index,
        key=key_values,
        column_id=lookup.column_id,
        axis_id=intent.id,
        value_type=intent.value_type,
    )


def validate_entity_inputs(
    topology: Topology,
    entity_inputs: tuple[str, ...],
    inputs: Mapping[str, object],
) -> None:
    for input_id in entity_inputs:
        if input_id not in inputs:
            continue
        value = inputs.get(input_id)
        if isinstance(value, ValueRef):
            continue
        try:
            if isinstance(value, str) and value:
                resolve_entity(topology, value)
                continue
            if isinstance(value, EntityRef):
                resolve_entity(topology, value)
                continue
        except EntityResolutionError as error:
            raise_entity_resolution_problem(error)
        raise_frontend_problem(
            "module_entity_input_invalid",
            f"module entity input {input_id} must be an entity",
            "inputs",
            path=(input_id,),
        )


def coerce_logical_inputs(
    ports: Sequence[ModuleInputPort],
    inputs: Mapping[str, object],
) -> dict[str, object]:
    declared: dict[str, ValueType] = {}
    for port in ports:
        existing = declared.get(port.id)
        if existing is not None and existing != port.value_type:
            raise_frontend_problem(
                "module_input_type_conflict",
                f"module input {port.id} has incompatible value types",
                "inputs",
                path=(port.id,),
                phase=ProblemPhase.AUTHORING,
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
                raise_frontend_problem(
                    "module_input_type_mismatch",
                    str(error),
                    "inputs",
                    path=(input_id,),
                    phase=ProblemPhase.AUTHORING,
                )
            continue
        try:
            result[input_id] = coerce_literal(
                value_type,
                value,
                path=("inputs", input_id),
            )
        except ValueValidationError as error:
            raise_frontend_problem(
                "module_input_type_mismatch",
                str(error),
                "inputs",
                path=(input_id,),
                phase=ProblemPhase.AUTHORING,
            )
    return result


def validate_consumed_inputs(
    program: LogicalProgram,
    inputs: Mapping[str, object],
) -> None:
    """Reject only free module inputs that the logical program actually uses."""

    consumed_dependencies: set[str] = set()
    values: list[object] = []
    values.extend(
        source
        for port in program.resource_ports
        for source in port.selector.entity_inputs
    )
    values.extend(
        value
        for overlay in program.parameter_overlays
        for _name, value in parameter_cell_lookup(overlay)[1]
    )
    consumed_dependencies.update(
        input_id
        for definition in program.value_defs
        for input_id in _value_source_dependencies(definition.source)
    )
    values.extend(
        axis.size for product in program.product_declarations for axis in product.axes
    )
    for value in values:
        consumed_dependencies.update(_nested_input_dependencies(value, inputs=inputs))

    provided = set(inputs)
    missing = sorted(consumed_dependencies - provided)
    if missing:
        raise_frontend_problem(
            "module_input_binding_missing",
            "logical program consumes module inputs without bindings: "
            + ", ".join(missing),
            "inputs",
            phase=ProblemPhase.AUTHORING,
        )


_EMPTY_VISITED_VALUE_IDS: frozenset[int] = frozenset()


def _nested_input_dependencies(
    value: object,
    *,
    inputs: Mapping[str, object],
    seen: frozenset[int] = _EMPTY_VISITED_VALUE_IDS,
) -> set[str]:
    if isinstance(value, ValueRef):
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultScalarExpr):
            return set()
        if isinstance(lowered, ScalarExpr):
            return set(
                expression_input_refs(
                    bind_scalar_input_refs(
                        lowered,
                        inputs,
                    )
                )
            )
        bound = bind_table_source(lowered, inputs)
        return {bound.input_id} if isinstance(bound, InputTableSource) else set()
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
        selected = value
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


def _value_source_dependencies(source: object) -> tuple[str, ...]:
    if isinstance(source, ScalarExpr):
        return expression_input_refs(source)
    if isinstance(source, InputTableSource):
        return (source.input_id,)
    return ()


def lower_point_domain(
    point_domain: PointAxes[ValueRef],
    *,
    inputs: Mapping[str, object],
    type_bindings: ExpressionTypeBindings,
    layout: PointDomainLayout = "product_grid",
) -> PointDomain:
    """Bind and verify each closed linear-axis center."""

    return PointDomain(
        axes=tuple(
            _lower_point_axis(
                axis,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            for axis in point_domain
        ),
        layout=layout,
    )


def _lower_point_axis(
    axis: PointAxis[ValueRef],
    *,
    inputs: Mapping[str, object],
    type_bindings: ExpressionTypeBindings,
) -> PointAxis[ScalarExpr]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return PointAxis(
            id=axis.id,
            value_type=axis.value_type,
            source=PointAxisValues(values=tuple(source.values)),
        )
    center = verify_scalar_expression(
        bind_scalar_input_refs(
            internal_lower_scalar_value_ref(source.center),
            inputs,
        ),
        bindings=type_bindings,
        expected_type=axis.value_type,
    )
    return PointAxis(
        id=axis.id,
        value_type=axis.value_type,
        source=PointAxisLinear(
            center=center,
            span=source.span,
            count=source.count,
        ),
    )


def input_row(inputs: Mapping[str, object]) -> dict[str, CellValue]:
    row: dict[str, CellValue] = {}
    for key, value in inputs.items():
        try:
            row[key] = input_cell(value)
        except TypeError:
            continue
    return row
