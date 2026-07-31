"""Free-input analysis for scalar plans."""

from __future__ import annotations

from typing import cast

from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    InputScalarExpr,
    ParameterLookupScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
    ScalarExpression,
)


def plan_input_refs(root: ScalarExpr) -> tuple[str, ...]:
    """Return free scalar input ids."""

    input_ids: set[str] = set()
    for scalar in _scalar_nodes(root):
        if isinstance(scalar, InputScalarExpr):
            input_ids.add(scalar.name)
    return tuple(sorted(input_ids))


def plan_point_refs(root: ScalarExpr) -> tuple[str, ...]:
    """Return point-column ids read by one scalar plan."""

    point_ids = {
        scalar.name
        for scalar in _scalar_nodes(root)
        if isinstance(scalar, PointColumnScalarExpr)
    }
    return tuple(sorted(point_ids))


def _scalar_nodes(root: ScalarExpr) -> tuple[ScalarExpression, ...]:
    selected: list[ScalarExpression] = []
    pending = [root]
    while pending:
        scalar = cast("ScalarExpression", pending.pop())
        selected.append(scalar)
        if isinstance(scalar, ParameterLookupScalarExpr):
            pending.extend(reversed(tuple(scalar.key.values())))
        elif isinstance(scalar, BinaryScalarExpr):
            pending.extend((scalar.right, scalar.left))
    return tuple(selected)
