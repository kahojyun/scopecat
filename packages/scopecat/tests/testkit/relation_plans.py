"""Strict test helpers for the verify -> evaluate pipeline."""

from __future__ import annotations

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar as evaluate_selected_scalar,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    verify_scalar_value_expr,
)
from scopecat.compiler.typed.program import set_state_field
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.graph.relations.model import (
    CellValue,
    ScalarExpr,
    as_scalar_expr,
)
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.value_types import Scalar


def scalar_value_expr(
    expression: object,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> ScalarValueExpr:
    return verify_scalar_value_expr(
        (
            expression
            if isinstance(expression, ScalarExpr)
            else as_scalar_expr(expression)
        ),
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )


def state_field(
    resource_port: LogicalResourcePortId | str,
    *,
    capability_id: str,
    field_path: str,
    value: object | ComputeResultRef,
    bindings: RelationTypeBindings | None = None,
    value_type: Scalar | None = None,
) -> SetStateSpec:
    selected_bindings = bindings or RelationTypeBindings()
    return set_state_field(
        resource_port_id=(
            resource_port
            if isinstance(resource_port, LogicalResourcePortId)
            else logical_resource_port_id(resource_port)
        ),
        capability_id=capability_id,
        field_path=field_path,
        value=(
            value
            if isinstance(value, ComputeResultRef)
            else scalar_value_expr(
                value,
                bindings=selected_bindings,
                expected_type=value_type,
            )
        ),
    )


def evaluate_scalar(
    expression: ScalarExpr,
    ctx: EvalContext,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> CellValue:
    verified = verify_relation_plan(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )
    return evaluate_selected_scalar(
        verified,
        ctx,
    )


__all__ = [
    "evaluate_scalar",
    "scalar_value_expr",
    "state_field",
]
