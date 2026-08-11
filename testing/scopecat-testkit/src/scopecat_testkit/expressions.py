"""Strict test helpers for scalar expression verification and evaluation."""

from __future__ import annotations

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar as evaluate_selected_scalar,
)
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    verify_scalar_expression,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Scalar
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
    as_scalar_expr,
)

from scopecat_testkit.bound_program import StateAssignmentFixture


def verified_scalar_expr(
    expression: object,
    *,
    bindings: ExpressionTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> ScalarExpr:
    return verify_scalar_expression(
        (
            expression
            if isinstance(expression, ScalarExpr)
            else as_scalar_expr(expression, value_type=expected_type)
        ),
        bindings=bindings or ExpressionTypeBindings(),
        expected_type=expected_type,
    )


def state_property(
    resource_port: LogicalResourcePortId | str,
    *,
    interface_id: str,
    property_id: str,
    component_path: tuple[str, ...] = (),
    value: object | ComputeResultScalarExpr,
    bindings: ExpressionTypeBindings | None = None,
    value_type: Scalar | None = None,
) -> StateAssignmentFixture:
    selected_bindings = bindings or ExpressionTypeBindings()
    return StateAssignmentFixture(
        port_id=(
            resource_port
            if isinstance(resource_port, LogicalResourcePortId)
            else logical_resource_port_id(resource_port)
        ),
        interface_id=interface_id,
        component_path=component_path,
        property_id=property_id,
        value=(
            value
            if isinstance(value, ScalarExpr)
            else verified_scalar_expr(
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
    bindings: ExpressionTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> CellValue:
    selected_bindings = bindings or ExpressionTypeBindings()
    verified = verify_scalar_expression(
        expression,
        bindings=selected_bindings,
        expected_type=expected_type,
    )
    return evaluate_selected_scalar(
        verified,
        ctx,
        bindings=selected_bindings,
        expected_type=expected_type,
    )


__all__ = [
    "evaluate_scalar",
    "state_property",
    "verified_scalar_expr",
]
