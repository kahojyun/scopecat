"""Backend-neutral typed value and pure-operation graph.

The graph is semantic data only.  Python kernels and authoring provenance are
carried by explicit sidecars so implementation choice and diagnostics cannot
change graph equality.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat.compiler.relations.verification import PlanImportNamespace
from scopecat.compiler.semantic.dependencies import (
    analyze_residual_dependencies,
)
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    LiteralValueSource,
    MeasurementTransformId,
    PlanExpressionSource,
    SemanticDomainExecution,
    SemanticGraphIR,
    SemanticMeasurementTransform,
    SemanticOperation,
    ValueDef,
)
from scopecat.compiler.semantic.operation_contract import (
    ScalarBinarySemantics,
)
from scopecat.graph.relations.model import (
    ParameterLookupUse,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.graph.relations.operators import (
    is_scalar_operator,
    scalar_operator_result_type,
)
from scopecat.graph.values import (
    OperationId,
    ValueId,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import (
    Scalar,
    Series,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.kernel.value_validation import ValueValidationError, validate_literal


@dataclass(frozen=True, slots=True)
class VerifiedSemanticGraph:
    graph: SemanticGraphIR
    value_defs: Mapping[ValueId, ValueDef] = field(
        init=False,
        compare=False,
        hash=False,
    )
    operation_results: Mapping[ValueId, SemanticOperation] = field(
        init=False,
        compare=False,
        hash=False,
    )
    value_types: Mapping[ValueId, ValueType] = field(
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

    def __post_init__(self) -> None:
        definitions = {
            definition.id: definition for definition in self.graph.value_defs
        }
        operation_results = {
            operation.result_id: operation for operation in self.graph.operations
        }
        value_types = {
            definition.id: definition.value_type for definition in self.graph.value_defs
        }
        value_types.update(
            {
                operation.result_id: operation.result_type
                for operation in self.graph.operations
            }
        )
        residual = analyze_residual_dependencies(self.graph.operations)
        object.__setattr__(self, "value_defs", MappingProxyType(definitions))
        object.__setattr__(
            self,
            "operation_results",
            MappingProxyType(operation_results),
        )
        object.__setattr__(self, "value_types", MappingProxyType(value_types))
        object.__setattr__(
            self,
            "residual_value_ids",
            residual.value_ids,
        )
        object.__setattr__(
            self,
            "residual_operation_ids",
            residual.operation_ids,
        )


def verify_semantic_graph(
    graph: SemanticGraphIR,
    *,
    effects: Sequence[SemanticDomainExecution | AcquireEffect] = (),
) -> VerifiedSemanticGraph:
    """Validate closure and normalize semantic dataflow."""

    domain_executions = tuple(
        effect for effect in effects if isinstance(effect, SemanticDomainExecution)
    )
    acquisitions = tuple(
        effect for effect in effects if isinstance(effect, AcquireEffect)
    )
    problems: list[Problem] = []
    definitions, ambiguous_value_ids = _definitions_by_id(
        graph.value_defs,
        problems,
    )
    ambiguous_operation_ids = _ambiguous_operation_ids(
        graph.operations,
        problems,
    )
    ambiguous_measurement_transform_ids = _measurement_transforms_by_id(
        graph.measurement_transforms,
        problems,
    )
    unambiguous_operations = tuple(
        operation
        for operation in graph.operations
        if operation.id not in ambiguous_operation_ids
    )
    operation_results, ambiguous_result_ids = _operation_results_by_id(
        graph.operations,
        unambiguous_operations,
        definitions,
        ambiguous_value_ids,
        ambiguous_operation_ids,
        problems,
    )
    ambiguous_value_ids |= ambiguous_result_ids
    value_types = {
        definition.id: definition.value_type for definition in definitions.values()
    }
    value_types.update(
        {
            result_id: operation.result_type
            for result_id, operation in operation_results.items()
        }
    )
    residual = analyze_residual_dependencies(unambiguous_operations)
    _verify_uses(
        unambiguous_operations,
        value_types,
        ambiguous_value_ids,
        problems,
    )
    execution_ids = tuple(execution.id for execution in domain_executions)
    if len(execution_ids) != len(set(execution_ids)):
        problems.append(
            _problem(
                "semantic_domain_execution_id_duplicate",
                "domain execution ids must be unique",
                "domain_executions",
            )
        )
    acquisition_ids = tuple(acquire.id for acquire in acquisitions)
    if len(acquisition_ids) != len(set(acquisition_ids)):
        problems.append(
            _problem(
                "semantic_acquire_id_duplicate",
                "acquisition ids must be unique",
                "acquisitions",
            )
        )
    for execution_index, execution in enumerate(domain_executions):
        _verify_domain_execution(
            execution,
            value_types,
            residual.value_ids,
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
        acquisitions,
        domain_executions,
        unambiguous_measurement_transforms,
        problems,
    )
    ordered_measurement_transforms = _topological_measurement_transforms(
        unambiguous_measurement_transforms,
        problems,
    )
    _verify_value_sources(tuple(definitions.values()), problems)
    _verify_plan_environment_consistency(tuple(definitions.values()), problems)
    _verify_scalar_operations(
        unambiguous_operations,
        definitions,
        value_types,
        problems,
    )
    ordered_operations = _topological_operations(
        unambiguous_operations,
        operation_results,
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
    )
    return VerifiedSemanticGraph(normalized)


def _measurement_transforms_by_id(
    transforms: tuple[SemanticMeasurementTransform, ...],
    problems: list[Problem],
) -> frozenset[MeasurementTransformId]:
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
            )
        )
    return ambiguous


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
        )
    )
    return transforms


def _verify_domain_execution(
    execution: SemanticDomainExecution,
    value_types: Mapping[ValueId, ValueType],
    residual_value_ids: frozenset[ValueId],
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
    expected_compiler_inputs = tuple(port.id for port in program.compiler_input_ports)
    if (
        tuple(name for name, _use in execution.compiler_inputs)
        != expected_compiler_inputs
    ):
        problems.append(
            _problem(
                "semantic_domain_compiler_input_contract_mismatch",
                "domain compiler inputs do not match the declared program ports",
                *location,
                "compiler_inputs",
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
        value_type = value_types.get(use.value_id)
        if value_type is None:
            if use.value_id not in ambiguous_value_ids:
                problems.append(
                    _problem(
                        "semantic_domain_execution_input_dangling",
                        f"domain execution input {name!r} references unknown value "
                        f"{use.value_id.qualified_name!r}",
                        *location,
                        "inputs",
                        name,
                    )
                )
            continue
        port = input_ports.get(name)
        if port is not None and not is_assignable(
            value_type,
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
        if use.value_id in residual_value_ids:
            problems.append(
                _problem(
                    "semantic_domain_execution_input_stage_unavailable",
                    f"domain execution input {name!r} must be available at plan stage",
                    *location,
                    "inputs",
                    name,
                )
            )
    compiler_input_ports = {port.id: port for port in program.compiler_input_ports}
    for name, use in execution.compiler_inputs:
        value_type = value_types.get(use.value_id)
        if value_type is None:
            if use.value_id not in ambiguous_value_ids:
                problems.append(
                    _problem(
                        "semantic_domain_compiler_input_dangling",
                        f"domain compiler input {name!r} references unknown value "
                        f"{use.value_id.qualified_name!r}",
                        *location,
                        "compiler_inputs",
                        name,
                    )
                )
            continue
        port = compiler_input_ports.get(name)
        if port is not None and not is_assignable(
            value_type,
            port.value_type,
        ):
            problems.append(
                _problem(
                    "semantic_domain_compiler_input_type_mismatch",
                    f"domain compiler input {name!r} is not assignable to its "
                    "declared port type",
                    *location,
                    "compiler_inputs",
                    name,
                )
            )
        if use.value_id in residual_value_ids:
            problems.append(
                _problem(
                    "semantic_domain_compiler_input_stage_unavailable",
                    f"domain compiler input {name!r} must be available at plan stage",
                    *location,
                    "compiler_inputs",
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
                )
            )
        else:
            product_owners[product_id] = result_name


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
            )
        )
    selected = {
        value_id: grouped[value_id][0]
        for value_id in sorted(grouped, key=lambda item: item.qualified_name)
        if value_id not in ambiguous
    }
    return selected, ambiguous


def _ambiguous_operation_ids(
    operations: tuple[SemanticOperation, ...],
    problems: list[Problem],
) -> frozenset[OperationId]:
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
            )
        )
    return ambiguous


def _operation_results_by_id(
    declared: tuple[SemanticOperation, ...],
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    ambiguous_definition_ids: frozenset[ValueId],
    ambiguous_operation_ids: frozenset[OperationId],
    problems: list[Problem],
) -> tuple[dict[ValueId, SemanticOperation], frozenset[ValueId]]:
    grouped: dict[ValueId, list[SemanticOperation]] = {}
    for operation in operations:
        grouped.setdefault(operation.result_id, []).append(operation)
    ambiguous = {
        operation.result_id
        for operation in declared
        if operation.id in ambiguous_operation_ids
    }
    ambiguous.update(
        result_id for result_id, owners in grouped.items() if len(owners) > 1
    )
    collisions = set(grouped) & (set(definitions) | set(ambiguous_definition_ids))
    ambiguous.update(collisions)
    for result_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        if result_id in collisions:
            message = (
                f"value {result_id.qualified_name!r} is defined both as a plan "
                "value and an operation result"
            )
        elif result_id in grouped and len(grouped[result_id]) > 1:
            message = (
                f"operation result {result_id.qualified_name!r} is produced "
                "more than once"
            )
        else:
            continue
        problems.append(
            _problem(
                "semantic_value_definition_duplicate",
                message,
                "values",
                result_id.qualified_name,
            )
        )
    return (
        {
            result_id: owners[0]
            for result_id, owners in grouped.items()
            if result_id not in ambiguous
        },
        frozenset(ambiguous),
    )


def _verify_uses(
    operations: tuple[SemanticOperation, ...],
    value_types: Mapping[ValueId, ValueType],
    ambiguous_value_ids: frozenset[ValueId],
    problems: list[Problem],
) -> None:
    for operation in operations:
        for input_name, use in operation.inputs:
            if use.value_id in value_types or use.value_id in ambiguous_value_ids:
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
                )
            )


def _verify_scalar_operations(
    operations: tuple[SemanticOperation, ...],
    definitions: Mapping[ValueId, ValueDef],
    value_types: Mapping[ValueId, ValueType],
    problems: list[Problem],
) -> None:
    for operation in operations:
        semantics = operation.contract
        if not isinstance(semantics, ScalarBinarySemantics):
            continue
        if not is_scalar_operator(semantics.operator):
            continue
        inputs = dict(operation.inputs)
        if set(inputs) != {"left", "right"}:
            problems.append(
                _problem(
                    "semantic_scalar_binary_shape_invalid",
                    "scalar binary operation requires left/right inputs",
                    "operations",
                    operation.id.qualified_name,
                )
            )
            continue
        left_id = inputs["left"].value_id
        right_id = inputs["right"].value_id
        left_type = value_types.get(left_id)
        right_type = value_types.get(right_id)
        if left_type is None or right_type is None:
            continue
        if not isinstance(left_type, Scalar) or not isinstance(right_type, Scalar):
            problems.append(
                _problem(
                    "semantic_scalar_binary_input_type_invalid",
                    "scalar binary operation inputs must be scalar-shaped",
                    "operations",
                    operation.id.qualified_name,
                )
            )
            continue
        left_definition = definitions.get(left_id)
        right_definition = definitions.get(right_id)
        left_source = None if left_definition is None else left_definition.source
        right_source = None if right_definition is None else right_definition.source
        try:
            expected_type = scalar_operator_result_type(
                left_type,
                right_type,
                semantics.operator,
                left_is_null_literal=(
                    isinstance(left_source, LiteralValueSource)
                    and left_source.value is None
                ),
                right_is_null_literal=(
                    isinstance(right_source, LiteralValueSource)
                    and right_source.value is None
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
        if operation.result_type != expected_type:
            problems.append(
                _problem(
                    "semantic_scalar_binary_result_type_mismatch",
                    f"scalar operation result type {operation.result_type!r} does not "
                    f"match inferred type {expected_type!r}",
                    "values",
                    operation.result_id.qualified_name,
                )
            )


def _verify_value_sources(
    definitions: tuple[ValueDef, ...],
    problems: list[Problem],
) -> None:
    for definition in definitions:
        source = definition.source
        value_type = definition.value_type
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
            continue
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
        tuple[ParameterLookupUse, ValueId],
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

        point_requirement = source.verified_plan.external_row_interface.point
        if point_requirement is None:
            continue
        for column in point_requirement.row_type.columns:
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


def _topological_operations(
    declared: tuple[SemanticOperation, ...],
    operation_results: Mapping[ValueId, SemanticOperation],
    problems: list[Problem],
) -> tuple[SemanticOperation, ...]:
    operations = {operation.id: operation for operation in declared}
    dependencies: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    dependents: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    for operation in declared:
        for _name, use in operation.inputs:
            producer_operation = operation_results.get(use.value_id)
            if producer_operation is None:
                continue
            producer = producer_operation.id
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
            )
        )
        return tuple(sorted(declared, key=lambda item: item.id.qualified_name))
    return tuple(ordered)


def _problem(
    code: str,
    message: str,
    root: str,
    *path: str,
) -> Problem:
    return problem(
        code=code,
        phase=ProblemPhase.AUTHORING,
        message=message,
        location=model_location(root, *path),
    )
