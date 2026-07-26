"""Validate and lower a composed authoring assembly into compiler values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.authoring._intents import ModuleInputPort, ParameterScanOverlayIntent
from scopecat.authoring._point_domain_intents import (
    PointDomainIntent,
    point_domain_intent_output_types,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
)
from scopecat.authoring.value_types import Table as TableType
from scopecat.authoring.value_types import (
    ValueType,
    ValueValidationError,
    coerce_literal,
)
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entities,
    resolve_entity,
)
from scopecat.compiler.frontend.binding_lowering import BindingSpec
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
    raise_frontend_problem,
)
from scopecat.compiler.frontend.value_binding import (
    bind_scalar_input_refs,
    bind_value_input_refs,
    input_cell,
    literal_data_expr,
    value_input_refs,
)
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    CellValue,
    RelationExpr,
    ScalarExpr,
    ScalarExpression,
    SeriesExpr,
    as_scalar_expr,
    point_col,
)
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDomainExpr,
    PointProduct,
    PointUnit,
)
from scopecat.compiler.relations.uses import RelationUse, relation_use
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
)
from scopecat.compiler.semantic.compute_result import ComputeOutput, ComputeResultRef
from scopecat.compiler.semantic.model import (
    LocalPythonImplementation,
    OperationId,
    PlanExpressionSource,
    SemanticDomainExecution,
    SemanticOperation,
    ValueDef,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import ScalarBinarySemantics
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    verify_scalar_value_expr,
    verify_value_expr,
)
from scopecat.compiler.semantic.verification import VerifiedSemanticGraph
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    TypedComputeNode,
    TypedDomainExecution,
    TypedDomainResultBinding,
    ValueInput,
    set_state_field,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.records.config import Topology
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import ParameterCatalog


def lower_parameter_overlay_intent(
    parameter_catalog: ParameterCatalog,
    intent: ParameterScanOverlayIntent,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> PointParameterOverlay:
    definition = parameter_catalog.get(intent.table_id)
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
            if isinstance(value, Sequence) and not isinstance(value, str | bytes):
                selected = cast("Sequence[EntityRef | str]", value)
                resolve_entities(topology, selected)
                continue
        except EntityResolutionError as error:
            raise_entity_resolution_problem(error)
        raise_frontend_problem(
            "module_entity_input_invalid",
            f"module entity input {input_id} must be an entity or entity series",
            "inputs",
            path=(input_id,),
        )


def lower_semantic_compute_graph(
    graph: VerifiedSemanticGraph,
    implementations: Mapping[OperationId, LocalPythonImplementation],
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> tuple[TypedComputeNode, ...]:
    """Lower implementation-defined operations to the local residual artifact."""

    residual_operations = graph.residual_operation_ids
    residual_values = graph.residual_value_ids
    nodes = tuple(
        _lower_semantic_operation(
            operation,
            implementation=implementations[operation.id],
            definitions=graph.value_defs,
            operation_results=graph.operation_results,
            value_types=graph.value_types,
            residual_values=residual_values,
            inputs=inputs,
            type_bindings=type_bindings,
        )
        for operation in graph.graph.operations
        if operation.id in residual_operations
    )
    return nodes


def lower_semantic_domain_graph(
    graph: VerifiedSemanticGraph,
    executions: Sequence[SemanticDomainExecution],
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
    product_uses: Sequence[ProductUse],
) -> tuple[TypedDomainExecution, ...]:
    """Lower ordered prepare-stage domain effects and their product uses."""

    residual_values = graph.residual_value_ids
    uses_by_product: dict[ProductId, list[ProductUseId]] = {}
    for use in product_uses:
        uses_by_product.setdefault(use.product_id, []).append(use.id)
    typed_executions: list[TypedDomainExecution] = []
    for execution in executions:
        lowered_inputs: dict[str, ValueInput] = {}
        for name, use in execution.inputs:
            lowered = _lower_semantic_input(
                use.value_id,
                definitions=graph.value_defs,
                operation_results=graph.operation_results,
                value_types=graph.value_types,
                residual_values=residual_values,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            if not isinstance(lowered, ValueInput):
                raise AssertionError(
                    "verified domain execution inputs must lower to plan values"
                )
            lowered_inputs[name] = lowered
        lowered_compiler_inputs: dict[str, ValueInput] = {}
        for name, use in execution.compiler_inputs:
            lowered = _lower_semantic_input(
                use.value_id,
                definitions=graph.value_defs,
                operation_results=graph.operation_results,
                value_types=graph.value_types,
                residual_values=residual_values,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            if not isinstance(lowered, ValueInput):
                raise AssertionError(
                    "verified domain compiler inputs must lower to plan values"
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
                resources=dict(execution.resources),
            )
        )
    return tuple(typed_executions)


def _lower_semantic_operation(
    operation: SemanticOperation,
    *,
    implementation: LocalPythonImplementation,
    definitions: Mapping[ValueId, ValueDef],
    operation_results: Mapping[ValueId, SemanticOperation],
    value_types: Mapping[ValueId, ValueType],
    residual_values: frozenset[ValueId],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> TypedComputeNode:
    return TypedComputeNode(
        id=operation.id,
        contract=operation.contract,
        implementation=implementation,
        inputs={
            name: _lower_semantic_input(
                use.value_id,
                definitions=definitions,
                operation_results=operation_results,
                value_types=value_types,
                residual_values=residual_values,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            for name, use in operation.inputs
        },
        result=ComputeOutput(
            id=operation.result_id,
            value_type=operation.result_type,
        ),
    )


def _lower_semantic_input(
    value_id: ValueId,
    *,
    definitions: Mapping[ValueId, ValueDef],
    operation_results: Mapping[ValueId, SemanticOperation],
    value_types: Mapping[ValueId, ValueType],
    residual_values: frozenset[ValueId],
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> ValueInput | ComputeEdge:
    if value_id in residual_values:
        return ComputeEdge(
            value_id=value_id,
            expected_type=value_types[value_id],
        )
    expression = _semantic_plan_expression(
        value_id,
        definitions=definitions,
        operation_results=operation_results,
        active=frozenset(),
    )
    origin_input_ids = tuple(value_input_refs(expression))
    return ValueInput(
        value=verify_value_expr(
            bind_value_input_refs(expression, inputs),
            bindings=type_bindings,
            expected_type=value_types[value_id],
        ),
        origin_input_ids=origin_input_ids,
    )


def _semantic_plan_expression(
    value_id: ValueId,
    *,
    definitions: Mapping[ValueId, ValueDef],
    operation_results: Mapping[ValueId, SemanticOperation],
    active: frozenset[ValueId],
) -> ScalarExpr | SeriesExpr | RelationExpr:
    if value_id in active:
        raise AssertionError("verified semantic graph contains a plan-value cycle")
    definition = definitions.get(value_id)
    if definition is not None:
        source = definition.source
        if isinstance(source, PlanExpressionSource):
            return source.expression
        return literal_data_expr(source.value)
    operation = operation_results[value_id]
    if not isinstance(operation.contract, ScalarBinarySemantics):
        raise AssertionError("only core scalar operations can be plan-inlined")
    uses = dict(operation.inputs)
    nested_active = active | {value_id}
    left = _semantic_plan_expression(
        uses["left"].value_id,
        definitions=definitions,
        operation_results=operation_results,
        active=nested_active,
    )
    right = _semantic_plan_expression(
        uses["right"].value_id,
        definitions=definitions,
        operation_results=operation_results,
        active=nested_active,
    )
    if not isinstance(left, ScalarExpr) or not isinstance(right, ScalarExpr):
        raise AssertionError("scalar semantic operands must lower to scalar plans")
    return BinaryScalarExpr(
        op=operation.contract.operator,
        left=cast("ScalarExpression", left),
        right=cast("ScalarExpression", right),
    )


def validate_assembly_entrypoint(assembly: SemanticExperimentIR) -> None:
    """Require the identity needed to lower a verified root assembly."""

    if not assembly.experiment_id:
        raise_frontend_problem(
            "experiment_assembly_entrypoint_missing_id",
            "experiment assembly must be linked with an experiment id",
            "experiment_id",
            phase=ProblemPhase.AUTHORING,
        )
    if not assembly.kind:
        raise_frontend_problem(
            "experiment_assembly_entrypoint_missing_kind",
            "experiment assembly must be linked with an experiment kind",
            "kind",
            phase=ProblemPhase.AUTHORING,
        )


def coerce_assembly_inputs(
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
    assembly: SemanticExperimentIR,
    inputs: Mapping[str, object],
) -> None:
    """Reject only free module inputs that the assembled program actually uses."""

    point_input_ids = set(point_domain_intent_output_types(assembly.point_domain))
    point_domain_dependencies = point_domain_input_dependencies(
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
    values.extend(
        axis.size for product in assembly.product_declarations for axis in product.axes
    )
    for value in values:
        consumed_dependencies.update(_nested_input_dependencies(value, inputs=inputs))

    provided = set(inputs)
    missing = sorted(
        (point_domain_dependencies - provided)
        | (consumed_dependencies - provided - point_input_ids)
    )
    if missing:
        raise_frontend_problem(
            "module_input_binding_missing",
            "experiment assembly consumes module inputs without bindings or point "
            "values: " + ", ".join(missing),
            "inputs",
            phase=ProblemPhase.AUTHORING,
        )


def point_domain_input_dependencies(
    domain: PointDomainIntent,
    *,
    inputs: Mapping[str, object],
) -> set[str]:
    """Return runtime inputs consumed by closed linear-axis centers."""

    axes = (
        ()
        if isinstance(domain, PointUnit)
        else (domain,)
        if isinstance(domain, PointAxis)
        else domain.factors
    )
    return {
        input_id
        for axis in axes
        if isinstance(axis.source, PointAxisLinear)
        for input_id in _nested_input_dependencies(
            axis.source.center,
            inputs=inputs,
        )
    }


_EMPTY_VISITED_VALUE_IDS: frozenset[int] = frozenset()


def _nested_input_dependencies(
    value: object,
    *,
    inputs: Mapping[str, object],
    seen: frozenset[int] = _EMPTY_VISITED_VALUE_IDS,
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


def lower_point_domain(
    point_domain: PointDomainIntent,
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> PointDomain:
    """Bind and verify each closed linear-axis center."""

    if isinstance(point_domain, PointUnit):
        root: PointDomainExpr[RelationUse[ScalarValueExpr]] = POINT_UNIT
    elif isinstance(point_domain, PointAxis):
        root = _lower_point_axis(
            point_domain,
            inputs=inputs,
            type_bindings=type_bindings,
        )
    else:
        root = PointProduct(
            tuple(
                _lower_point_axis(
                    axis,
                    inputs=inputs,
                    type_bindings=type_bindings,
                )
                for axis in point_domain.factors
            )
        )
    return PointDomain(root=root)


def _lower_point_axis(
    axis: PointAxis[ValueRef],
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return PointAxis(
            id=axis.id,
            value_type=axis.value_type,
            source=PointAxisValues(values=tuple(source.values)),
        )
    center = relation_use(
        verify_scalar_value_expr(
            bind_scalar_input_refs(
                internal_lower_scalar_value_ref(source.center),
                inputs,
            ),
            bindings=type_bindings,
            expected_type=axis.value_type,
        )
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


def state_spec(
    binding: BindingSpec,
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> SetStateSpec:
    value = binding.value
    return set_state_field(
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


def input_row(inputs: Mapping[str, object]) -> dict[str, CellValue]:
    row: dict[str, CellValue] = {}
    for key, value in inputs.items():
        try:
            row[key] = input_cell(value)
        except TypeError:
            continue
    return row
