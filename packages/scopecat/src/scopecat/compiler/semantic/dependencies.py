"""Structural dependency facts derived from the semantic value graph."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.compiler.semantic.model import (
    OperationId,
    SemanticOperation,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import OpaqueSemantics


@dataclass(frozen=True, slots=True)
class ResidualDependencyAnalysis:
    """Values and operations that must remain for runtime computation."""

    value_ids: frozenset[ValueId]
    operation_ids: frozenset[OperationId]


def analyze_residual_dependencies(
    operations: Sequence[SemanticOperation],
) -> ResidualDependencyAnalysis:
    """Close runtime values and operations from opaque operation outputs.

    The fixed point is deliberately structural. It covers portable pure
    operations applied to opaque results without inventing a stage declaration
    on every intermediate value.
    """

    selected_operations = tuple(operations)
    residual: set[ValueId] = {
        value_id
        for operation in selected_operations
        if isinstance(operation.contract, OpaqueSemantics)
        for value_id in (operation.result_id,)
    }
    changed = True
    while changed:
        changed = False
        for operation in selected_operations:
            if not any(use.value_id in residual for _name, use in operation.inputs):
                continue
            if operation.result_id not in residual:
                residual.add(operation.result_id)
                changed = True
    value_ids = frozenset(residual)
    return ResidualDependencyAnalysis(
        value_ids=value_ids,
        operation_ids=frozenset(
            operation.id
            for operation in selected_operations
            if operation.result_id in value_ids
        ),
    )
