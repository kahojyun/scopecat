"""Lower verified logical-program values into config-bound compiler values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

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
    input_cell,
    scalar_input_refs,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    ComputeInput,
    TypedComputeNode,
    TypedDomainExecution,
    TypedDomainResultBinding,
)
from scopecat.compiler.typed.values import (
    CompilerValue,
    TableValue,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
    ScalarExpression,
    as_scalar_expr,
)
from scopecat.program.logical import (
    LocalPythonImplementation,
    LogicalComputeNode,
    LogicalDomainExecution,
    LogicalProgram,
    ValueDef,
)
from scopecat.program.operations import ModuleInputPort
from scopecat.program.point_domain import (
    PointAxes,
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
)
from scopecat.program.scans import (
    AxisSpec,
    parameter_cell_lookup,
)
from scopecat.program.table_values import (
    InputTableSource,
    TableSource,
)
from scopecat.program.value_graph import (
    ComputeOutput,
    ValueId,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
)
from scopecat.program.value_types import (
    Table,
    ValueType,
    ValueValidationError,
    coerce_literal,
)
from scopecat.program.value_types import Table as TableType
from scopecat.records.config import Topology
from scopecat.records.parameter import ParameterCatalog


class _LogicalProgramProof(Protocol):
    """Facts exposed by the config-free logical verifier."""

    @property
    def program(self) -> LogicalProgram: ...

    @property
    def value_defs(self) -> Mapping[ValueId, ValueDef]: ...

    @property
    def operation_results(self) -> Mapping[ValueId, LogicalComputeNode]: ...

    @property
    def value_types(self) -> Mapping[ValueId, ValueType]: ...

    @property
    def scalar_values(self) -> Mapping[ValueId, ScalarExpression]: ...


def lower_parameter_overlay_intent(
    parameter_catalog: ParameterCatalog,
    static_evaluator: StaticRelationEvaluator,
    intent: AxisSpec,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
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


def lower_compute_graph(
    program: _LogicalProgramProof,
) -> tuple[TypedComputeNode, ...]:
    """Lower implementation-defined operations to the local residual artifact."""

    nodes = tuple(
        _lower_compute_node(
            program,
            operation,
            implementation=program.program.implementations[operation.id],
        )
        for operation in program.program.compute_nodes
    )
    return nodes


def lower_domain_graph(
    program: _LogicalProgramProof,
    executions: Sequence[LogicalDomainExecution],
    *,
    product_uses: Sequence[ProductUse],
) -> tuple[TypedDomainExecution, ...]:
    """Lower ordered prepare-stage domain effects and their product uses."""

    uses_by_product: dict[ProductId, list[ProductUseId]] = {}
    for use in product_uses:
        uses_by_product.setdefault(use.product_id, []).append(use.id)
    typed_executions: list[TypedDomainExecution] = []
    for execution in executions:
        lowered_inputs: dict[str, ScalarExpression] = {}
        for name, value_id in execution.inputs:
            lowered = cast(
                "ScalarExpression",
                lower_logical_value(
                    program,
                    value_id,
                ),
            )
            lowered_inputs[name] = lowered
        lowered_compiler_inputs: dict[str, CompilerValue] = {}
        for name, value_id in execution.compiler_inputs:
            lowered = lower_logical_value(
                program,
                value_id,
            )
            lowered_compiler_inputs[name] = lowered
        result_bindings: list[TypedDomainResultBinding] = []
        for result_id, product_id in execution.results:
            result_bindings.append(
                TypedDomainResultBinding(
                    id=result_id,
                    product_id=product_id,
                    product_use_ids=tuple(uses_by_product.get(product_id, [])),
                )
            )
        typed_executions.append(
            TypedDomainExecution(
                id=execution.id,
                program=execution.program,
                inputs=lowered_inputs,
                compiler_inputs=lowered_compiler_inputs,
                results=tuple(result_bindings),
            )
        )
    return tuple(typed_executions)


def _lower_compute_node(
    program: _LogicalProgramProof,
    operation: LogicalComputeNode,
    *,
    implementation: LocalPythonImplementation,
) -> TypedComputeNode:
    lowered_inputs: dict[str, ComputeInput] = {}
    for name, value_id in operation.inputs:
        lowered = lower_logical_value(
            program,
            value_id,
        )
        if not isinstance(lowered, ScalarExpr):
            raise AssertionError("verified compute inputs must be scalar")
        lowered_inputs[name] = lowered
    return TypedComputeNode(
        id=operation.id,
        implementation=implementation,
        input_types=dict(operation.input_types),
        inputs=lowered_inputs,
        result=ComputeOutput(
            id=operation.result_id,
            value_type=operation.result_type,
        ),
    )


def lower_logical_value(
    program: _LogicalProgramProof,
    value_id: ValueId,
) -> CompilerValue:
    if value_id in program.operation_results:
        operation = program.operation_results[value_id]
        return ComputeResultScalarExpr(
            value_id=value_id,
            value_type=operation.result_type,
        )
    scalar = program.scalar_values.get(value_id)
    if scalar is not None:
        return scalar
    source = program.value_defs[value_id].source
    value_type = program.value_types[value_id]
    return TableValue(
        source=cast("TableSource", source),
        value_type=cast("Table", value_type),
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
                scalar_input_refs(
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
        return scalar_input_refs(source)
    if isinstance(source, InputTableSource):
        return (source.input_id,)
    return ()


def lower_point_domain(
    point_domain: PointAxes[ValueRef],
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
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
        )
    )


def _lower_point_axis(
    axis: PointAxis[ValueRef],
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> PointAxis[ScalarExpression]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return PointAxis(
            id=axis.id,
            value_type=axis.value_type,
            source=PointAxisValues(values=tuple(source.values)),
        )
    center = verify_relation_plan(
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
