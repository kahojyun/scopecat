"""Config-free verification for one fully composed logical program.

This pass owns invariants that depend only on the source graph.  Keeping it
separate from binding prevents malformed dataflow from being hidden behind an
unrelated config or parameter-catalog error.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from scopecat.compiler.frontend.logical_lowering import (
    coerce_logical_inputs,
    validate_consumed_inputs,
)
from scopecat.compiler.frontend.logical_product_validation import (
    verify_product_axis_dependencies,
    verify_product_schema,
)
from scopecat.compiler.frontend.logical_resource_validation import (
    collect_resource_ports,
    verify_effect_resource_ports,
    verify_final_state_resources,
    verify_resource_selector_values,
)
from scopecat.compiler.frontend.logical_value_validation import (
    bind_value_definition_inputs,
    verify_effect_value_references,
    verify_final_state_values,
    verify_scalar_values,
    verify_value_record_references,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.problems import Problem
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.value_types import ValueType
from scopecat.program.expressions import ScalarExpr
from scopecat.program.logical import (
    LogicalComputeNode,
    LogicalProgram,
    ValueDef,
)
from scopecat.program.logical_graph import verify_logical_graph
from scopecat.program.products import ModuleProductDecl


@dataclass(frozen=True, slots=True)
class VerifiedLogicalProgram:
    """The only config-free compiler artifact accepted by binding."""

    program: LogicalProgram
    product_declarations: Mapping[ProductId, ModuleProductDecl]
    scalar_values: Mapping[ValueId, ScalarExpr]
    value_defs: Mapping[ValueId, ValueDef] = field(
        init=False,
        compare=False,
        hash=False,
    )
    operation_results: Mapping[ValueId, LogicalComputeNode] = field(
        init=False,
        compare=False,
        hash=False,
    )
    value_types: Mapping[ValueId, ValueType] = field(
        init=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scalar_values",
            MappingProxyType(dict(self.scalar_values)),
        )
        value_defs = {
            definition.id: definition for definition in self.program.value_defs
        }
        operation_results = {
            operation.result_id: operation for operation in self.program.compute_nodes
        }
        value_types = {
            definition.id: definition.value_type
            for definition in self.program.value_defs
        }
        value_types.update(
            {
                operation.result_id: operation.result_type
                for operation in self.program.compute_nodes
            }
        )
        object.__setattr__(self, "value_defs", MappingProxyType(value_defs))
        object.__setattr__(
            self,
            "operation_results",
            MappingProxyType(operation_results),
        )
        object.__setattr__(self, "value_types", MappingProxyType(value_types))

    @property
    def experiment_id(self) -> str:
        """Return the verified entrypoint identity."""

        return self.program.experiment_id

    @property
    def kind(self) -> str:
        """Return the verified experiment kind."""

        return self.program.kind


def verify_logical_program(program: LogicalProgram) -> VerifiedLogicalProgram:
    """Normalize and close every config-independent invariant once.

    The verifier deliberately has no authoring context or config argument.  A
    successful result therefore proves that config-dependent binding will not
    encounter a missing compute producer, a compute cycle, or a dangling
    logical-resource reference.
    """

    inputs = coerce_logical_inputs(program.input_ports, program.inputs)
    normalized = replace(
        program,
        inputs=inputs,
        value_defs=tuple(
            bind_value_definition_inputs(definition, inputs)
            for definition in program.value_defs
        ),
    )
    problems: list[Problem] = []
    scalar_values = verify_scalar_values(normalized, problems)
    resource_ports = collect_resource_ports(normalized.resource_ports, problems)
    product_declarations = verify_product_schema(normalized, problems)
    try:
        verified_graph = verify_logical_graph(
            normalized.value_defs,
            normalized.compute_nodes,
            normalized.measurement_postprocessors,
            effects=normalized.product_effects,
        )
    except CheckFailed as error:
        problems.extend(error.problems)
        verified_graph = None
    if verified_graph is not None:
        _value_defs, compute_nodes, _measurement_postprocessors = verified_graph
        operation_results = {
            operation.result_id: operation for operation in compute_nodes
        }
        verify_effect_value_references(
            normalized,
            {definition.id for definition in normalized.value_defs},
            operation_results,
            problems,
        )
        verify_value_record_references(
            normalized,
            {definition.id for definition in normalized.value_defs},
            operation_results,
            problems,
        )
    verify_effect_resource_ports(normalized, resource_ports, problems)
    verify_final_state_values(normalized, problems)
    verify_final_state_resources(normalized, resource_ports, problems)
    if verified_graph is not None:
        verify_resource_selector_values(normalized, problems)
        verify_product_axis_dependencies(normalized, problems)
    if problems:
        raise CheckFailed(problems)
    if verified_graph is None:
        raise AssertionError("successful logical verification requires graph proofs")
    value_defs, compute_nodes, measurement_postprocessors = verified_graph
    canonical = replace(
        normalized,
        value_defs=value_defs,
        compute_nodes=compute_nodes,
        measurement_postprocessors=measurement_postprocessors,
    )
    validate_consumed_inputs(canonical, inputs)
    return VerifiedLogicalProgram(
        program=canonical,
        product_declarations=MappingProxyType(product_declarations),
        scalar_values=scalar_values,
    )
