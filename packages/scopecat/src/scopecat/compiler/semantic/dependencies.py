"""Structural dependency facts derived from the semantic value graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.compiler.semantic.model import (
    OperationId,
    SemanticOperation,
    ValueDef,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import OpaqueSemantics


def residual_value_ids(
    definitions: Mapping[ValueId, ValueDef],
    operations: Sequence[SemanticOperation],
) -> frozenset[ValueId]:
    """Return values transitively dependent on an opaque operation.

    The fixed point is deliberately structural. It covers portable pure
    operations applied to opaque results without inventing a stage declaration
    on every intermediate value.
    """

    residual: set[ValueId] = {
        value_id
        for operation in operations
        if isinstance(operation.contract.semantics, OpaqueSemantics)
        for _port, value_id in operation.outputs
    }
    changed = True
    while changed:
        changed = False
        for operation in operations:
            if not any(use.value_id in residual for _name, use in operation.inputs):
                continue
            for _port, value_id in operation.outputs:
                if value_id in definitions and value_id not in residual:
                    residual.add(value_id)
                    changed = True
    return frozenset(residual)


def residual_operation_ids(
    definitions: Mapping[ValueId, ValueDef],
    operations: Sequence[SemanticOperation],
) -> frozenset[OperationId]:
    """Return operations whose outputs require runtime computation."""

    values = residual_value_ids(definitions, operations)
    return frozenset(
        operation.id
        for operation in operations
        if any(value_id in values for _port, value_id in operation.outputs)
    )
