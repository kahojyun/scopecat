"""Tests for core value-type compatibility semantics."""

from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._value_refs import (
    internal_lower_scalar_value_ref,
)
from scopecat.compiler.relations.model import BinaryScalarExpr, LiteralScalarExpr
from scopecat.kernel.value_type_compatibility import (
    describe_value_type,
    is_assignable,
    require_assignable,
)
from scopecat.kernel.value_types import Int, Scalar
from scopecat.kernel.value_validation import ValueValidationError


def test_typed_value_assignability_and_descriptions() -> None:
    narrow = Scalar(Int(minimum=1, maximum=2))
    wide = Scalar(Int(minimum=0, maximum=3))

    assert is_assignable(narrow, wide)
    assert not is_assignable(wide, narrow)
    assert describe_value_type(narrow) == "Scalar[Int]"
    require_assignable(narrow, wide, path=("input", "count"))

    with pytest.raises(ValueValidationError) as error:
        require_assignable(wide, narrow, path=("input", "count"))

    assert error.value.code == "incompatible_value_type"
    assert error.value.path == ("input", "count")


def test_scalar_operations_capture_entity_literal_snapshots() -> None:
    subject = sc.point("subject", sc.ScalarType(sc.EntityType()))
    labels = ["data"]
    entity = sc.EntityRef(id="q0", metadata={"labels": labels})

    expression = subject.eq(entity)
    labels.append("changed")
    lowered = internal_lower_scalar_value_ref(expression)

    assert isinstance(lowered, BinaryScalarExpr)
    assert isinstance(lowered.right, LiteralScalarExpr)
    captured = lowered.right.value
    assert isinstance(captured, sc.EntityRef)
    assert captured.metadata == {"labels": ("data",)}
