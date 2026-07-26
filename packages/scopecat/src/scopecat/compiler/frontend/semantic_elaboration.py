"""Close flattened module declarations into the backend-neutral semantic graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from scopecat.authoring._binding_intents import ExperimentBindingIntent
from scopecat.authoring._identities import ComputeDeclarationKey
from scopecat.authoring._intents import (
    ComputeNodeInputValue,
    ModuleOperationDecl,
)
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    ParameterValueContract,
)
from scopecat.authoring._value_refs import (
    PointValueDependency,
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_operation_id,
)
from scopecat.authoring.domain import LoweredDomainExecution
from scopecat.authoring.measurements import MeasurementPostprocessor
from scopecat.authoring.values import ComputeFunction
from scopecat.compiler.frontend.value_binding import literal_data_expr
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    ImplementationId,
    LiteralValueSource,
    LocalPythonImplementation,
    MeasurementPostprocessorId,
    PlanExpressionSource,
    SemanticDomainExecution,
    SemanticGraphIR,
    SemanticMeasurementPostprocessor,
    SemanticOperation,
    ValueDef,
    ValueUse,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.graph.relations.model import (
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.graph.values import (
    ComputeResultRef,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import literal_scalar_type
from scopecat.kernel.value_types import TableColumn, ValueType

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
    implementations: Mapping[OperationId, LocalPythonImplementation]
    effects: tuple[
        ExperimentBindingIntent | SemanticDomainExecution | AcquireEffect,
        ...,
    ]


def elaborate_semantic_graph(
    operations: Sequence[ModuleOperationDecl],
    implementations: Sequence[ScopedPythonImplementation],
    *,
    measurement_postprocessors: Sequence[MeasurementPostprocessor] = (),
    effects: Sequence[
        ExperimentBindingIntent | LoweredDomainExecution | AcquireEffect
    ] = (),
    value_roots: Sequence[object] = (),
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
    for postprocessor in measurement_postprocessors:
        builder.add_measurement_postprocessor(postprocessor)
    for operation in operations:
        builder.add_authored_operation(operation)
    semantic_effects = tuple(
        builder.add_domain_execution(effect)
        if isinstance(effect, LoweredDomainExecution)
        else effect
        for effect in effects
    )
    for root in value_roots:
        if isinstance(root, ValueRef):
            builder.add_value_root(root)
    return builder.finish(effects=semantic_effects)


def semantic_operation_id(symbol: SymbolId) -> OperationId:
    return OperationId(symbol)


def semantic_value_id(value: ValueRef) -> ValueId:
    """Return the graph identity deterministically assigned to a typed value."""

    operation_id = internal_value_ref_operation_id(value)
    if operation_id is not None:
        return operation_result_id(semantic_operation_id(operation_id))
    declaration_key = value.declaration_key
    scope = value.declaration_scope
    return ValueId(
        SymbolId(
            scope=(*scope, "values"),
            local_id=f"v_{declaration_key.value.hex}",
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
        self._definitions: dict[ValueId, ValueDef] = {}
        self._operations: dict[OperationId, SemanticOperation] = {}
        self._measurement_postprocessors: list[SemanticMeasurementPostprocessor] = []
        self._implementations: dict[OperationId, LocalPythonImplementation] = {}
        self._input_types = dict(input_types)
        self._parameter_types = {
            contract.parameter_id: contract.value_type
            for contract in parameter_contracts
            if isinstance(contract, ParameterValueContract)
        }
        point_columns = tuple(
            TableColumn(dependency.id, dependency.value_type)
            for dependency in point_dependencies
        )
        self._point_row = RowType(point_columns) if point_columns else None

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
            result_id=output_id,
            result_type=declaration.output_type,
        )
        self._add_operation(operation)
        implementation = self._module_implementations.get(operation_id)
        if implementation is not None:
            self._implementations[operation_id] = LocalPythonImplementation(
                id=ImplementationId(
                    "python:"
                    f"{declaration.declaration_key.value.hex}:"
                    f"{operation_id.qualified_name}"
                ),
                kernel=implementation.fn,
            )

    def add_domain_execution(
        self,
        execution: LoweredDomainExecution,
    ) -> SemanticDomainExecution:
        program = execution.program
        operation_id = OperationId(
            SymbolId(scope=("domain_execution",), local_id=execution.id)
        )
        return SemanticDomainExecution(
            id=execution.id,
            program=program,
            inputs=tuple(
                (
                    name,
                    ValueUse(
                        self._add_compute_input(
                            value,
                            operation_id=operation_id,
                            input_name=name,
                        )
                    ),
                )
                for name, value in execution.input_bindings
            ),
            compiler_inputs=tuple(
                (
                    name,
                    ValueUse(
                        self._add_compute_input(
                            value,
                            operation_id=operation_id,
                            input_name=name,
                        )
                    ),
                )
                for name, value in execution.compiler_input_bindings
            ),
            results=execution.result_bindings,
            resources=execution.resource_bindings,
        )

    def add_measurement_postprocessor(
        self,
        declaration: MeasurementPostprocessor,
    ) -> None:
        self._measurement_postprocessors.append(
            SemanticMeasurementPostprocessor(
                id=MeasurementPostprocessorId(declaration.symbol_id),
                input=declaration.input_binding,
                outputs=declaration.output_bindings,
                kernel=declaration.kernel,
            )
        )

    def add_value_root(self, value: ValueRef) -> ValueId:
        return self._add_value(value)

    def finish(
        self,
        *,
        effects: tuple[
            ExperimentBindingIntent | SemanticDomainExecution | AcquireEffect,
            ...,
        ],
    ) -> SemanticElaboration:
        graph = SemanticGraphIR(
            value_defs=tuple(self._definitions.values()),
            operations=tuple(self._operations.values()),
            measurement_postprocessors=tuple(self._measurement_postprocessors),
        )
        return SemanticElaboration(
            graph=graph,
            implementations=MappingProxyType(dict(self._implementations)),
            effects=effects,
        )

    def _add_compute_input(
        self,
        value: ComputeNodeInputValue,
        *,
        operation_id: OperationId,
        input_name: str,
    ) -> ValueId:
        if isinstance(value, ValueRef):
            return self._add_value(value)
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
        self._add_literal(
            input_id,
            value,
        )
        return input_id

    def _add_value(self, value: ValueRef) -> ValueId:
        value_id = semantic_value_id(value)
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
        self._add_definition(
            ValueDef(
                id=value_id,
                value_type=value.value_type,
                source=self._plan_source(
                    lowered,
                    expected_type=value.value_type,
                ),
            )
        )
        return value_id

    def _add_literal(
        self,
        value_id: ValueId,
        value: object,
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
    ) -> PlanExpressionSource:
        bindings = RelationTypeBindings(
            inputs=self._input_types,
            parameters=self._parameter_types,
            point_row=self._point_row,
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
                    problem(
                        code=f"relation_plan_{error.code}",
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
