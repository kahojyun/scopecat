from __future__ import annotations

from scopecat.kernel.value_types import Float, Scalar
from tests.testkit.relation_plans import scalar_value_expr


def test_verified_value_expression_exposes_its_relation_plan() -> None:
    value = scalar_value_expr(1.0, expected_type=Scalar(Float()))

    assert value.shape == "scalar"
    assert value.value_type == Scalar(Float())
    assert value.plan.certified_type == value.value_type
