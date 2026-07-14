from __future__ import annotations

import pytest

from scopecat.compiler.semantic.model import (
    MeasurementTransformId,
    SemanticGraphIR,
    SemanticMeasurementTransform,
)
from scopecat.compiler.semantic.verification import verify_semantic_graph
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import product_id
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.semantics import MeasurementTransformSemanticContract


def _transform(
    local_id: str,
    *,
    source: str = "raw",
    output: str = "derived",
) -> SemanticMeasurementTransform:
    return SemanticMeasurementTransform(
        id=MeasurementTransformId(SymbolId(local_id=local_id)),
        semantic=MeasurementTransformSemanticContract(
            id="test.identity",
            version="1",
        ),
        rate="point",
        inputs=(("source", product_id(source)),),
        outputs=(("result", product_id(output)),),
    )


def _problem_codes(error: CheckFailed) -> list[str]:
    return [problem.code for problem in error.problems]


def test_measurement_transform_roles_are_unique() -> None:
    with pytest.raises(ValueError, match="duplicate measurement transform input"):
        SemanticMeasurementTransform(
            id=MeasurementTransformId(SymbolId(local_id="duplicate-role")),
            semantic=MeasurementTransformSemanticContract(
                id="test.identity",
                version="1",
            ),
            rate="point",
            inputs=(
                ("source", product_id("left")),
                ("source", product_id("right")),
            ),
            outputs=(("result", product_id("derived")),),
        )


def test_duplicate_measurement_transform_id_is_declaration_independent() -> None:
    first = _transform("duplicate", output="first")
    second = _transform("duplicate", output="second")

    errors: list[CheckFailed] = []
    for transforms in ((first, second), (second, first)):
        with pytest.raises(CheckFailed) as caught:
            verify_semantic_graph(
                SemanticGraphIR(measurement_transforms=transforms),
            )
        errors.append(caught.value)

    assert [_problem_codes(error) for error in errors] == [
        ["semantic_measurement_transform_duplicate"],
        ["semantic_measurement_transform_duplicate"],
    ]


def test_transform_output_owner_conflict_is_rejected() -> None:
    first = _transform("first", output="derived")
    second = _transform("second", output="derived")

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(measurement_transforms=(second, first)),
        )

    assert _problem_codes(caught.value) == ["semantic_product_producer_duplicate"]
