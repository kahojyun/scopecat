"""Close flattened module declarations into the backend-neutral semantic graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import cast

from scopecat.authoring._intents import (
    ComputeNodeInputValue,
    ModuleActionDecl,
    ModuleOperationDecl,
    StateEachIntent,
)
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    ParameterLookupContract,
    ParameterValueContract,
)
from scopecat.authoring._value_refs import (
    PointValueDependency,
    ScalarOperationOperand,
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_is_row_dependent,
    internal_value_ref_operation_id,
    internal_value_ref_scalar_operation,
    internal_value_ref_source_kind,
)
from scopecat.authoring.domain import LoweredDomainExecution
from scopecat.authoring.measurements import MeasurementTransform
from scopecat.authoring.values import ComputeDeclarationKey, ComputeFunction, RouteRef
from scopecat.compiler.frontend.value_binding import literal_data_expr
from scopecat.compiler.relations.analysis import (
    PlanReferenceKind,
    free_row_references,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    values,
)
from scopecat.compiler.relations.scalar_eval import eval_binary
from scopecat.compiler.relations.verification import (
    ParameterLookupSignature,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ActionId,
    DomainInputPortDef,
    DomainProgramId,
    DomainResultPortDef,
    ImplementationCatalog,
    ImplementationId,
    InstrumentActionEffect,
    LiteralValueSource,
    LocalPythonImplementation,
    MeasurementTransformId,
    OperationId,
    OperationOutputSource,
    PlanExpressionSource,
    RouteValueSource,
    RowArgumentDef,
    RowRegionId,
    SemanticDomainExecution,
    SemanticDomainProgram,
    SemanticGraphIR,
    SemanticMeasurementTransform,
    SemanticOperation,
    SourceAnchor,
    SourceMap,
    StateEachRegion,
    ValueDef,
    ValueId,
    ValueUse,
    operation_result_id,
    state_each_region_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    scalar_binary_operation_contract,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import literal_scalar_type
from scopecat.kernel.value_types import (
    AtomType,
    Bool,
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

type _PlanExpression = ScalarExpr | SeriesExpr | RelationExpr


@dataclass(frozen=True, slots=True)
class ScopedPythonImplementation:
    """A module implementation already associated with its scoped operation."""

    operation_id: OperationId
    declaration_key: ComputeDeclarationKey
    fn: ComputeFunction


@dataclass(frozen=True, slots=True)
class SemanticElaboration:
    graph: SemanticGraphIR
    implementations: ImplementationCatalog
    source_map: SourceMap


def elaborate_semantic_graph(
    operations: Sequence[ModuleOperationDecl],
    implementations: Sequence[ScopedPythonImplementation],
    *,
    measurement_transforms: Sequence[MeasurementTransform] = (),
    domain_executions: Sequence[LoweredDomainExecution] = (),
    actions: Sequence[ModuleActionDecl] = (),
    value_roots: Sequence[object] = (),
    state_regions: Sequence[StateEachIntent] = (),
    input_types: Mapping[str, ValueType] | None = None,
    point_dependencies: Sequence[PointValueDependency] = (),
    parameter_contracts: Sequence[ParameterContract] = (),
) -> SemanticElaboration:
    """Assemble one semantic graph and its sidecars from flattened module data."""

    builder = _SemanticGraphBuilder(
        implementations,
        input_types=input_types or {},
        point_dependencies=point_dependencies,
        parameter_contracts=parameter_contracts,
    )
    builder.declare_state_regions(state_regions)
    for transform in measurement_transforms:
        builder.add_measurement_transform(transform)
    for operation in operations:
        builder.add_authored_operation(operation)
    for execution in domain_executions:
        builder.add_domain_execution(execution)
    for action in actions:
        builder.add_action(action)
    for root in value_roots:
        if isinstance(root, ValueRef):
            builder.add_value_root(root)
    for intent in state_regions:
        builder.add_state_region(intent)
    return builder.finish()


def semantic_operation_id(symbol: SymbolId) -> OperationId:
    return OperationId(symbol)


def semantic_value_id(value: ValueRef) -> ValueId:
    """Return the graph identity deterministically assigned to a typed value."""

    operation_id = internal_value_ref_operation_id(value)
    if operation_id is not None:
        return operation_result_id(semantic_operation_id(operation_id))
    if internal_value_ref_scalar_operation(value) is not None:
        return operation_result_id(_scalar_operation_id(value))
    declaration_key = value.declaration_key
    scope = value.declaration_scope
    return ValueId(
        SymbolId(
            scope=(*scope, "values"),
            local_id=f"v_{declaration_key.value.hex}",
        )
    )


def _scalar_operation_id(value: ValueRef) -> OperationId:
    declaration_key = value.declaration_key
    scope = value.declaration_scope
    return OperationId(
        SymbolId(
            scope=(*scope, "scalar_operations"),
            local_id=f"op_{declaration_key.value.hex}",
        )
    )


class _SemanticGraphBuilder:
    def __init__(
        self,
        implementations: Sequence[ScopedPythonImplementation],
        *,
        input_types: Mapping[str, ValueType],
        point_dependencies: Sequence[PointValueDependency],
        parameter_contracts: Sequence[ParameterContract],
    ) -> None:
        self._module_implementations = {
            implementation.operation_id: implementation
            for implementation in implementations
        }
        if len(self._module_implementations) != len(implementations):
            msg = "scoped module implementations must have unique operation ids"
            raise ValueError(msg)
        self._definitions: dict[ValueId, ValueDef] = {}
        self._operations: dict[OperationId, SemanticOperation] = {}
        self._measurement_transforms: list[SemanticMeasurementTransform] = []
        self._domain_executions: list[SemanticDomainExecution] = []
        self._actions: list[InstrumentActionEffect] = []
        self._implementations: dict[OperationId, LocalPythonImplementation] = {}
        self._operation_sources: dict[OperationId, SourceAnchor] = {}
        self._action_sources: dict[ActionId, SourceAnchor] = {}
        self._value_sources: dict[ValueId, SourceAnchor] = {}
        self._row_regions: list[StateEachRegion] = []
        self._row_region_sources: dict[RowRegionId, SourceAnchor] = {}
        self._region_by_row_argument: dict[RowScopeId, RowRegionId] = {}
        self._region_rows: dict[RowRegionId, tuple[RowScopeId, RowType]] = {}
        self._input_types = dict(input_types)
        self._parameter_types = {
            contract.parameter_id: contract.value_type
            for contract in parameter_contracts
            if isinstance(contract, ParameterValueContract)
        }
        self._parameter_lookups = tuple(
            ParameterLookupSignature(
                table_id=contract.parameter_id,
                key_input_types=contract.key_types,
                column_id=contract.column_id,
                result_type=contract.value_type,
            )
            for contract in parameter_contracts
            if isinstance(contract, ParameterLookupContract)
        )
        point_columns = tuple(
            TableColumn(dependency.id, dependency.value_type)
            for dependency in point_dependencies
        )
        self._point_row = RowType(point_columns) if point_columns else None

    def declare_state_regions(self, intents: Sequence[StateEachIntent]) -> None:
        """Register binder ownership before any value definition is elaborated."""

        for intent in intents:
            region_id = state_each_region_id(intent.row_scope_id)
            self._region_by_row_argument.setdefault(intent.row_scope_id, region_id)
            relation_type = intent.relation.value_type
            if not isinstance(relation_type, Table):
                msg = "state row region relation must be table-shaped"
                raise TypeError(msg)
            self._region_rows.setdefault(
                region_id,
                (intent.row_scope_id, RowType.from_table(relation_type)),
            )

    def add_authored_operation(self, declaration: ModuleOperationDecl) -> None:
        operation_id = semantic_operation_id(declaration.operation_id)
        output_id = operation_result_id(operation_id)
        inputs = tuple(
            (
                name,
                ValueUse(
                    self._add_compute_input(
                        value,
                        operation_id=operation_id,
                        declaration_id=declaration.declaration_key.value.hex,
                        input_name=name,
                    )
                ),
            )
            for name, value in declaration.inputs
        )
        operation = SemanticOperation(
            id=operation_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            inputs=inputs,
            outputs=(("result", output_id),),
        )
        self._add_operation(operation)
        self._add_definition(
            ValueDef(
                id=output_id,
                value_type=declaration.output_type,
                source=OperationOutputSource(operation_id),
            )
        )
        implementation = self._module_implementations.get(operation_id)
        if implementation is not None:
            self._implementations[operation_id] = LocalPythonImplementation(
                id=ImplementationId(
                    "python:"
                    f"{declaration.declaration_key.value.hex}:"
                    f"{operation_id.qualified_name}"
                ),
                operation_id=operation_id,
                operation_contract=operation.contract,
                kernel=implementation.fn,
            )
        anchor = SourceAnchor(
            kind="module_operation",
            declaration_id=declaration.declaration_key.value.hex,
            composition_scope=declaration.scope,
        )
        self._operation_sources[operation_id] = anchor
        self._value_sources[output_id] = anchor

    def add_domain_execution(self, execution: LoweredDomainExecution) -> None:
        program = execution.program
        semantic_program = SemanticDomainProgram(
            id=DomainProgramId(program.symbol_id),
            dialect_id=program.dialect_id,
            dialect_version=program.dialect_version,
            body=program.body,
            input_ports=tuple(
                DomainInputPortDef(port.id, port.value_type)
                for port in program.input_ports
            ),
            result_ports=tuple(
                DomainResultPortDef(port.id, port.contract)
                for port in program.result_ports
            ),
        )
        operation_id = OperationId(
            SymbolId(scope=("domain_execution",), local_id=execution.id)
        )
        self._domain_executions.append(
            SemanticDomainExecution(
                id=execution.id,
                program=semantic_program,
                inputs=tuple(
                    (
                        name,
                        ValueUse(
                            self._add_compute_input(
                                value,
                                operation_id=operation_id,
                                declaration_id="domain",
                                input_name=name,
                            )
                        ),
                    )
                    for name, value in execution.input_bindings
                ),
                results=execution.result_bindings,
            )
        )

    def add_measurement_transform(
        self,
        declaration: MeasurementTransform,
    ) -> None:
        self._measurement_transforms.append(
            SemanticMeasurementTransform(
                id=MeasurementTransformId(declaration.symbol_id),
                semantic=declaration.semantic,
                inputs=declaration.input_bindings,
                outputs=declaration.output_bindings,
            )
        )

    def add_action(self, declaration: ModuleActionDecl) -> None:
        action_id = ActionId(declaration.action_id)
        fields = tuple(
            (
                name,
                ValueUse(
                    self._add_action_value(
                        value,
                        action_id=action_id,
                        field_name=name,
                    )
                ),
            )
            for name, value in declaration.fields
        )
        self._actions.append(
            InstrumentActionEffect(
                id=action_id,
                resource_port_id=declaration.resource_port_id,
                capability_id=declaration.capability_id,
                fields=fields,
            )
        )
        self._action_sources[action_id] = SourceAnchor(
            kind="instrument_action",
            declaration_id=action_id.local_id,
            composition_scope=declaration.scope,
        )

    def add_value_root(self, value: ValueRef) -> ValueId:
        return self._add_value(value, requested_region_id=None)

    def add_state_region(self, intent: StateEachIntent) -> None:
        region_id = state_each_region_id(intent.row_scope_id)
        relation_id = self._add_value(
            intent.relation,
            requested_region_id=None,
        )
        composition_scope = intent.row_scope_id.symbol.scope
        resource_id = (
            self._add_state_body_value(
                intent.resource,
                region_id=region_id,
                role="resource",
                composition_scope=composition_scope,
            )
            if intent.resource is not None
            else None
        )
        value_id = self._add_state_body_value(
            intent.value,
            region_id=region_id,
            role="value",
            composition_scope=composition_scope,
        )
        route_ids = tuple(
            self._add_state_body_value(
                route,
                region_id=region_id,
                role=f"route_{index}",
                composition_scope=composition_scope,
            )
            for index, route in enumerate(intent.route_entities)
        )
        relation_type = intent.relation.value_type
        if not isinstance(relation_type, Table):
            msg = "state row region relation must be table-shaped"
            raise TypeError(msg)
        region = StateEachRegion(
            id=region_id,
            row_argument=RowArgumentDef(intent.row_scope_id, relation_type),
            relation=ValueUse(relation_id),
            resource=(ValueUse(resource_id) if resource_id is not None else None),
            resource_port=intent.resource_port,
            capability_id=intent.capability_id,
            field_path=intent.field_path,
            value=ValueUse(value_id),
            route_entities=tuple(ValueUse(value_id) for value_id in route_ids),
        )
        self._row_regions.append(region)
        self._row_region_sources[region_id] = SourceAnchor(
            kind="state_each",
            declaration_id=intent.row_scope_id.symbol.local_id,
            composition_scope=intent.row_scope_id.symbol.scope,
        )

    def finish(self) -> SemanticElaboration:
        graph = SemanticGraphIR(
            value_defs=tuple(self._definitions.values()),
            operations=tuple(self._operations.values()),
            measurement_transforms=tuple(self._measurement_transforms),
            domain_executions=tuple(self._domain_executions),
            actions=tuple(self._actions),
            row_regions=tuple(self._row_regions),
        )
        catalog = ImplementationCatalog(
            local_python=tuple(self._implementations.values()),
        )
        source_map = SourceMap(
            operation_sources=tuple(self._operation_sources.items()),
            value_sources=tuple(self._value_sources.items()),
            action_sources=tuple(self._action_sources.items()),
            row_region_sources=tuple(self._row_region_sources.items()),
        )
        return SemanticElaboration(
            graph=graph,
            implementations=catalog,
            source_map=source_map,
        )

    def _add_action_value(
        self,
        value: object,
        *,
        action_id: ActionId,
        field_name: str,
    ) -> ValueId:
        if isinstance(value, ValueRef):
            return self._add_value(value, requested_region_id=None)
        value_id = ValueId(
            SymbolId(
                scope=(*action_id.scope, action_id.local_id, "fields"),
                local_id=field_name,
            )
        )
        self._add_literal(
            value_id,
            value,
            anchor=SourceAnchor(
                kind="action_field_literal",
                declaration_id=f"{action_id.local_id}:{field_name}",
                composition_scope=action_id.scope,
            ),
        )
        return value_id

    def _add_compute_input(
        self,
        value: ComputeNodeInputValue,
        *,
        operation_id: OperationId,
        declaration_id: str,
        input_name: str,
    ) -> ValueId:
        if isinstance(value, ValueRef):
            return self._add_value(value, requested_region_id=None)
        input_id = ValueId(
            SymbolId(
                scope=(
                    *operation_id.scope,
                    operation_id.local_id,
                    "inputs",
                ),
                local_id=input_name,
            )
        )
        if isinstance(value, RouteRef):
            self._add_definition(
                ValueDef(
                    id=input_id,
                    value_type=value.value_type,
                    source=RouteValueSource(
                        port_id=value.port_id,
                    ),
                )
            )
            self._value_sources[input_id] = SourceAnchor(
                kind="operation_route_input",
                declaration_id=f"{declaration_id}:{input_name}",
                composition_scope=operation_id.scope,
            )
            return input_id
        self._add_literal(
            input_id,
            value,
            anchor=SourceAnchor(
                kind="operation_input_literal",
                declaration_id=f"{declaration_id}:{input_name}",
                composition_scope=operation_id.scope,
            ),
        )
        return input_id

    def _add_state_body_value(
        self,
        value: object,
        *,
        region_id: RowRegionId,
        role: str,
        composition_scope: tuple[str, ...],
    ) -> ValueId:
        if isinstance(value, ValueRef):
            return self._add_value(
                value,
                requested_region_id=region_id,
            )
        value_id = ValueId(
            SymbolId(
                scope=(
                    *region_id.scope,
                    region_id.local_id,
                    "body",
                ),
                local_id=role,
            )
        )
        anchor = SourceAnchor(
            kind="state_literal",
            declaration_id=f"{region_id.local_id}:{role}",
            composition_scope=composition_scope,
        )
        if isinstance(value, tuple):
            items = cast("tuple[object, ...]", value)
            expression = values(items)
            self._add_definition(
                ValueDef(
                    id=value_id,
                    value_type=_literal_series_type(items),
                    source=self._plan_source(
                        expression,
                        expected_type=_literal_series_type(items),
                        owner_region_id=None,
                    ),
                )
            )
            self._value_sources[value_id] = anchor
            return value_id
        self._add_literal(value_id, value, anchor=anchor)
        return value_id

    def _add_value(
        self,
        value: ValueRef,
        *,
        requested_region_id: RowRegionId | None,
    ) -> ValueId:
        value_id = semantic_value_id(value)
        scalar_operation = internal_value_ref_scalar_operation(value)
        if scalar_operation is not None:
            return self._add_scalar_operation(
                value,
                requested_region_id=requested_region_id,
            )
        if value_id in self._definitions:
            return value_id
        operation_id = internal_value_ref_operation_id(value)
        if operation_id is not None:
            # Its definition is owned by the corresponding authored operation.
            return value_id
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            msg = "non-compute semantic values must lower to a plan expression"
            raise TypeError(msg)
        owner_region_id = self._expression_owner(
            lowered,
            requested_region_id=requested_region_id,
        )
        self._add_definition(
            ValueDef(
                id=value_id,
                value_type=value.value_type,
                source=self._plan_source(
                    lowered,
                    expected_type=value.value_type,
                    owner_region_id=owner_region_id,
                ),
                owner_region_id=owner_region_id,
            )
        )
        self._value_sources[value_id] = SourceAnchor(
            kind=internal_value_ref_source_kind(value),
            declaration_id=value.declaration_key.value.hex,
            composition_scope=value.declaration_scope,
        )
        return value_id

    def _add_scalar_operation(
        self,
        value: ValueRef,
        *,
        requested_region_id: RowRegionId | None,
    ) -> ValueId:
        operation_id = _scalar_operation_id(value)
        output_id = operation_result_id(operation_id)
        scalar_operation = internal_value_ref_scalar_operation(value)
        if scalar_operation is None:
            raise AssertionError("scalar operation value lost its operation")
        declaration_id = value.declaration_key.value.hex
        left_id = self._add_scalar_operand(
            scalar_operation.left,
            operation_id=operation_id,
            declaration_id=declaration_id,
            input_name="left",
            requested_region_id=requested_region_id,
        )
        right_id = self._add_scalar_operand(
            scalar_operation.right,
            operation_id=operation_id,
            declaration_id=declaration_id,
            input_name="right",
            requested_region_id=requested_region_id,
        )
        if operation_id in self._operations:
            return output_id
        operand_owners = {
            definition.owner_region_id
            for value_id in (left_id, right_id)
            if (definition := self._definitions.get(value_id)) is not None
            and definition.owner_region_id is not None
        }
        owner_region_id = (
            next(iter(operand_owners))
            if len(operand_owners) == 1
            else requested_region_id
            if internal_value_ref_is_row_dependent(value)
            else None
        )
        operation_contract = scalar_binary_operation_contract(scalar_operation.operator)
        self._add_operation(
            SemanticOperation(
                id=operation_id,
                contract=operation_contract,
                inputs=(
                    ("left", ValueUse(left_id)),
                    ("right", ValueUse(right_id)),
                ),
                outputs=(("result", output_id),),
                owner_region_id=owner_region_id,
            )
        )
        self._add_definition(
            ValueDef(
                id=output_id,
                value_type=value.value_type,
                source=OperationOutputSource(operation_id),
                owner_region_id=owner_region_id,
            )
        )
        self._implementations[operation_id] = LocalPythonImplementation(
            id=ImplementationId(f"core.scalar:{operation_id.qualified_name}"),
            operation_id=operation_id,
            operation_contract=operation_contract,
            kernel=partial(eval_binary, scalar_operation.operator),
        )
        anchor = SourceAnchor(
            kind="scalar_operation",
            declaration_id=declaration_id,
            composition_scope=value.declaration_scope,
        )
        self._operation_sources[operation_id] = anchor
        self._value_sources[output_id] = anchor
        return output_id

    def _add_scalar_operand(
        self,
        operand: ScalarOperationOperand,
        *,
        operation_id: OperationId,
        declaration_id: str,
        input_name: str,
        requested_region_id: RowRegionId | None,
    ) -> ValueId:
        if isinstance(operand, ValueRef):
            return self._add_value(
                operand,
                requested_region_id=requested_region_id,
            )
        value_id = ValueId(
            SymbolId(
                scope=(
                    *operation_id.scope,
                    operation_id.local_id,
                    "inputs",
                ),
                local_id=input_name,
            )
        )
        self._add_literal(
            value_id,
            operand,
            anchor=SourceAnchor(
                kind="scalar_literal",
                declaration_id=f"{declaration_id}:{input_name}",
                composition_scope=operation_id.scope,
            ),
        )
        return value_id

    def _add_literal(
        self,
        value_id: ValueId,
        value: object,
        *,
        anchor: SourceAnchor,
    ) -> None:
        # Constructing the relation literal here also validates that the value
        # belongs to the same closed scalar domain used by local plan lowering.
        literal_data_expr(value)
        self._add_definition(
            ValueDef(
                id=value_id,
                value_type=literal_scalar_type(value),
                source=LiteralValueSource(value),
            )
        )
        self._value_sources[value_id] = anchor

    def _add_definition(self, definition: ValueDef) -> None:
        existing = self._definitions.get(definition.id)
        if existing is not None and existing != definition:
            msg = f"semantic value {definition.id.qualified_name!r} is redefined"
            raise ValueError(msg)
        self._definitions[definition.id] = definition

    def _plan_source(
        self,
        expression: _PlanExpression,
        *,
        expected_type: ValueType,
        owner_region_id: RowRegionId | None,
    ) -> PlanExpressionSource:
        row_entry = (
            self._region_rows.get(owner_region_id)
            if owner_region_id is not None
            else None
        )
        row_scope_id, row_type = row_entry if row_entry is not None else (None, None)
        bindings = RelationTypeBindings(
            inputs=self._input_types,
            parameters=self._parameter_types,
            parameter_lookups=self._parameter_lookups,
            point_row=self._point_row,
            current_row=row_type,
            row_arguments=(
                {row_scope_id: row_type}
                if row_scope_id is not None and row_type is not None
                else {}
            ),
        )
        try:
            verified = verify_relation_plan(
                expression,
                bindings=bindings,
                expected_type=expected_type,
            )
        except RelationPlanVerificationError as error:
            raise CheckFailed(
                [
                    blocking_problem(
                        code=f"relation_plan_{error.code}",
                        category=ProblemCategory.INVALID_INPUT,
                        phase=ProblemPhase.AUTHORING,
                        message=error.reason,
                        location=model_location(
                            "semantic_graph",
                            "values",
                            *error.path,
                        ),
                        details={
                            "relation_code": error.code,
                            "plan_path": list(error.path),
                        },
                    )
                ]
            ) from error
        return PlanExpressionSource(verified)

    def _add_operation(self, operation: SemanticOperation) -> None:
        existing = self._operations.get(operation.id)
        if existing is not None and existing != operation:
            msg = f"semantic operation {operation.id.qualified_name!r} is redefined"
            raise ValueError(msg)
        self._operations[operation.id] = operation

    def _expression_owner(
        self,
        expression: _PlanExpression,
        *,
        requested_region_id: RowRegionId | None,
    ) -> RowRegionId | None:
        free = free_row_references(expression)
        if not free.references:
            return None
        declared_owners: set[RowRegionId] = set()
        all_nominal_uses_are_declared = True
        for reference in free.references:
            if (
                reference.kind is not PlanReferenceKind.CURRENT_COLUMN
                or reference.row_scope_id is None
            ):
                all_nominal_uses_are_declared = False
                continue
            owner = self._region_by_row_argument.get(reference.row_scope_id)
            if owner is None:
                all_nominal_uses_are_declared = False
            else:
                declared_owners.add(owner)
        if all_nominal_uses_are_declared and len(declared_owners) == 1:
            return next(iter(declared_owners))
        return requested_region_id


def _literal_series_type(items: tuple[object, ...]) -> Series:
    if not items:
        return Series(Scalar(Entity()), min_length=0, max_length=0)
    item_types = tuple(literal_scalar_type(item) for item in items)
    atoms = tuple(item_type.atom for item_type in item_types)
    nullable = any(item_type.nullable for item_type in item_types)
    selected_atom: AtomType
    if all(isinstance(atom, Bool) for atom in atoms):
        selected_atom = Bool()
    elif all(isinstance(atom, Int) for atom in atoms):
        selected_atom = Int()
    elif all(isinstance(atom, Int | Float) for atom in atoms):
        selected_atom = Float()
    elif all(isinstance(atom, String) for atom in atoms):
        strings = tuple(atom for atom in atoms if isinstance(atom, String))
        selected_atom = String(
            min_length=min(atom.min_length for atom in strings),
            max_length=(
                None
                if any(atom.max_length is None for atom in strings)
                else max(
                    atom.max_length for atom in strings if atom.max_length is not None
                )
            ),
        )
    elif all(isinstance(atom, Quantity) for atom in atoms):
        units = {atom.unit for atom in atoms if isinstance(atom, Quantity)}
        selected_atom = (
            Quantity(unit=next(iter(units))) if len(units) == 1 else Quantity()
        )
    elif all(isinstance(atom, Entity | String) for atom in atoms):
        kinds = {atom.entity_kind for atom in atoms if isinstance(atom, Entity)}
        selected_atom = Entity(
            entity_kind=next(iter(kinds)) if len(kinds) == 1 else None
        )
    elif all(isinstance(atom, Payload) for atom in atoms):
        schemas = {atom.schema_id for atom in atoms if isinstance(atom, Payload)}
        if len(schemas) != 1:
            msg = "state route series cannot mix payload schemas"
            raise TypeError(msg)
        selected_atom = Payload(next(iter(schemas)))
    else:
        msg = "state route series contains incompatible scalar values"
        raise TypeError(msg)
    return Series(
        Scalar(selected_atom, nullable=nullable),
        min_length=len(items),
        max_length=len(items),
    )
