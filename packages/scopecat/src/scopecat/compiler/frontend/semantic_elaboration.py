"""Close flattened module declarations into logical program fields."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from scopecat.compiler.frontend.value_binding import input_cell
from scopecat.graph.relations.model import (
    ScalarExpr,
)
from scopecat.graph.values import (
    ComputeResultRef,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import literal_scalar_type
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
)
from scopecat.program.domain import LoweredDomainExecution
from scopecat.program.identities import ComputeDeclarationKey
from scopecat.program.logical import (
    AcquireEffect,
    ImplementationId,
    LiteralValueSource,
    LocalPythonImplementation,
    LogicalComputeNode,
    LogicalDomainExecution,
    LogicalEnsureState,
    LogicalInvocation,
    LogicalInvocationArgument,
    LogicalMeasurementPostprocessor,
    LogicalProgram,
    LogicalStateAssignment,
    MeasurementPostprocessorId,
    PlanExpressionSource,
    ValueDef,
    ValueSource,
)
from scopecat.program.measurements import MeasurementPostprocessor
from scopecat.program.operations import (
    ComputeNodeInputValue,
    ModuleOperationDecl,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_operation_id,
)
from scopecat.program.values import ComputeFunction


@dataclass(frozen=True, slots=True)
class ScopedPythonImplementation:
    """A module implementation already associated with its scoped operation."""

    operation_id: OperationId
    declaration_key: ComputeDeclarationKey
    fn: ComputeFunction


def close_logical_program(
    program: LogicalProgram,
    operations: Sequence[ModuleOperationDecl],
    implementations: Sequence[ScopedPythonImplementation],
    *,
    measurement_postprocessors: Sequence[MeasurementPostprocessor] = (),
    effects: Sequence[
        BindingIntent
        | EnsureStateIntent
        | InvocationIntent
        | LoweredDomainExecution
        | AcquireEffect
    ] = (),
    final_state: EnsureStateIntent | None = None,
    value_roots: Sequence[object] = (),
) -> LogicalProgram:
    """Close flattened definition data directly into its logical program."""

    builder = _LogicalSemanticsBuilder(implementations)
    for postprocessor in measurement_postprocessors:
        builder.add_measurement_postprocessor(postprocessor)
    for operation in operations:
        builder.add_authored_operation(operation)
    semantic_effects = tuple(
        builder.add_effect(effect, effect_index=effect_index)
        for effect_index, effect in enumerate(effects)
    )
    for root in value_roots:
        if isinstance(root, ValueRef):
            builder.add_value_root(root)
    return builder.finish(
        program,
        effects=semantic_effects,
        final_state=(
            None
            if final_state is None
            else builder.add_ensure_state(final_state, scope=("final_state",))
        ),
    )


def logical_compute_node_id(symbol: SymbolId) -> OperationId:
    return OperationId(symbol)


def logical_value_id(value: ValueRef) -> ValueId:
    """Return the graph identity deterministically assigned to a typed value."""

    operation_id = internal_value_ref_operation_id(value)
    if operation_id is not None:
        return operation_result_id(logical_compute_node_id(operation_id))
    declaration_key = value.declaration_key
    scope = value.declaration_scope
    return ValueId(
        SymbolId(
            scope=(*scope, "values"),
            local_id=f"v_{declaration_key.value.hex}",
        )
    )


class _LogicalSemanticsBuilder:
    def __init__(
        self,
        implementations: Sequence[ScopedPythonImplementation],
    ) -> None:
        self._module_implementations = {
            implementation.operation_id: implementation
            for implementation in implementations
        }
        self._definitions: dict[ValueId, ValueDef] = {}
        self._compute_nodes: dict[OperationId, LogicalComputeNode] = {}
        self._measurement_postprocessors: list[LogicalMeasurementPostprocessor] = []
        self._implementations: dict[OperationId, LocalPythonImplementation] = {}

    def add_authored_operation(self, declaration: ModuleOperationDecl) -> None:
        operation_id = logical_compute_node_id(declaration.operation_id)
        output_id = operation_result_id(operation_id)
        inputs = tuple(
            (
                name,
                self._add_compute_input(
                    value,
                    operation_id=operation_id,
                    input_name=name,
                ),
            )
            for name, value in declaration.inputs
        )
        operation = LogicalComputeNode(
            id=operation_id,
            inputs=inputs,
            result_id=output_id,
            result_type=declaration.output_type,
        )
        self._add_compute_node(operation)
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
    ) -> LogicalDomainExecution:
        program = execution.program
        operation_id = OperationId(
            SymbolId(scope=("domain_execution",), local_id=execution.id)
        )
        return LogicalDomainExecution(
            id=execution.id,
            program=program,
            inputs=tuple(
                (
                    name,
                    self._add_compute_input(
                        value,
                        operation_id=operation_id,
                        input_name=name,
                    ),
                )
                for name, value in execution.input_bindings
            ),
            compiler_inputs=tuple(
                (
                    name,
                    self._add_compute_input(
                        value,
                        operation_id=operation_id,
                        input_name=name,
                    ),
                )
                for name, value in execution.compiler_input_bindings
            ),
            results=execution.result_bindings,
        )

    def add_effect(
        self,
        effect: (
            BindingIntent
            | EnsureStateIntent
            | InvocationIntent
            | LoweredDomainExecution
            | AcquireEffect
        ),
        *,
        effect_index: int,
    ) -> (
        LogicalStateAssignment
        | LogicalEnsureState
        | LogicalInvocation
        | LogicalDomainExecution
        | AcquireEffect
    ):
        scope = ("effects", str(effect_index))
        if isinstance(effect, BindingIntent):
            return self._add_state_assignment(effect, scope=scope)
        if isinstance(effect, EnsureStateIntent):
            return self.add_ensure_state(effect, scope=scope)
        if isinstance(effect, InvocationIntent):
            return LogicalInvocation(
                id=effect.id,
                port_id=effect.port_id,
                interface_id=effect.interface_id,
                component_path=effect.component_path,
                operation_id=effect.operation_id,
                arguments=tuple(
                    LogicalInvocationArgument(
                        id=argument.id,
                        value_id=self._add_effect_value(
                            argument.value,
                            scope=(*scope, "invocation", effect.id, "arguments"),
                            local_id=argument.id,
                        ),
                    )
                    for argument in effect.arguments
                ),
                scope=effect.scope,
            )
        if isinstance(effect, LoweredDomainExecution):
            return self.add_domain_execution(effect)
        return effect

    def add_ensure_state(
        self,
        effect: EnsureStateIntent,
        *,
        scope: tuple[str, ...],
    ) -> LogicalEnsureState:
        return LogicalEnsureState(
            tuple(
                self._add_state_assignment(
                    assignment,
                    scope=(*scope, "assignments", str(index)),
                )
                for index, assignment in enumerate(effect.assignments)
            )
        )

    def _add_state_assignment(
        self,
        assignment: BindingIntent,
        *,
        scope: tuple[str, ...],
    ) -> LogicalStateAssignment:
        return LogicalStateAssignment(
            port_id=assignment.port_id,
            interface_id=assignment.interface_id,
            component_path=assignment.component_path,
            property_id=assignment.property_id,
            value_id=self._add_effect_value(
                assignment.value,
                scope=scope,
                local_id="value",
            ),
        )

    def _add_effect_value(
        self,
        value: object,
        *,
        scope: tuple[str, ...],
        local_id: str,
    ) -> ValueId:
        if isinstance(value, ValueRef):
            return self._add_value(value)
        value_id = ValueId(SymbolId(scope=scope, local_id=local_id))
        self._add_literal(value_id, value)
        return value_id

    def add_measurement_postprocessor(
        self,
        declaration: MeasurementPostprocessor,
    ) -> None:
        self._measurement_postprocessors.append(
            LogicalMeasurementPostprocessor(
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
        program: LogicalProgram,
        *,
        effects: tuple[
            LogicalStateAssignment
            | LogicalEnsureState
            | LogicalInvocation
            | LogicalDomainExecution
            | AcquireEffect,
            ...,
        ],
        final_state: LogicalEnsureState | None,
    ) -> LogicalProgram:
        return replace(
            program,
            value_defs=tuple(self._definitions.values()),
            compute_nodes=tuple(self._compute_nodes.values()),
            measurement_postprocessors=tuple(self._measurement_postprocessors),
            implementations=MappingProxyType(dict(self._implementations)),
            effects=effects,
            final_state=final_state,
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
        value_id = logical_value_id(value)
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
        source: ValueSource
        if isinstance(lowered, ScalarExpr):
            source = PlanExpressionSource(lowered)
        else:
            source = lowered
        self._add_definition(
            ValueDef(
                id=value_id,
                value_type=value.value_type,
                source=source,
            )
        )
        return value_id

    def _add_literal(
        self,
        value_id: ValueId,
        value: object,
    ) -> None:
        input_cell(value)
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

    def _add_compute_node(self, operation: LogicalComputeNode) -> None:
        existing = self._compute_nodes.get(operation.id)
        if existing is not None and existing != operation:
            msg = f"semantic operation {operation.id.qualified_name!r} is redefined"
            raise ValueError(msg)
        self._compute_nodes[operation.id] = operation
