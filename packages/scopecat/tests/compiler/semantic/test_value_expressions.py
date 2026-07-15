from __future__ import annotations

import copy

import pytest

from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.kernel.value_types import Float, Scalar
from tests.testkit.relation_plans import scalar_value_expr


def test_verified_value_expression_is_an_opaque_shareable_proof() -> None:
    value = scalar_value_expr(1.0, expected_type=Scalar(Float()))

    assert value.shape == "scalar"
    assert value.value_type == Scalar(Float())
    assert copy.copy(value) is value
    assert copy.deepcopy(value) is value
    with pytest.raises(AttributeError, match="cannot assign"):
        value._plan = value.plan  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(TypeError, match="created by verify_scalar_value_expr"):
        ScalarValueExpr()
