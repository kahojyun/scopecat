"""Tests for core value-type compatibility semantics."""

from __future__ import annotations

import pytest

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
