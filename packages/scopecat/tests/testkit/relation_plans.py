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
from scopecat.compiler.typed.program import set_state_property
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Scalar
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
    ScalarExpression,
    as_scalar_expr,
)


def scalar_value_expr(
    expression: object,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> ScalarExpression:
    return verify_relation_plan(
        (
            expression
            if isinstance(expression, ScalarExpr)
            else as_scalar_expr(expression, value_type=expected_type)
        ),
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )


def state_property(
    resource_port: LogicalResourcePortId | str,
    *,
    interface_id: str,
    property_id: str,
    component_path: tuple[str, ...] = (),
    value: object | ComputeResultScalarExpr,
    bindings: RelationTypeBindings | None = None,
    value_type: Scalar | None = None,
) -> SetStateSpec:
    selected_bindings = bindings or RelationTypeBindings()
    return set_state_property(
        resource_port_id=(
            resource_port
            if isinstance(resource_port, LogicalResourcePortId)
            else logical_resource_port_id(resource_port)
        ),
        interface_id=interface_id,
        component_path=component_path,
        property_id=property_id,
        value=(
            value
            if isinstance(value, ComputeResultScalarExpr)
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
    selected_bindings = bindings or RelationTypeBindings()
    verified = verify_relation_plan(
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
    "scalar_value_expr",
    "state_property",
]
