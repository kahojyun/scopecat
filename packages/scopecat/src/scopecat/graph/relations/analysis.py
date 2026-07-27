"""Free-input analysis for scalar plans."""

from __future__ import annotations

from typing import cast

from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    InputScalarExpr,
    ParameterLookupScalarExpr,
    ScalarExpr,
    ScalarExpression,
)


def plan_input_refs(root: ScalarExpr) -> tuple[str, ...]:
    """Return free scalar input ids."""

    input_ids: set[str] = set()
    pending = [root]
    while pending:
        scalar = cast("ScalarExpression", pending.pop())
        if isinstance(scalar, InputScalarExpr):
            input_ids.add(scalar.name)
        if isinstance(scalar, ParameterLookupScalarExpr):
            pending.extend(reversed(tuple(scalar.key.values())))
        elif isinstance(scalar, BinaryScalarExpr):
            pending.extend((scalar.right, scalar.left))
    return tuple(sorted(input_ids))
