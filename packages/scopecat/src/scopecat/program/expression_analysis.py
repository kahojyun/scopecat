"""Dependency analysis for scalar expressions."""

from __future__ import annotations

from scopecat.program.expressions import (
    BinaryScalarExpr,
    ComputeResultScalarExpr,
    InputScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
)
from scopecat.program.identities import InvocationKey


def expression_input_refs(root: ScalarExpr) -> tuple[str, ...]:
    """Return free scalar input ids."""

    input_ids: set[str] = set()
    for scalar in scalar_nodes(root):
        if isinstance(scalar, InputScalarExpr):
            input_ids.add(scalar.name)
    return tuple(sorted(input_ids))


def expression_point_refs(root: ScalarExpr) -> tuple[str, ...]:
    """Return point-column ids read by one scalar expression."""

    point_ids = {
        scalar.name
        for scalar in scalar_nodes(root)
        if isinstance(scalar, PointColumnScalarExpr)
    }
    return tuple(sorted(point_ids))


def expression_parameter_refs(root: ScalarExpr) -> tuple[str, ...]:
    """Return scalar and table parameter ids read by one expression."""

    parameter_ids = {
        scalar.name
        for scalar in scalar_nodes(root)
        if isinstance(scalar, ParameterScalarExpr)
    }
    parameter_ids.update(
        scalar.use.table_id
        for scalar in scalar_nodes(root)
        if isinstance(scalar, ParameterLookupScalarExpr)
    )
    return tuple(sorted(parameter_ids))


def expression_module_exports(
    root: ScalarExpr,
) -> tuple[tuple[InvocationKey, str], ...]:
    """Return unresolved module projections in deterministic tree order."""

    return tuple(
        (scalar.invocation_key, scalar.export_id)
        for scalar in scalar_nodes(root)
        if isinstance(scalar, ModuleExportScalarExpr)
    )


def expression_requires_execution(root: ScalarExpr) -> bool:
    """Return whether an expression is an opaque point-local compute result."""

    return any(
        isinstance(scalar, ComputeResultScalarExpr) for scalar in scalar_nodes(root)
    )


def scalar_nodes(root: ScalarExpr) -> tuple[ScalarExpr, ...]:
    """Return scalar nodes in stable depth-first order."""

    selected: list[ScalarExpr] = []
    pending = [root]
    while pending:
        scalar = pending.pop()
        selected.append(scalar)
        if isinstance(scalar, ParameterLookupScalarExpr):
            pending.extend(reversed(tuple(scalar.key.values())))
        elif isinstance(scalar, BinaryScalarExpr):
            pending.extend((scalar.right, scalar.left))
    return tuple(selected)
