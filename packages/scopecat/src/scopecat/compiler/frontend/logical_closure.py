"""Close flattened module declarations into logical program fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from scopecat.compiler.frontend.value_binding import input_cell
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import literal_scalar_type
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
)
from scopecat.program.domain import DomainExecution
from scopecat.program.expressions import ComputeResultScalarExpr, lit
from scopecat.program.logical import (
    AcquireEffect,
    ImplementationId,
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
    ValueDef,
)
from scopecat.program.measurements import MeasurementPostprocessor
from scopecat.program.operations import (
    ComputeNodeInputValue,
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.program.parameters import ParameterContract
from scopecat.program.point_domain import PointAxes
from scopecat.program.products import ModuleProductDecl, RecordSelection
from scopecat.program.scans import AxisSpec
from scopecat.program.value_graph import (
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.program.value_refs import (
    PointValueDependency,
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_operation_id,
)
from scopecat.program.values import ComputeFunction


def logical_compute_node_id(symbol: SymbolId) -> OperationId:
    return OperationId(symbol)


def logical_value_id(value: ValueRef) -> ValueId:
    """Return the graph identity already owned by a typed value."""

    operation_id = internal_value_ref_operation_id(value)
    if operation_id is not None:
        return operation_result_id(logical_compute_node_id(operation_id))
    return value.id


class LogicalProgramBuilder:
    """Single sink for localized declarations, values, and ordered effects."""

    def __init__(self) -> None:
        self._definitions: dict[ValueId, ValueDef] = {}
        self._compute_nodes: dict[OperationId, LogicalComputeNode] = {}
        self._measurement_postprocessors: list[LogicalMeasurementPostprocessor] = []
        self._implementations: dict[OperationId, LocalPythonImplementation] = {}

    def add_authored_operation(
        self,
        declaration: ModuleOperationDecl,
        implementation: ComputeFunction,
    ) -> None:
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
            input_types=declaration.input_types,
            result_id=output_id,
            result_type=declaration.output_type,
        )
        self._add_compute_node(operation)
        self._implementations[operation_id] = LocalPythonImplementation(
            id=ImplementationId(
                "python:"
                f"{declaration.declaration_key.value.hex}:"
                f"{operation_id.qualified_name}"
            ),
            kernel=implementation,
        )

    def add_domain_execution(
        self,
        execution: DomainExecution,
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
            results=tuple(
                (result_id, product.product_id)
                for result_id, product in execution.result_bindings
            ),
        )

    def add_effect(
        self,
        effect: (
            BindingIntent
            | EnsureStateIntent
            | InvocationIntent
            | DomainExecution
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
        if isinstance(effect, DomainExecution):
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
        *,
        experiment_id: str,
        kind: str,
        inputs: Mapping[str, object],
        input_ports: Sequence[ModuleInputPort],
        entity_inputs: Sequence[str],
        resource_ports: Sequence[ResourcePort],
        point_dependencies: Sequence[PointValueDependency],
        parameter_overlays: Sequence[AxisSpec],
        product_declarations: Sequence[ModuleProductDecl],
        record_selections: Sequence[RecordSelection],
        parameter_contracts: Sequence[ParameterContract],
        point_domain: PointAxes[ValueRef],
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
        return LogicalProgram(
            experiment_id=experiment_id,
            kind=kind,
            inputs=dict(inputs),
            input_ports=tuple(input_ports),
            entity_inputs=tuple(entity_inputs),
            resource_ports=tuple(resource_ports),
            point_dependencies=tuple(point_dependencies),
            parameter_overlays=tuple(parameter_overlays),
            product_declarations=tuple(product_declarations),
            record_selections=tuple(record_selections),
            parameter_contracts=tuple(parameter_contracts),
            point_domain=point_domain,
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
        if isinstance(lowered, ComputeResultScalarExpr):
            msg = "non-compute logical values must lower to a scalar expression"
            raise TypeError(msg)
        self._add_definition(
            ValueDef(
                id=value_id,
                value_type=value.value_type,
                source=lowered,
            )
        )
        return value_id

    def _add_literal(
        self,
        value_id: ValueId,
        value: object,
    ) -> None:
        value_type = literal_scalar_type(value)
        self._add_definition(
            ValueDef(
                id=value_id,
                value_type=value_type,
                source=lit(input_cell(value), value_type),
            )
        )

    def _add_definition(self, definition: ValueDef) -> None:
        existing = self._definitions.get(definition.id)
        if existing is not None and existing != definition:
            msg = f"logical value {definition.id.qualified_name!r} is redefined"
            raise ValueError(msg)
        self._definitions[definition.id] = definition

    def _add_compute_node(self, operation: LogicalComputeNode) -> None:
        existing = self._compute_nodes.get(operation.id)
        if existing is not None and existing != operation:
            msg = f"semantic operation {operation.id.qualified_name!r} is redefined"
            raise ValueError(msg)
        self._compute_nodes[operation.id] = operation
