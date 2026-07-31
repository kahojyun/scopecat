from __future__ import annotations

import pytest

from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import product_id
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.results import MeasurementValue
from scopecat.program.logical import (
    LogicalMeasurementPostprocessor,
    MeasurementPostprocessorId,
)
from scopecat.program.logical_graph import verify_logical_graph


def _kernel(value: MeasurementValue) -> dict[str, MeasurementValue]:
    return {"result": value}


def _postprocessor(
    local_id: str,
    *,
    source: str = "raw",
    output: str = "derived",
) -> LogicalMeasurementPostprocessor:
    return LogicalMeasurementPostprocessor(
        id=MeasurementPostprocessorId(SymbolId(local_id=local_id)),
        input=product_id(source),
        outputs=(("result", product_id(output)),),
        kernel=_kernel,
    )


def _problem_codes(error: CheckFailed) -> list[str]:
    return [problem.code for problem in error.problems]


def test_duplicate_measurement_postprocessor_id_is_rejected() -> None:
    first = _postprocessor("duplicate", output="first")
    second = _postprocessor("duplicate", output="second")

    with pytest.raises(CheckFailed) as caught:
        verify_logical_graph((), (), (second, first))

    assert _problem_codes(caught.value) == [
        "semantic_measurement_postprocessor_duplicate"
    ]


def test_postprocessor_output_owner_conflict_is_rejected() -> None:
    first = _postprocessor("first", output="derived")
    second = _postprocessor("second", output="derived")

    with pytest.raises(CheckFailed) as caught:
        verify_logical_graph((), (), (second, first))

    assert _problem_codes(caught.value) == ["semantic_product_producer_duplicate"]


def test_postprocessor_input_cannot_be_another_postprocessor_output() -> None:
    first = _postprocessor("first", source="raw", output="middle")
    second = _postprocessor("second", source="middle", output="derived")

    with pytest.raises(CheckFailed) as caught:
        verify_logical_graph((), (), (second, first))

    assert _problem_codes(caught.value) == [
        "semantic_measurement_postprocessor_chaining_unsupported"
    ]
