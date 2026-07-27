from __future__ import annotations

from collections.abc import Sequence

import pytest

from scopecat.sdk.domain.batch import DomainBatchInputs


def test_batch_inputs_expose_named_columns() -> None:
    inputs = DomainBatchInputs(
        program=(("x", (2, 3)),),
        compiler=(),
    )

    assert inputs.program_input("x") == (2, 3)
    with pytest.raises(KeyError):
        inputs.program_input("missing")


def test_batch_inputs_decode_each_compiler_collection() -> None:
    inputs = DomainBatchInputs(
        program=(),
        compiler=(("rows", (({"value": 1},), ({"value": 2}, {"value": 3}))),),
    )

    def decode(rows: Sequence[dict[str, int]]) -> tuple[int, ...]:
        return tuple(row["value"] for row in rows)

    assert inputs.decode_compiler_collection("rows", decode) == ((1,), (2, 3))
