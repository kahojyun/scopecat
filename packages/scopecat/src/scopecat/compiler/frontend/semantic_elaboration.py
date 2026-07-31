"""Close flattened module declarations into the backend-neutral semantic graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from scopecat.compiler.frontend.value_binding import input_cell
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
    ValueSource,
    ValueUse,
)
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
    EnsureStateIntent,
    ExperimentBindingIntent,
    InvocationIntent,
)
from scopecat.program.domain import LoweredDomainExecution
from scopecat.program.identities import ComputeDeclarationKey
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


@dataclass(frozen=True, slots=True)
class SemanticElaboration:
    graph: SemanticGraphIR
    implementations: Mapping[OperationId, LocalPythonImplementation]
    effects: tuple[
        ExperimentBindingIntent
        | EnsureStateIntent
        | InvocationIntent
        | SemanticDomainExecution
        | AcquireEffect,
        ...,
    ]


def elaborate_semantic_graph(
    operations: Sequence[ModuleOperationDecl],
    implementations: Sequence[ScopedPythonImplementation],
    *,
    measurement_postprocessors: Sequence[MeasurementPostprocessor] = (),
    effects: Sequence[
        ExperimentBindingIntent
        | EnsureStateIntent
        | InvocationIntent
        | LoweredDomainExecution
        | AcquireEffect
    ] = (),
    value_roots: Sequence[object] = (),
) -> SemanticElaboration:
    """Assemble one semantic graph and its sidecars from flattened module data."""

    builder = _SemanticGraphBuilder(implementations)
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
    ) -> None:
        self._module_implementations = {
            implementation.operation_id: implementation
            for implementation in implementations
        }
        self._definitions: dict[ValueId, ValueDef] = {}
        self._operations: dict[OperationId, SemanticOperation] = {}
        self._measurement_postprocessors: list[SemanticMeasurementPostprocessor] = []
        self._implementations: dict[OperationId, LocalPythonImplementation] = {}

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
            ExperimentBindingIntent
            | EnsureStateIntent
            | InvocationIntent
            | SemanticDomainExecution
            | AcquireEffect,
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

    def _add_operation(self, operation: SemanticOperation) -> None:
        existing = self._operations.get(operation.id)
        if existing is not None and existing != operation:
            msg = f"semantic operation {operation.id.qualified_name!r} is redefined"
            raise ValueError(msg)
        self._operations[operation.id] = operation
